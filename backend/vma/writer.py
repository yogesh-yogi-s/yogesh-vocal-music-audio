from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .audio import parse_pcm_wav
from .format import HEADER_SIZE, HEADER_STRUCT, MAGIC, STREAM_ENTRY_SIZE, STREAM_STRUCT, VERSION
from .models import Codec, StreamType, VMAError


def create_vma(
    vocal_path: str | Path,
    music_path: str | Path,
    output_path: str | Path,
    metadata: dict[str, Any] | None = None,
    *,
    vocal_start_sample: int = 0,
    music_start_sample: int = 0,
) -> Path:
    """Create a VMA v0.1 file from two strict PCM WAV files.

    vocal_start_sample and music_start_sample are non-negative frame offsets
    on the shared playback timeline.  Both default to 0, preserving the v0.1
    behaviour for all existing callers.
    """
    if vocal_start_sample < 0:
        raise VMAError("vocal_start_sample must be >= 0")
    if music_start_sample < 0:
        raise VMAError("music_start_sample must be >= 0")
    vocal_path, music_path, output_path = map(Path, (vocal_path, music_path, output_path))
    vocal, music = parse_pcm_wav(vocal_path), parse_pcm_wav(music_path)
    user_metadata = metadata or {}
    if not isinstance(user_metadata, dict):
        raise VMAError("metadata must be a JSON-compatible object")
    info = {
        "title": str(user_metadata.get("title", "")),
        "artist": str(user_metadata.get("artist", "")),
        "vocal_filename": vocal_path.name,
        "music_filename": music_path.name,
        "created_utc": datetime.now(UTC).isoformat(),
    }
    metadata_bytes = json.dumps(info, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    header_size = HEADER_SIZE + len(metadata_bytes) + 2 * STREAM_ENTRY_SIZE
    vocal_offset = header_size
    music_offset = vocal_offset + vocal.data_size
    if music_offset + music.data_size > 2 * 1024 * 1024 * 1024:
        raise VMAError("VMA file exceeds the v0.1 2 GiB safety limit")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as output:
        output.write(HEADER_STRUCT.pack(MAGIC, VERSION, 0, header_size, 2, len(metadata_bytes), STREAM_ENTRY_SIZE, 0))
        output.write(metadata_bytes)
        output.write(_entry(1, StreamType.VOCAL, vocal.audio, vocal_offset, vocal.data_size, vocal_start_sample))
        output.write(_entry(2, StreamType.MUSIC, music.audio, music_offset, music.data_size, music_start_sample))
        _copy_region(vocal_path, vocal.data_offset, vocal.data_size, output)
        _copy_region(music_path, music.data_offset, music.data_size, output)
    return output_path


def _entry(stream_id, stream_type, audio, data_offset, data_size, start_sample: int = 0) -> bytes:
    return STREAM_STRUCT.pack(
        stream_id, int(stream_type), int(Codec.PCM_WAV_LE), audio.sample_rate, audio.channels,
        audio.bit_depth, start_sample, audio.sample_count, data_offset, data_size, b"\0" * 16,
    )


def _copy_region(path: Path, offset: int, size: int, output) -> None:
    with path.open("rb") as source:
        source.seek(offset)
        remaining = size
        while remaining:
            block = source.read(min(1024 * 1024, remaining))
            if not block:
                raise VMAError("source WAV ended before its data chunk")
            output.write(block)
            remaining -= len(block)
