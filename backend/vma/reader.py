from __future__ import annotations

import json
from pathlib import Path

from .audio import _validate_pcm_descriptor
from .format import HEADER_SIZE, HEADER_STRUCT, MAGIC, MAX_FILE_SIZE, MAX_METADATA_SIZE, MAX_STREAMS, STREAM_ENTRY_SIZE, STREAM_STRUCT, VERSION
from .models import Codec, PayloadRange, StreamInfo, StreamType, VMAError, VMAFile


def read_vma(vma_path: str | Path) -> VMAFile:
    """Read and fully validate a VMA v0.1 container before exposing its streams."""
    path = Path(vma_path)
    file_size = path.stat().st_size
    if file_size < HEADER_SIZE:
        raise VMAError("VMA is too small for its fixed header")
    if file_size > MAX_FILE_SIZE:
        raise VMAError("VMA exceeds the v0.1 2 GiB safety limit")
    with path.open("rb") as source:
        fields = HEADER_STRUCT.unpack(_read_exact(source, HEADER_SIZE, "VMA header"))
        magic, version, reserved, header_size, stream_count, metadata_size, entry_size, flags = fields
        if magic != MAGIC:
            raise VMAError("invalid VMA magic bytes")
        if version != VERSION:
            raise VMAError(f"unsupported VMA version {version}")
        if reserved != 0 or flags != 0:
            raise VMAError("unsupported VMA header flags")
        if stream_count != 2 or stream_count > MAX_STREAMS:
            raise VMAError("VMA v0.1 requires exactly two streams")
        if entry_size != STREAM_ENTRY_SIZE:
            raise VMAError("unsupported VMA stream entry size")
        if metadata_size > MAX_METADATA_SIZE:
            raise VMAError("VMA metadata exceeds the safety limit")
        expected_header_size = HEADER_SIZE + metadata_size + stream_count * entry_size
        if header_size != expected_header_size or header_size > file_size:
            raise VMAError("VMA header size is inconsistent or outside the file")
        metadata = _metadata(_read_exact(source, metadata_size, "VMA metadata"))
        streams = tuple(_parse_stream(_read_exact(source, entry_size, "stream entry"), header_size, file_size) for _ in range(stream_count))
    _validate_stream_set(streams)
    return VMAFile(path=path, version=version, metadata=metadata, streams=streams)


def _metadata(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VMAError("VMA metadata is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise VMAError("VMA metadata must be a JSON object")
    return value


def _parse_stream(raw: bytes, header_size: int, file_size: int) -> StreamInfo:
    stream_id, type_id, codec_id, sample_rate, channels, bit_depth, start_sample, sample_count, data_offset, data_size, reserved = STREAM_STRUCT.unpack(raw)
    if stream_id == 0 or reserved != b"\0" * 16:
        raise VMAError("invalid VMA stream identifier or reserved bytes")
    try:
        stream_type, codec = StreamType(type_id), Codec(codec_id)
    except ValueError as exc:
        raise VMAError("VMA contains an unsupported stream type or codec") from exc
    if codec is not Codec.PCM_WAV_LE:
        raise VMAError("unsupported VMA codec")
    audio = _validate_pcm_descriptor(
        sample_rate=sample_rate, channels=channels, bit_depth=bit_depth,
        sample_count=sample_count, data_size=data_size,
    )
    if start_sample < 0:
        raise VMAError("VMA stream synchronization fields are invalid")
    payload = PayloadRange(data_offset, data_size)
    if payload.offset < header_size or payload.end > file_size:
        raise VMAError("VMA stream data range is outside the file")
    return StreamInfo(stream_id, stream_type, codec, audio, start_sample, payload.offset, payload.size)


def _validate_stream_set(streams: tuple[StreamInfo, ...]) -> None:
    if {stream.stream_id for stream in streams} != {1, 2}:
        raise VMAError("VMA stream IDs must be unique")
    if {stream.stream_type for stream in streams} != {StreamType.VOCAL, StreamType.MUSIC}:
        raise VMAError("VMA must contain one vocal and one music stream")
    payloads = [PayloadRange(stream.data_offset, stream.data_size) for stream in streams]
    intervals = sorted((payload.offset, payload.end) for payload in payloads)
    if intervals[0][1] > intervals[1][0]:
        raise VMAError("VMA stream data regions overlap")


def _read_exact(source, size: int, name: str) -> bytes:
    value = source.read(size)
    if len(value) != size:
        raise VMAError(f"unexpected end of file while reading {name}")
    return value
