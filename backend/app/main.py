from __future__ import annotations

import asyncio
import base64
from functools import partial
import hashlib
import hmac
import logging
import secrets
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.vma import create_vma, extract_all, extract_music, extract_vocal, peek_vma_version
from backend.vma.audio import parse_pcm_wav
from backend.vma.models import StreamType, VMAError
from backend.vma.v2.models import V2File
from backend.app import vma_service
from backend.app.resource_control import (
    MAX_ACTIVE_SESSION_OPERATIONS,
    MAX_BROWSER_SESSIONS,
    MAX_PROCESS_SESSIONS,
    MULTIPART_OVERHEAD_BYTES,
    ResourceProtectionMiddleware,
    ResourceGovernor,
)
from backend.app.deployment_security import (
    DeploymentSecurityMiddleware,
    load_deployment_settings,
)

logger = logging.getLogger(__name__)
SESSION_TTL_SECONDS = 2 * 60 * 60
OWNER_COOKIE_NAME = "vma_owner"
OWNER_FILE_NAME = ".owner"
DELETED_FILE_NAME = ".deleted"
ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
DEMO_VMA_PATH = Path(__file__).resolve().parent / "assets" / "welcome-demo.vma"


class GuaranteedCleanupFileResponse(FileResponse):
    """Run local cleanup after success, send failure, or request cancellation."""

    def __init__(self, *args, cleanup, cleanup_args=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.cleanup = cleanup
        self.cleanup_args = cleanup_args

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            await asyncio.to_thread(self.cleanup, *self.cleanup_args)


@asynccontextmanager
async def lifespan(app: FastAPI):
    deployment_settings = load_deployment_settings()
    temp_base = deployment_settings.temp_base
    if temp_base is not None:
        if not temp_base.is_dir():
            raise RuntimeError("VMA_TEMP_ROOT must name an existing directory")
        temp_root = Path(tempfile.mkdtemp(prefix="vma-local-", dir=temp_base))
    else:
        temp_root = Path(tempfile.mkdtemp(prefix="vma-local-"))
    app.state.deployment_settings = deployment_settings
    app.state.ready = False
    app.state.temp_root = temp_root
    app.state.storage = temp_root / "sessions"
    app.state.work_storage = temp_root / "work"
    try:
        app.state.storage.mkdir()
        app.state.work_storage.mkdir()
    except BaseException:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise
    app.state.session_guard = threading.Lock()
    app.state.active_sessions = {}
    app.state.owner_signing_key = secrets.token_bytes(32)
    app.state.resource_governor = ResourceGovernor(temp_root)
    app.state.ready = True
    cleanup_task = asyncio.create_task(_cleanup_expired_sessions(app))
    try:
        yield
    finally:
        app.state.ready = False
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task
        shutil.rmtree(temp_root, ignore_errors=True)


APP_VERSION = "0.3"

app = FastAPI(title=f"VMA v{APP_VERSION}", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(ResourceProtectionMiddleware)
app.add_middleware(DeploymentSecurityMiddleware)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/ready")
def readiness(request: Request):
    """Report whether this process can accept work using its configured storage."""
    if not getattr(request.app.state, "ready", False):
        raise HTTPException(503, "service is not ready")
    for directory in (
        request.app.state.temp_root,
        request.app.state.storage,
        request.app.state.work_storage,
    ):
        if not directory.is_dir():
            raise HTTPException(503, "service is not ready")
    try:
        shutil.disk_usage(request.app.state.temp_root)
        with tempfile.NamedTemporaryFile(dir=request.app.state.work_storage):
            pass
    except OSError as exc:
        raise HTTPException(503, "service is not ready") from exc
    return {"status": "ready"}


@app.post("/api/demo")
def open_welcome_demo(request: Request):
    """Open the fixed bundled demo in its own ordinary ephemeral session."""
    _require_same_origin(request)
    job, owner_token = _new_session(request)
    try:
        if not DEMO_VMA_PATH.is_file():
            raise HTTPException(503, "Welcome demo is temporarily unavailable")
        target = job / "song.vma"
        shutil.copyfile(DEMO_VMA_PATH, target)
        _enforce_session_size(job)
        payload = vma_service.container_payload(vma_service.read_container(target), job.name)
        payload["demo"] = True
        response = JSONResponse(payload)
        _set_owner_cookie(response, request, owner_token)
        return response
    except HTTPException:
        shutil.rmtree(job, ignore_errors=True)
        raise
    except (OSError, VMAError) as exc:
        shutil.rmtree(job, ignore_errors=True)
        logger.exception("Bundled VMA welcome demo could not be opened")
        raise HTTPException(503, "Welcome demo is temporarily unavailable") from exc


def _safe_upload_suffix(filename: str | None, default: str = ".bin") -> str:
    if not filename:
        return default
    suffix = Path(filename).suffix.lower()
    if suffix and all(c.isalnum() for c in suffix.lstrip(".")) and len(suffix) <= 10:
        return suffix
    return default


def _new_work_directory(app: FastAPI, prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=app.state.work_storage))


def _zip_v1_tracks(vma_path: Path, directory: Path) -> Path:
    output_directory = directory / "tracks"
    vocal, music = extract_all(vma_path, output_directory)
    archive = directory / "vma-tracks.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(vocal, "vocal.wav")
        bundle.write(music, "music.wav")
    return archive


def _remove_paths(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


async def _run_blocking(function, *args):
    """Keep a worker alive through caller cancellation, then let cleanup run safely."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except BaseException:
            pass
        raise


def _enforce_session_size(directory: Path) -> None:
    limit = 2 * vma_service.MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES
    size = sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
    if size > limit:
        raise HTTPException(507, "session storage limit exceeded")


@app.post("/api/vma/create", tags=["VMA"])
async def api_create_vma(
    request: Request,
    vocal: UploadFile = File(..., description="Vocal audio stream"),
    music: UploadFile = File(..., description="Music / Instrumental audio stream"),
    title: str = Form(""),
    artist: str = Form(""),
    vocal_start_sample: int = Form(0),
    music_start_sample: int = Form(0),
    version: int | None = Form(None),
):
    directory = _new_work_directory(request.app, "create-")
    try:
        vocal_ext = _safe_upload_suffix(vocal.filename, default=".bin")
        music_ext = _safe_upload_suffix(music.filename, default=".bin")
        vocal_path = await vma_service.store_upload(vocal, directory / f"vocal-input{vocal_ext}")
        music_path = await vma_service.store_upload(music, directory / f"music-input{music_ext}")
        output = directory / "song.vma"
        container = await _run_blocking(
            partial(
                vma_service.create_container,
                vocal_path, music_path, output,
                title=title, artist=artist,
                vocal_start_sample=vocal_start_sample,
                music_start_sample=music_start_sample,
                version=version,
                vocal_filename=vocal.filename,
                music_filename=music.filename,
                vocal_content_type=vocal.content_type,
                music_content_type=music.content_type,
            )
        )
        await _run_blocking(_remove_paths, vocal_path, music_path)
        is_v2 = isinstance(container, V2File)
        version_num = container.header.version if is_v2 else container.version
        stream_count = len(container.streams)
        if is_v2:
            durations = [s.descriptor.duration for s in container.streams if s.descriptor.duration]
            duration = (max(durations) / vma_service.NANOSECONDS_PER_SECOND) if durations else 0.0
        else:
            duration = container.duration_seconds
        return GuaranteedCleanupFileResponse(
            output,
            media_type="application/vnd.vma",
            filename="song.vma",
            headers={
                "X-VMA-Version": str(version_num),
                "X-VMA-Stream-Count": str(stream_count),
                "X-VMA-Duration-Seconds": f"{duration:.6f}",
            },
            cleanup=vma_service.cleanup_directory,
            cleanup_args=(directory,),
        )
    except VMAError as exc:
        vma_service.cleanup_directory(directory)
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
        vma_service.cleanup_directory(directory)
        raise
    except asyncio.CancelledError:
        vma_service.cleanup_directory(directory)
        raise
    except Exception as exc:
        vma_service.cleanup_directory(directory)
        logger.exception("VMA API creation failed")
        raise HTTPException(500, "VMA creation failed") from exc


@app.post("/api/vma/validate", tags=["VMA"])
async def api_validate_vma(request: Request, file: UploadFile = File(..., description="VMA container")):
    with tempfile.TemporaryDirectory(prefix="validate-", dir=request.app.state.work_storage) as directory:
        try:
            path = await vma_service.store_upload(file, Path(directory) / "input.vma")
            container = await _run_blocking(vma_service.read_container, path)
            return vma_service.validation_payload(container)
        except VMAError as exc:
            raise HTTPException(422, str(exc)) from exc


@app.post("/api/vma/info", tags=["VMA"])
async def api_vma_info(request: Request, file: UploadFile = File(..., description="VMA container")):
    with tempfile.TemporaryDirectory(prefix="info-", dir=request.app.state.work_storage) as directory:
        try:
            path = await vma_service.store_upload(file, Path(directory) / "input.vma")
            container = await _run_blocking(vma_service.read_container, path)
            return vma_service.info_payload(container)
        except VMAError as exc:
            raise HTTPException(422, str(exc)) from exc


async def _api_extract(request: Request, file: UploadFile, kind: str):
    directory = _new_work_directory(request.app, f"extract-{kind}-")
    try:
        source = await vma_service.store_upload(file, directory / "input.vma")
        output = await _run_blocking(
            vma_service.extract_track, source, kind, directory / f"{kind}.wav"
        )
        await _run_blocking(_remove_paths, source)
        return GuaranteedCleanupFileResponse(
            output, media_type="audio/wav", filename=f"{kind}.wav",
            cleanup=vma_service.cleanup_directory, cleanup_args=(directory,),
        )
    except VMAError as exc:
        vma_service.cleanup_directory(directory)
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
        vma_service.cleanup_directory(directory)
        raise
    except asyncio.CancelledError:
        vma_service.cleanup_directory(directory)
        raise
    except Exception as exc:
        vma_service.cleanup_directory(directory)
        logger.exception("VMA API extraction failed")
        raise HTTPException(500, "VMA extraction failed") from exc


@app.post("/api/vma/extract/vocal", tags=["VMA"])
async def api_extract_vocal(request: Request, file: UploadFile = File(..., description="VMA container")):
    return await _api_extract(request, file, "vocal")


@app.post("/api/vma/extract/music", tags=["VMA"])
async def api_extract_music(request: Request, file: UploadFile = File(..., description="VMA container")):
    return await _api_extract(request, file, "music")


@app.post("/api/vma/extract/all", tags=["VMA"])
async def api_extract_all(request: Request, file: UploadFile = File(..., description="VMA container")):
    directory = _new_work_directory(request.app, "extract-all-")
    try:
        source = await vma_service.store_upload(file, directory / "input.vma")
        archive = await _run_blocking(_zip_v1_tracks, source, directory)
        await _run_blocking(_remove_paths, source)
        return GuaranteedCleanupFileResponse(
            archive, media_type="application/zip", filename="vma-tracks.zip",
            cleanup=vma_service.cleanup_directory, cleanup_args=(directory,),
        )
    except VMAError as exc:
        vma_service.cleanup_directory(directory)
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
        vma_service.cleanup_directory(directory)
        raise
    except asyncio.CancelledError:
        vma_service.cleanup_directory(directory)
        raise
    except Exception as exc:
        vma_service.cleanup_directory(directory)
        logger.exception("VMA API extract-all failed")
        raise HTTPException(500, "VMA extraction failed") from exc


@app.post("/api/create")
async def create_container(
    request: Request,
    vocal: UploadFile = File(...),
    music: UploadFile = File(...),
    title: str = Form(""),
    artist: str = Form(""),
    vocal_start_sample: int = Form(0),
    music_start_sample: int = Form(0),
    version: int | None = Form(None),
):
    _require_same_origin(request)
    job, owner_token = _new_session(request)
    try:
        vocal_ext = _safe_upload_suffix(vocal.filename, default=".bin")
        music_ext = _safe_upload_suffix(music.filename, default=".bin")
        vocal_path = await vma_service.store_upload(vocal, job / f"vocal-input{vocal_ext}")
        music_path = await vma_service.store_upload(music, job / f"music-input{music_ext}")
        output = job / "song.vma"
        container = await _run_blocking(
            partial(
                vma_service.create_container,
                vocal_path, music_path, output,
                title=title, artist=artist,
                vocal_start_sample=vocal_start_sample,
                music_start_sample=music_start_sample,
                version=version,
                vocal_filename=vocal.filename,
                music_filename=music.filename,
                vocal_content_type=vocal.content_type,
                music_content_type=music.content_type,
            )
        )
        await _run_blocking(_remove_paths, vocal_path, music_path)
        _enforce_session_size(job)
        is_v2 = isinstance(container, V2File)
        version_num = container.header.version if is_v2 else container.version
        response = FileResponse(
            output,
            media_type="application/vnd.vma",
            filename="song.vma",
            headers={"X-VMA-Session": job.name, "X-VMA-Version": str(version_num)},
        )
        _set_owner_cookie(response, request, owner_token)
        return response
    except VMAError as exc:
        shutil.rmtree(job, ignore_errors=True)
        raise HTTPException(400, str(exc)) from exc
    except HTTPException:
        shutil.rmtree(job, ignore_errors=True)
        raise
    except asyncio.CancelledError:
        shutil.rmtree(job, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(job, ignore_errors=True)
        logger.exception("VMA creation failed")
        raise HTTPException(500, "VMA creation failed; see the local server log for details") from exc


@app.post("/api/open")
async def open_container(request: Request, file: UploadFile = File(...)):
    _require_same_origin(request)
    job, owner_token = _new_session(request)
    try:
        vma_path = await vma_service.store_upload(file, job / "song.vma")
        container = await _run_blocking(vma_service.read_container, vma_path)
        _enforce_session_size(job)
        response = JSONResponse(vma_service.container_payload(container, job.name))
        _set_owner_cookie(response, request, owner_token)
        return response
    except VMAError as exc:
        shutil.rmtree(job, ignore_errors=True)
        raise HTTPException(400, str(exc)) from exc
    except HTTPException:
        shutil.rmtree(job, ignore_errors=True)
        raise
    except asyncio.CancelledError:
        shutil.rmtree(job, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(job, ignore_errors=True)
        logger.exception("VMA open failed")
        raise HTTPException(500, "VMA open failed; see the local server log for details") from exc


@app.get("/api/vma/{session_id}")
def inspect_container(request: Request, session_id: str):
    source = _acquire_session(request, session_id)
    try:
        container = vma_service.read_container(source)
        response = JSONResponse(vma_service.container_payload(container, session_id))
        response.headers["Cache-Control"] = "private, no-store"
        return response
    finally:
        _release_session(request.app, session_id)


@app.get("/api/vma/{session_id}/stream/{kind}")
def playback_stream(request: Request, session_id: str, kind: str):
    source = _acquire_session(request, session_id)
    response_directory = None
    try:
        _require_v1_container(source)
        stream_type = _stream_type(kind)
        response_directory = _new_session_response_directory(source)
        target = response_directory / f"play-{kind}.wav"
        extractor = extract_vocal if stream_type is StreamType.VOCAL else extract_music
        extractor(source, target)
        return _leased_file_response(
            request, session_id, target, media_type="audio/wav", filename=f"{kind}.wav"
        )
    except BaseException:
        if response_directory is not None:
            shutil.rmtree(response_directory, ignore_errors=True)
        _release_session(request.app, session_id)
        raise


@app.get("/api/vma/{session_id}/extract/{kind}")
def extract_track(request: Request, session_id: str, kind: str):
    source = _acquire_session(request, session_id)
    response_directory = None
    try:
        _require_v1_container(source)
        stream_type = _stream_type(kind)
        response_directory = _new_session_response_directory(source)
        target = response_directory / f"{kind}.wav"
        extractor = extract_vocal if stream_type is StreamType.VOCAL else extract_music
        extractor(source, target)
        return _leased_file_response(
            request, session_id, target, media_type="audio/wav", filename=f"{kind}.wav"
        )
    except BaseException:
        if response_directory is not None:
            shutil.rmtree(response_directory, ignore_errors=True)
        _release_session(request.app, session_id)
        raise


@app.get("/api/vma/{session_id}/extract-all")
def extract_everything(request: Request, session_id: str):
    source = _acquire_session(request, session_id)
    response_directory = None
    try:
        _require_v1_container(source)
        response_directory = _new_session_response_directory(source)
        archive = _zip_v1_tracks(source, response_directory)
        return _leased_file_response(
            request, session_id, archive, media_type="application/zip", filename="vma-tracks.zip"
        )
    except BaseException:
        if response_directory is not None:
            shutil.rmtree(response_directory, ignore_errors=True)
        _release_session(request.app, session_id)
        raise


@app.get("/api/vma/{session_id}/extract-stream/{stream_id}")
def extract_stream(request: Request, session_id: str, stream_id: int):
    """Extract a single stream. V2 payloads are returned byte-for-byte."""
    source = _acquire_session(request, session_id)
    response_directory = None
    try:
        container = vma_service.read_container(source)
        if isinstance(container, V2File):
            stream = vma_service.find_v2_stream(container, stream_id)
            if stream is None:
                raise HTTPException(404, "VMA session resource not found")
            info = vma_service.stream_download_info(stream)
            response_directory = _new_session_response_directory(source)
            target = response_directory / f"v2-stream-{stream_id}.bin"
            vma_service.extract_track_v2(source, stream_id, target)
            return _leased_file_response(
                request, session_id, target,
                media_type=info["media_type"], filename=info["filename"],
            )
        if stream_id not in (StreamType.VOCAL, StreamType.MUSIC):
            raise HTTPException(404, "VMA session resource not found")
        stream_type = StreamType(stream_id)
        kind = stream_type.name.lower()
        response_directory = _new_session_response_directory(source)
        target = response_directory / f"{kind}.wav"
        extractor = extract_vocal if stream_type is StreamType.VOCAL else extract_music
        extractor(source, target)
        return _leased_file_response(
            request, session_id, target, media_type="audio/wav", filename=f"{kind}.wav"
        )
    except BaseException:
        if response_directory is not None:
            shutil.rmtree(response_directory, ignore_errors=True)
        _release_session(request.app, session_id)
        raise


@app.delete("/api/vma/{session_id}", status_code=204)
def delete_session(request: Request, session_id: str):
    """Revoke an owned session immediately and remove it after active responses finish."""
    _require_same_origin(request)
    _mark_session_deleted(request, session_id)
    return Response(status_code=204)


def _valid_owner_token(app: FastAPI, token: str | None) -> bool:
    if token is None or not 80 <= len(token) <= 96:
        return False
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (ValueError, UnicodeEncodeError):
        return False
    if len(raw) != 64:
        return False
    nonce, signature = raw[:32], raw[32:]
    expected = hmac.digest(app.state.owner_signing_key, nonce, "sha256")
    return hmac.compare_digest(signature, expected)


def _new_owner_token(app: FastAPI) -> str:
    nonce = secrets.token_bytes(32)
    signature = hmac.digest(app.state.owner_signing_key, nonce, "sha256")
    return base64.urlsafe_b64encode(nonce + signature).rstrip(b"=").decode("ascii")


def _owner_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _new_session(request: Request) -> tuple[Path, str]:
    token = request.cookies.get(OWNER_COOKIE_NAME)
    if not _valid_owner_token(request.app, token):
        token = _new_owner_token(request.app)
    digest = _owner_digest(token)
    with request.app.state.session_guard:
        sessions = [path for path in request.app.state.storage.iterdir() if path.is_dir()]
        if len(sessions) >= MAX_PROCESS_SESSIONS:
            raise HTTPException(
                429, "server session limit exceeded", headers={"Retry-After": "60"}
            )
        owned_sessions = 0
        for directory in sessions:
            try:
                if hmac.compare_digest(
                    (directory / OWNER_FILE_NAME).read_text(encoding="ascii"), digest
                ):
                    owned_sessions += 1
            except OSError:
                continue
        if owned_sessions >= MAX_BROWSER_SESSIONS:
            raise HTTPException(
                429, "browser session limit exceeded", headers={"Retry-After": "60"}
            )
        job = request.app.state.storage / uuid.uuid4().hex
        job.mkdir(parents=True, exist_ok=False)
        (job / OWNER_FILE_NAME).write_text(digest, encoding="ascii")
    return job, token


def _local_development_request(request: Request) -> bool:
    hostname = (request.url.hostname or "").lower()
    client_host = (request.client.host if request.client else "").lower()
    local_hosts = {"127.0.0.1", "::1", "localhost", "testserver"}
    local_clients = {"127.0.0.1", "::1", "localhost", "testclient"}
    return hostname in local_hosts and client_host in local_clients


def _set_owner_cookie(response: Response, request: Request, token: str) -> None:
    settings = request.app.state.deployment_settings
    response.set_cookie(
        OWNER_COOKIE_NAME,
        token,
        httponly=True,
        secure=(
            settings.production
            or request.url.scheme == "https"
            or not _local_development_request(request)
        ),
        samesite="strict",
        path="/api",
    )
    response.headers["Cache-Control"] = "no-store"


def _require_same_origin(request: Request) -> None:
    fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if fetch_site == "cross-site":
        raise HTTPException(403, "request origin is not allowed")
    origin = request.headers.get("origin")
    if origin is None:
        if request.app.state.deployment_settings.production:
            raise HTTPException(403, "request origin is not allowed")
        return
    try:
        supplied = urlsplit(origin)
    except ValueError as exc:
        raise HTTPException(403, "request origin is not allowed") from exc
    canonical = f"{supplied.scheme.lower()}://{supplied.netloc.lower()}"
    settings = request.app.state.deployment_settings
    expected = f"{request.url.scheme.lower()}://{request.url.netloc.lower()}"
    allowed = settings.allowed_origins or (expected,)
    if (
        origin == "null"
        or canonical not in allowed
        or supplied.username is not None
        or supplied.password is not None
        or supplied.path not in {"", "/"}
        or supplied.query
        or supplied.fragment
    ):
        raise HTTPException(403, "request origin is not allowed")


def _session_not_found() -> HTTPException:
    return HTTPException(404, "VMA session not found")


def _session_id_is_valid(session_id: str) -> bool:
    return (
        len(session_id) == 32
        and all(character in "0123456789abcdef" for character in session_id)
    )


def _owned_session_path_locked(request: Request, session_id: str) -> Path:
    token = request.cookies.get(OWNER_COOKIE_NAME)
    if not _session_id_is_valid(session_id) or not _valid_owner_token(request.app, token):
        raise _session_not_found()
    directory = request.app.state.storage / session_id
    source = directory / "song.vma"
    owner_file = directory / OWNER_FILE_NAME
    if (directory / DELETED_FILE_NAME).exists() or not source.is_file() or not owner_file.is_file():
        raise _session_not_found()
    try:
        stored_digest = owner_file.read_text(encoding="ascii")
    except OSError as exc:
        raise _session_not_found() from exc
    if not hmac.compare_digest(stored_digest, _owner_digest(token)):
        raise _session_not_found()
    try:
        expired = time.time() - source.stat().st_mtime > SESSION_TTL_SECONDS
    except OSError as exc:
        raise _session_not_found() from exc
    if expired:
        (directory / DELETED_FILE_NAME).touch(exist_ok=True)
        if request.app.state.active_sessions.get(session_id, 0) == 0:
            shutil.rmtree(directory, ignore_errors=True)
        raise _session_not_found()
    source.touch()
    return source


def _acquire_session(request: Request, session_id: str) -> Path:
    with request.app.state.session_guard:
        source = _owned_session_path_locked(request, session_id)
        active = request.app.state.active_sessions
        if active.get(session_id, 0) >= MAX_ACTIVE_SESSION_OPERATIONS:
            raise HTTPException(429, "session operation limit exceeded", headers={"Retry-After": "1"})
        active[session_id] = active.get(session_id, 0) + 1
        return source


def _release_session(app: FastAPI, session_id: str) -> None:
    remove = None
    with app.state.session_guard:
        active = app.state.active_sessions
        remaining = max(0, active.get(session_id, 1) - 1)
        if remaining:
            active[session_id] = remaining
        else:
            active.pop(session_id, None)
            directory = app.state.storage / session_id
            if (directory / DELETED_FILE_NAME).exists():
                remove = directory
    if remove is not None:
        shutil.rmtree(remove, ignore_errors=True)


def _new_session_response_directory(source: Path) -> Path:
    directory = source.parent / f".response-{uuid.uuid4().hex}"
    directory.mkdir()
    return directory


def _finish_leased_response(app: FastAPI, session_id: str, directory: Path) -> None:
    shutil.rmtree(directory, ignore_errors=True)
    _release_session(app, session_id)


def _leased_file_response(
    request: Request,
    session_id: str,
    path: Path,
    *,
    media_type: str,
    filename: str,
) -> FileResponse:
    response = GuaranteedCleanupFileResponse(
        path,
        media_type=media_type,
        filename=filename,
        cleanup=_finish_leased_response,
        cleanup_args=(request.app, session_id, path.parent),
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _mark_session_deleted(request: Request, session_id: str) -> None:
    remove = None
    with request.app.state.session_guard:
        source = _owned_session_path_locked(request, session_id)
        directory = source.parent
        (directory / DELETED_FILE_NAME).touch(exist_ok=True)
        if request.app.state.active_sessions.get(session_id, 0) == 0:
            remove = directory
    if remove is not None:
        shutil.rmtree(remove, ignore_errors=True)


def _stream_type(kind: str) -> StreamType:
    try:
        return {"vocal": StreamType.VOCAL, "music": StreamType.MUSIC}[kind]
    except KeyError as exc:
        raise HTTPException(404, "unknown stream") from exc


def _require_v1_container(source: Path) -> None:
    """Reject non-V1 containers so V2 never enters the V1-only playback path."""
    try:
        version = peek_vma_version(source)
    except VMAError as exc:
        raise HTTPException(400, str(exc)) from exc
    if version != 1:
        raise HTTPException(
            409,
            "This route serves V1 streams; V2 containers expose each stream via "
            "/api/vma/{session_id}/extract-stream/{stream_id}.",
        )


async def _cleanup_expired_sessions(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(10 * 60)
        await asyncio.to_thread(_cleanup_expired_sessions_once, app)
        app.state.resource_governor.prune_rates()


def _cleanup_expired_sessions_once(app: FastAPI) -> None:
    cutoff = time.time() - SESSION_TTL_SECONDS
    try:
        directories = list(app.state.storage.iterdir())
    except OSError:
        logger.exception("Could not scan VMA session storage")
        return
    for directory in directories:
        remove = False
        try:
            with app.state.session_guard:
                if not directory.is_dir() or app.state.active_sessions.get(directory.name, 0):
                    continue
                song = directory / "song.vma"
                remove = (directory / DELETED_FILE_NAME).exists() or (
                    song.stat().st_mtime < cutoff
                    if song.is_file()
                    else directory.stat().st_mtime < cutoff
                )
                if remove:
                    (directory / DELETED_FILE_NAME).touch(exist_ok=True)
            if remove:
                shutil.rmtree(directory, ignore_errors=True)
        except OSError:
            logger.exception("Could not clean VMA session directory")


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
