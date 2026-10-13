from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
import uuid
import zipfile
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from backend.vma import create_vma, extract_all, extract_music, extract_vocal, peek_vma_version
from backend.vma.audio import parse_pcm_wav
from backend.vma.models import StreamType, VMAError
from backend.vma.v2.models import V2File
from backend.app import vma_service

logger = logging.getLogger(__name__)
SESSION_TTL_SECONDS = 2 * 60 * 60
ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage = Path(tempfile.mkdtemp(prefix="vma-local-"))
    app.state.storage = storage
    cleanup_task = asyncio.create_task(_cleanup_expired_sessions(storage))
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task
        shutil.rmtree(storage, ignore_errors=True)


APP_VERSION = "0.3"

app = FastAPI(title=f"VMA v{APP_VERSION}", version=APP_VERSION, lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/vma/create", tags=["VMA"])
async def api_create_vma(
    vocal: UploadFile = File(..., description="Uncompressed PCM Vocal WAV"),
    music: UploadFile = File(..., description="Uncompressed PCM Music WAV"),
    title: str = Form(""),
    artist: str = Form(""),
    vocal_start_sample: int = Form(0),
    music_start_sample: int = Form(0),
):
    directory = Path(tempfile.mkdtemp(prefix="vma-create-"))
    try:
        vocal_path = await vma_service.store_upload(vocal, directory / "vocal-input.wav")
        music_path = await vma_service.store_upload(music, directory / "music-input.wav")
        output = directory / "song.vma"
        container = vma_service.create_container(
            vocal_path, music_path, output,
            title=title, artist=artist,
            vocal_start_sample=vocal_start_sample,
            music_start_sample=music_start_sample,
        )
        return FileResponse(
            output,
            media_type="application/vnd.vma",
            filename="song.vma",
            headers={
                "X-VMA-Version": str(container.version),
                "X-VMA-Stream-Count": str(len(container.streams)),
                "X-VMA-Duration-Seconds": f"{container.duration_seconds:.6f}",
            },
            background=BackgroundTask(vma_service.cleanup_directory, directory),
        )
    except VMAError as exc:
        vma_service.cleanup_directory(directory)
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
        vma_service.cleanup_directory(directory)
        raise
    except Exception as exc:
        vma_service.cleanup_directory(directory)
        logger.exception("VMA API creation failed")
        raise HTTPException(500, "VMA creation failed") from exc


@app.post("/api/vma/validate", tags=["VMA"])
async def api_validate_vma(file: UploadFile = File(..., description="VMA container")):
    with tempfile.TemporaryDirectory(prefix="vma-validate-") as directory:
        try:
            path = await vma_service.store_upload(file, Path(directory) / "input.vma")
            return vma_service.validation_payload(vma_service.read_container(path))
        except VMAError as exc:
            raise HTTPException(422, str(exc)) from exc


@app.post("/api/vma/info", tags=["VMA"])
async def api_vma_info(file: UploadFile = File(..., description="VMA container")):
    with tempfile.TemporaryDirectory(prefix="vma-info-") as directory:
        try:
            path = await vma_service.store_upload(file, Path(directory) / "input.vma")
            return vma_service.info_payload(vma_service.read_container(path))
        except VMAError as exc:
            raise HTTPException(422, str(exc)) from exc


async def _api_extract(file: UploadFile, kind: str):
    directory = Path(tempfile.mkdtemp(prefix=f"vma-extract-{kind}-"))
    try:
        source = await vma_service.store_upload(file, directory / "input.vma")
        output = vma_service.extract_track(source, kind, directory / f"{kind}.wav")
        return FileResponse(
            output, media_type="audio/wav", filename=f"{kind}.wav",
            background=BackgroundTask(vma_service.cleanup_directory, directory),
        )
    except VMAError as exc:
        vma_service.cleanup_directory(directory)
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
        vma_service.cleanup_directory(directory)
        raise
    except Exception as exc:
        vma_service.cleanup_directory(directory)
        logger.exception("VMA API extraction failed")
        raise HTTPException(500, "VMA extraction failed") from exc


@app.post("/api/vma/extract/vocal", tags=["VMA"])
async def api_extract_vocal(file: UploadFile = File(..., description="VMA container")):
    return await _api_extract(file, "vocal")


@app.post("/api/vma/extract/music", tags=["VMA"])
async def api_extract_music(file: UploadFile = File(..., description="VMA container")):
    return await _api_extract(file, "music")


@app.post("/api/vma/extract/all", tags=["VMA"])
async def api_extract_all(file: UploadFile = File(..., description="VMA container")):
    directory = Path(tempfile.mkdtemp(prefix="vma-extract-all-"))
    try:
        source = await vma_service.store_upload(file, directory / "input.vma")
        output_directory = directory / "tracks"
        vocal, music = extract_all(source, output_directory)
        archive = directory / "vma-tracks.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(vocal, "vocal.wav")
            bundle.write(music, "music.wav")
        return FileResponse(
            archive, media_type="application/zip", filename="vma-tracks.zip",
            background=BackgroundTask(vma_service.cleanup_directory, directory),
        )
    except VMAError as exc:
        vma_service.cleanup_directory(directory)
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
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
):
    job = _job_directory(request)
    try:
        vocal_path = await vma_service.store_upload(vocal, job / "vocal-input.wav")
        music_path = await vma_service.store_upload(music, job / "music-input.wav")
        # Parse now so technical input errors reach the user before container writing.
        parse_pcm_wav(vocal_path)
        parse_pcm_wav(music_path)
        output = create_vma(
            vocal_path, music_path, job / "song.vma",
            {"title": title, "artist": artist},
            vocal_start_sample=vocal_start_sample,
            music_start_sample=music_start_sample,
        )
        return FileResponse(
            output,
            media_type="application/vnd.vma",
            filename="song.vma",
            headers={"X-VMA-Session": job.name},
        )
    except VMAError as exc:
        shutil.rmtree(job, ignore_errors=True)
        raise HTTPException(400, str(exc)) from exc
    except HTTPException:
        shutil.rmtree(job, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(job, ignore_errors=True)
        logger.exception("VMA creation failed")
        raise HTTPException(500, "VMA creation failed; see the local server log for details") from exc


@app.post("/api/open")
async def open_container(request: Request, file: UploadFile = File(...)):
    job = _job_directory(request)
    try:
        vma_path = await vma_service.store_upload(file, job / "song.vma")
        container = vma_service.read_container(vma_path)
        return vma_service.container_payload(container, job.name)
    except VMAError as exc:
        shutil.rmtree(job, ignore_errors=True)
        raise HTTPException(400, str(exc)) from exc
    except HTTPException:
        shutil.rmtree(job, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(job, ignore_errors=True)
        logger.exception("VMA open failed")
        raise HTTPException(500, "VMA open failed; see the local server log for details") from exc


@app.get("/api/vma/{session_id}")
def inspect_container(request: Request, session_id: str):
    container = vma_service.read_container(_session_path(request, session_id))
    return vma_service.container_payload(container, session_id)


@app.get("/api/vma/{session_id}/stream/{kind}")
def playback_stream(request: Request, session_id: str, kind: str):
    source = _session_path(request, session_id)
    _require_v1_container(source)
    stream_type = _stream_type(kind)
    target = source.parent / f"play-{kind}.wav"
    extractor = extract_vocal if stream_type is StreamType.VOCAL else extract_music
    extractor(source, target)
    return FileResponse(target, media_type="audio/wav", filename=f"{kind}.wav")


@app.get("/api/vma/{session_id}/extract/{kind}")
def extract_track(request: Request, session_id: str, kind: str):
    source = _session_path(request, session_id)
    _require_v1_container(source)
    stream_type = _stream_type(kind)
    target = source.parent / f"{kind}.wav"
    extractor = extract_vocal if stream_type is StreamType.VOCAL else extract_music
    extractor(source, target)
    return FileResponse(target, media_type="audio/wav", filename=f"{kind}.wav")


@app.get("/api/vma/{session_id}/extract-all")
def extract_everything(request: Request, session_id: str):
    source = _session_path(request, session_id)
    _require_v1_container(source)
    directory = source.parent / "all"
    extract_all(source, directory)
    archive = source.parent / "vma-tracks.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(directory / "vocal.wav", "vocal.wav")
        bundle.write(directory / "music.wav", "music.wav")
    return FileResponse(archive, media_type="application/zip", filename="vma-tracks.zip")


@app.get("/api/vma/{session_id}/extract-stream/{stream_id}")
def extract_stream(request: Request, session_id: str, stream_id: int):
    """Extract a single stream. V2 payloads are returned byte-for-byte."""
    source = _session_path(request, session_id)
    container = vma_service.read_container(source)
    if isinstance(container, V2File):
        stream = vma_service.find_v2_stream(container, stream_id)
        if stream is None:
            raise HTTPException(404, "V2 container does not contain that stream")
        info = vma_service.stream_download_info(stream)
        target = source.parent / f"v2-stream-{stream_id}.bin"
        vma_service.extract_track_v2(source, stream_id, target)
        return FileResponse(target, media_type=info["media_type"], filename=info["filename"])
    if stream_id not in (StreamType.VOCAL, StreamType.MUSIC):
        raise HTTPException(404, "unknown V1 stream")
    stream_type = StreamType(stream_id)
    kind = stream_type.name.lower()
    target = source.parent / f"{kind}.wav"
    extractor = extract_vocal if stream_type is StreamType.VOCAL else extract_music
    extractor(source, target)
    return FileResponse(target, media_type="audio/wav", filename=f"{kind}.wav")


def _job_directory(request: Request) -> Path:
    job = request.app.state.storage / uuid.uuid4().hex
    job.mkdir(parents=True, exist_ok=False)
    return job


def _session_path(request: Request, session_id: str) -> Path:
    if not session_id or any(char not in "0123456789abcdef" for char in session_id) or len(session_id) != 32:
        raise HTTPException(404, "VMA session not found")
    path = request.app.state.storage / session_id / "song.vma"
    if not path.is_file():
        raise HTTPException(404, "VMA session not found")
    if time.time() - path.stat().st_mtime > SESSION_TTL_SECONDS:
        shutil.rmtree(path.parent, ignore_errors=True)
        raise HTTPException(404, "VMA session has expired")
    path.touch()
    return path


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


async def _cleanup_expired_sessions(storage: Path) -> None:
    while True:
        await asyncio.sleep(10 * 60)
        cutoff = time.time() - SESSION_TTL_SECONDS
        for directory in storage.iterdir():
            song = directory / "song.vma"
            if directory.is_dir() and (not song.exists() or song.stat().st_mtime < cutoff):
                shutil.rmtree(directory, ignore_errors=True)


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
