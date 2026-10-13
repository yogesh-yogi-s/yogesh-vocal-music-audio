"""Application-layer adapter between FastAPI uploads and the VMA library."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from backend.vma import (
    create_vma,
    extract_all,
    extract_music,
    extract_stream_v2,
    extract_vocal,
    read_vma_any,
    validate_vma,
)
from backend.vma.formats.registry import FORMAT_REGISTRY
from backend.vma.models import VMAFile
from backend.vma.v2.constants import (
    ROLE_AUDIO_PRIMARY,
    ROLE_AUDIO_SUPPLEMENTAL,
    ROLE_METADATA_SIDECAR,
    ROLE_UNKNOWN,
)
from backend.vma.v2.format_info import FILE_EXTENSION, MEDIA_TYPE, SOURCE_FILENAME, parse_format_info
from backend.vma.v2.models import V2File

MAX_UPLOAD_BYTES = 500 * 1024 * 1024
NANOSECONDS_PER_SECOND = 1_000_000_000

# V2 roles are generic; vocal/music are application-level labels, so the raw
# u16 role is always reported and only known values are named.
_ROLE_NAMES = {
    ROLE_UNKNOWN: "UNKNOWN",
    ROLE_AUDIO_PRIMARY: "AUDIO_PRIMARY",
    ROLE_AUDIO_SUPPLEMENTAL: "AUDIO_SUPPLEMENTAL",
    ROLE_METADATA_SIDECAR: "METADATA_SIDECAR",
}


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
    return read_vma_any(output_path)


def read_container(vma_path: str | Path) -> VMAFile | V2File:
    """Read a V1 or V2 container through the shared version dispatcher."""
    return read_vma_any(vma_path)


def validation_payload(container: VMAFile | V2File) -> dict[str, Any]:
    return {"valid": True, **info_payload(container)}


def info_payload(container: VMAFile | V2File) -> dict[str, Any]:
    if isinstance(container, V2File):
        return v2_container_body(container)
    return {
        "version": container.version,
        "metadata": container.metadata,
        "duration_seconds": container.duration_seconds,
        "stream_count": len(container.streams),
        "streams": [stream_payload(stream) for stream in container.streams],
    }


def container_payload(container: VMAFile | V2File, session_id: str) -> dict[str, Any]:
    """Build the /api/open and /api/vma/{id} payload for either container version."""
    if isinstance(container, V2File):
        return {"session_id": session_id, **v2_container_body(container)}
    return {
        "session_id": session_id,
        "version": container.version,
        "metadata": container.metadata,
        "duration_seconds": container.duration_seconds,
        "streams": [stream.to_dict() for stream in container.streams],
    }


def stream_payload(stream) -> dict[str, Any]:
    """Flat V1 stream descriptor used by the multipart info/validate routes."""
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


def v2_container_body(container: V2File) -> dict[str, Any]:
    """Version-2 container description; never assumes V1-only fields."""
    durations = [stream.descriptor.duration for stream in container.streams if stream.descriptor.duration]
    return {
        "version": container.header.version,
        "metadata": container.metadata,
        "duration_seconds": (max(durations) / NANOSECONDS_PER_SECOND) if durations else None,
        "stream_count": len(container.streams),
        "streams": [v2_stream_payload(stream, container.metadata) for stream in container.streams],
    }


def v2_stream_payload(stream, metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Describe one V2 stream without decoding or claiming playback support."""
    descriptor = stream.descriptor
    info = format_info_fields(stream.format_info)
    lookup = FORMAT_REGISTRY.lookup(descriptor.format_id)
    return {
        "stream_id": descriptor.stream_id,
        "role": descriptor.role,
        "role_name": _ROLE_NAMES.get(descriptor.role, "RESERVED"),
        "format_id": descriptor.format_id,
        "format_name": lookup.entry.canonical_name if lookup.known else None,
        "format_range": lookup.range.value,
        "start_seconds": descriptor.start_time / NANOSECONDS_PER_SECOND,
        "duration_seconds": (descriptor.duration / NANOSECONDS_PER_SECOND) if descriptor.duration else None,
        "payload_size": descriptor.payload_size,
        "source_filename": info.get("source_filename"),
        "media_type": info.get("media_type"),
        "file_extension": info.get("file_extension"),
        "download_filename": download_filename(descriptor, info),
        "label": stream_label(descriptor, info, metadata),
    }


def format_info_fields(raw: bytes) -> dict[str, str]:
    """Extract only the three defined V2 FORMAT_INFO text fields, preserving first wins."""
    fields: dict[str, str] = {}
    for tlv in parse_format_info(raw).tlvs:
        if tlv.base_type == SOURCE_FILENAME and "source_filename" not in fields:
            fields["source_filename"] = tlv.value.decode("utf-8")
        elif tlv.base_type == MEDIA_TYPE and "media_type" not in fields:
            fields["media_type"] = tlv.value.decode("ascii")
        elif tlv.base_type == FILE_EXTENSION and "file_extension" not in fields:
            fields["file_extension"] = tlv.value.decode("ascii")
    return fields


def download_filename(descriptor, info: dict[str, str]) -> str:
    """Prefer the declared source basename; otherwise synthesize a safe name."""
    name = info.get("source_filename")
    if name:
        return name
    extension = info.get("file_extension")
    return f"stream-{descriptor.stream_id}" + (f".{extension}" if extension else ".bin")


def stream_label(descriptor, info: dict[str, str], metadata: dict[str, Any] | None) -> str:
    """Resolve a display label, preferring application-level metadata over format."""
    labels = (metadata or {}).get("stream_labels")
    if isinstance(labels, dict):
        label = labels.get(str(descriptor.stream_id))
        if isinstance(label, str) and label:
            return label
    if info.get("source_filename"):
        return info["source_filename"]
    lookup = FORMAT_REGISTRY.lookup(descriptor.format_id)
    if lookup.known:
        return lookup.entry.canonical_name
    return f"Stream {descriptor.stream_id}"


def find_v2_stream(container: V2File, stream_id: int):
    for stream in container.streams:
        if stream.descriptor.stream_id == stream_id:
            return stream
    return None


def stream_download_info(stream) -> dict[str, str]:
    """Return the response filename and media type for one V2 stream payload."""
    info = format_info_fields(stream.format_info)
    return {
        "filename": download_filename(stream.descriptor, info),
        "media_type": info.get("media_type") or "application/octet-stream",
    }


def extract_track(vma_path: Path, kind: str, output_path: Path) -> Path:
    if kind == "vocal":
        return extract_vocal(vma_path, output_path)
    if kind == "music":
        return extract_music(vma_path, output_path)
    raise ValueError(f"unsupported VMA stream type: {kind}")


def extract_track_v2(vma_path: Path, stream_id: int, output_path: Path) -> Path:
    """Copy one V2 payload verbatim; bytes are never transformed."""
    return extract_stream_v2(vma_path, stream_id, output_path)


def cleanup_directory(path: str | Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
