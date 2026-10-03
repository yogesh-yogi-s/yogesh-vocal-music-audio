"""Application-layer adapter between FastAPI uploads and the VMA library."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from backend.vma import create_vma, extract_all, extract_music, extract_vocal, read_vma, validate_vma
from backend.vma.models import VMAFile

MAX_UPLOAD_BYTES = 500 * 1024 * 1024


async def store_upload(upload: UploadFile, destination: Path) -> Path:
    """Save an upload under an application-chosen filename and enforce a size limit."""
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


def create_container(
    vocal_path: Path,
    music_path: Path,
    output_path: Path,
    *,
    title: str,
    artist: str,
    vocal_start_sample: int = 0,
    music_start_sample: int = 0,
) -> VMAFile:
    create_vma(
        vocal_path,
        music_path,
        output_path,
        {"title": title, "artist": artist},
        vocal_start_sample=vocal_start_sample,
        music_start_sample=music_start_sample,
    )
    return read_vma(output_path)


def validation_payload(container: VMAFile) -> dict[str, Any]:
    return {"valid": True, **info_payload(container)}


def info_payload(container: VMAFile) -> dict[str, Any]:
    return {
        "version": container.version,
        "metadata": container.metadata,
        "duration_seconds": container.duration_seconds,
        "stream_count": len(container.streams),
        "streams": [stream_payload(stream) for stream in container.streams],
    }


def stream_payload(stream) -> dict[str, Any]:
    return {
        "stream_id": stream.stream_id,
        "type": stream.stream_type.name.lower(),
        "codec": stream.codec.name,
        "sample_rate": stream.audio.sample_rate,
        "channels": stream.audio.channels,
        "bit_depth": stream.audio.bit_depth,
        "start_sample": stream.start_sample,
        "sample_count": stream.audio.sample_count,
        "data_offset": stream.data_offset,
        "data_size": stream.data_size,
        "duration_seconds": stream.audio.duration_seconds,
    }


def extract_track(vma_path: Path, kind: str, output_path: Path) -> Path:
    if kind == "vocal":
        return extract_vocal(vma_path, output_path)
    if kind == "music":
        return extract_music(vma_path, output_path)
    raise ValueError(f"unsupported VMA stream type: {kind}")


def cleanup_directory(path: str | Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
