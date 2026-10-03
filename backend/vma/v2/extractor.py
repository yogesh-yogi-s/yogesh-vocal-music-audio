"""Verbatim payload extraction for VMA v2 containers."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from vma.models import VMAError

from .models import V2File, V2Stream
from .reader import read_vma_v2


_COPY_CHUNK_SIZE = 1024 * 1024


def extract_stream_v2(vma_path: str | Path, stream_id: int, output_path: str | Path) -> Path:
    """Copy one selected V2 payload byte range to *output_path* verbatim."""
    container = read_vma_v2(vma_path)
    stream = _stream_for_id(container, stream_id)
    return _copy_payload(container, stream, Path(output_path))


def extract_all_v2(
    vma_path: str | Path,
    output_paths: Mapping[int, str | Path],
) -> tuple[Path, ...]:
    """Extract all streams to caller-selected paths in descriptor order.

    The caller supplies every destination explicitly; V2 FORMAT_INFO does not
    define an extraction naming or collision policy.
    """
    container = read_vma_v2(vma_path)
    stream_ids = {stream.descriptor.stream_id for stream in container.streams}
    if set(output_paths) != stream_ids:
        raise VMAError("V2 output paths must specify exactly the container stream IDs")
    return tuple(
        _copy_payload(container, stream, Path(output_paths[stream.descriptor.stream_id]))
        for stream in container.streams
    )


def _stream_for_id(container: V2File, stream_id: int) -> V2Stream:
    for stream in container.streams:
        if stream.descriptor.stream_id == stream_id:
            return stream
    raise VMAError(f"V2 container does not contain stream ID {stream_id}")


def _copy_payload(container: V2File, stream: V2Stream, output_path: Path) -> Path:
    descriptor = stream.descriptor
    output_path.parent.mkdir(parents=True, exist_ok=True)
    remaining = descriptor.payload_size
    with container.path.open("rb") as source, output_path.open("wb") as output:
        source.seek(descriptor.payload_offset)
        while remaining:
            block = source.read(min(_COPY_CHUNK_SIZE, remaining))
            if not block:
                raise VMAError("validated V2 payload ended unexpectedly during extraction")
            output.write(block)
            remaining -= len(block)
    return output_path
