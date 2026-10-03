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

from backend.vma import create_vma, extract_all, extract_music, extract_vocal, read_vma
from backend.vma.audio import parse_pcm_wav
from backend.vma.models import StreamType, VMAError

logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
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


app = FastAPI(title="VMA v0.1", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/create")
async def create_container(
    request: Request,
    vocal: UploadFile = File(...),
    music: UploadFile = File(...),
    title: str = Form(""),
    artist: str = Form(""),
):
    job = _job_directory(request)
    try:
        vocal_path = await _store_upload(vocal, job / "vocal-input.wav")
        music_path = await _store_upload(music, job / "music-input.wav")
        # Parse now so technical input errors reach the user before container writing.
        parse_pcm_wav(vocal_path)
        parse_pcm_wav(music_path)
        output = create_vma(vocal_path, music_path, job / "song.vma", {"title": title, "artist": artist})
        return FileResponse(output, media_type="application/vnd.vma", filename="song.vma")
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
        vma_path = await _store_upload(file, job / "song.vma")
        container = read_vma(vma_path)
        return _container_payload(container, job.name)
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
    return _container_payload(read_vma(_session_path(request, session_id)), session_id)


@app.get("/api/vma/{session_id}/stream/{kind}")
def playback_stream(request: Request, session_id: str, kind: str):
    stream_type = _stream_type(kind)
    source = _session_path(request, session_id)
    target = source.parent / f"play-{kind}.wav"
    extractor = extract_vocal if stream_type is StreamType.VOCAL else extract_music
    extractor(source, target)
    return FileResponse(target, media_type="audio/wav", filename=f"{kind}.wav")


@app.get("/api/vma/{session_id}/extract/{kind}")
def extract_track(request: Request, session_id: str, kind: str):
    stream_type = _stream_type(kind)
    source = _session_path(request, session_id)
    target = source.parent / f"{kind}.wav"
    extractor = extract_vocal if stream_type is StreamType.VOCAL else extract_music
    extractor(source, target)
    return FileResponse(target, media_type="audio/wav", filename=f"{kind}.wav")


@app.get("/api/vma/{session_id}/extract-all")
def extract_everything(request: Request, session_id: str):
    source = _session_path(request, session_id)
    directory = source.parent / "all"
    extract_all(source, directory)
    archive = source.parent / "vma-tracks.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(directory / "vocal.wav", "vocal.wav")
        bundle.write(directory / "music.wav", "music.wav")
    return FileResponse(archive, media_type="application/zip", filename="vma-tracks.zip")


def _job_directory(request: Request) -> Path:
    job = request.app.state.storage / uuid.uuid4().hex
    job.mkdir(parents=True, exist_ok=False)
    return job


async def _store_upload(upload: UploadFile, destination: Path) -> Path:
    total = 0
    with destination.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                output.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(413, "uploads are limited to 500 MB each")
            output.write(chunk)
    if total == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(400, "uploaded file is empty")
    return destination


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


def _container_payload(container, session_id: str) -> dict:
    return {
        "session_id": session_id,
        "version": container.version,
        "metadata": container.metadata,
        "duration_seconds": container.duration_seconds,
        "streams": [stream.to_dict() for stream in container.streams],
    }


async def _cleanup_expired_sessions(storage: Path) -> None:
    while True:
        await asyncio.sleep(10 * 60)
        cutoff = time.time() - SESSION_TTL_SECONDS
        for directory in storage.iterdir():
            song = directory / "song.vma"
            if directory.is_dir() and (not song.exists() or song.stat().st_mtime < cutoff):
                shutil.rmtree(directory, ignore_errors=True)


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
