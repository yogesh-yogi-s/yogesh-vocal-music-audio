"""VMA v2 opaque source-byte container writer."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable

from vma.models import VMAError

from .constants import HEADER_SIZE_V2, MAGIC, MAX_STREAMS_V2, VERSION_V2
from .format_info import FormatInfoError, FormatInfoTLV, serialize_format_info
from .models import V2Header, V2StreamDescriptor
from .wire import pack_descriptor, pack_header


_COPY_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class V2StreamInput:
    """Writer input for one opaque source-file payload."""

    stream_id: int
    source_path: str | Path
    role: int = 0
    format_id: int = 0
    start_time: int = 0
    duration: int = 0
    format_info: tuple[FormatInfoTLV, ...] = ()
    stream_flags: int = 0
    reserved: int = 0


@dataclass(frozen=True)
class _PreparedStream:
    input: V2StreamInput
    source_path: Path
    source_size: int
    format_info: bytes


def create_vma_v2(
    streams: Iterable[V2StreamInput],
    output_path: str | Path,
    *,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Write a V2 container holding the supplied source-file bytes verbatim."""
    prepared = _prepare_streams(streams)
    metadata_bytes = _serialize_metadata(metadata)
    descriptor_table_offset = HEADER_SIZE_V2 + len(metadata_bytes)
    descriptor_table_size = sum(48 + len(stream.format_info) for stream in prepared)
    payload_offset = descriptor_table_offset + descriptor_table_size

    descriptors_by_id: dict[int, tuple[V2StreamDescriptor, bytes]] = {}
    for stream in prepared:
        descriptor = V2StreamDescriptor(
            stream_id=stream.input.stream_id,
            role=stream.input.role,
            stream_flags=0,
            format_id=stream.input.format_id,
            reserved=0,
            start_time=stream.input.start_time,
            duration=stream.input.duration,
            payload_offset=payload_offset,
            payload_size=stream.source_size,
            format_info_size=len(stream.format_info),
        )
        _validate_representable_descriptor(descriptor)
        descriptors_by_id[descriptor.stream_id] = (descriptor, stream.format_info)
        payload_offset += stream.source_size

    if payload_offset > 0xFFFFFFFFFFFFFFFF:
        raise VMAError("V2 output offsets exceed the u64 wire range")

    header = V2Header(
        magic=MAGIC,
        version=VERSION_V2,
        header_size=HEADER_SIZE_V2,
        stream_count=len(prepared),
        header_flags=0,
        metadata_offset=HEADER_SIZE_V2,
        metadata_size=len(metadata_bytes),
        descriptor_table_offset=descriptor_table_offset,
        descriptor_table_size=descriptor_table_size,
        reserved_1=0,
        reserved_2=0,
    )
    _validate_representable_header(header)

    path = Path(output_path)
    with path.open("wb") as output:
        output.write(pack_header(header))
        output.write(metadata_bytes)
        for stream_id in sorted(descriptors_by_id):
            descriptor, format_info = descriptors_by_id[stream_id]
            output.write(pack_descriptor(descriptor))
            output.write(format_info)
        for stream in prepared:
            _copy_exact_source(stream.source_path, output, stream.source_size)
    return path


def write_vma_v2(
    streams: Iterable[V2StreamInput],
    output_path: str | Path,
    *,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Alias for :func:`create_vma_v2` for explicit writer-oriented callers."""
    return create_vma_v2(streams, output_path, metadata=metadata)


def _prepare_streams(streams: Iterable[V2StreamInput]) -> tuple[_PreparedStream, ...]:
    values = tuple(streams)
    if len(values) > MAX_STREAMS_V2:
        raise VMAError(f"V2 stream count exceeds the reference limit of {MAX_STREAMS_V2}")
    stream_ids: set[int] = set()
    prepared: list[_PreparedStream] = []
    for stream in values:
        _validate_stream_input(stream, stream_ids)
        source_path = Path(stream.source_path)
        try:
            source_size = source_path.stat().st_size
        except OSError as exc:
            raise VMAError(f"unable to stat V2 source file: {source_path}") from exc
        try:
            format_info = serialize_format_info(stream.format_info)
        except FormatInfoError as exc:
            raise VMAError(f"invalid V2 FORMAT_INFO: {exc}") from exc
        prepared.append(_PreparedStream(stream, source_path, source_size, format_info))
    return tuple(prepared)


def _validate_stream_input(stream: V2StreamInput, stream_ids: set[int]) -> None:
    if not isinstance(stream, V2StreamInput):
        raise VMAError("V2 streams must be V2StreamInput instances")
    if not 1 <= stream.stream_id <= 0xFFFFFFFF:
        raise VMAError("V2 stream ID must be a non-zero u32")
    if stream.stream_id in stream_ids:
        raise VMAError("V2 stream IDs must be unique")
    stream_ids.add(stream.stream_id)
    if stream.stream_flags != 0 or stream.reserved != 0:
        raise VMAError("V2 stream flags and reserved fields must be zero")
    if not 0 <= stream.role <= 0xFFFF:
        raise VMAError("V2 role is outside the u16 range")
    if not 0 <= stream.format_id <= 0xFFFF:
        raise VMAError("V2 format ID is outside the u16 range")
    if not -0x8000000000000000 <= stream.start_time <= 0x7FFFFFFFFFFFFFFF:
        raise VMAError("V2 start time is outside the i64 range")
    if stream.start_time < 0:
        raise VMAError("V2 writers require a non-negative start time")
    if not 0 <= stream.duration <= 0xFFFFFFFFFFFFFFFF:
        raise VMAError("V2 duration is outside the u64 range")


def _serialize_metadata(metadata: dict[str, Any] | None) -> bytes:
    if metadata is None:
        return b""
    if not isinstance(metadata, dict):
        raise VMAError("V2 metadata must be a JSON object")
    if type(metadata.get("schema_version")) is not int or metadata["schema_version"] != 1:
        raise VMAError("V2 metadata schema_version must be the integer 1")
    try:
        return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VMAError("V2 metadata is not JSON serializable") from exc


def _validate_representable_header(header: V2Header) -> None:
    if header.metadata_size > 0xFFFFFFFFFFFFFFFF or header.descriptor_table_size > 0xFFFFFFFFFFFFFFFF:
        raise VMAError("V2 header size fields exceed the u64 wire range")
    if header.descriptor_table_offset > 0xFFFFFFFFFFFFFFFF:
        raise VMAError("V2 descriptor table offset exceeds the u64 wire range")


def _validate_representable_descriptor(descriptor: V2StreamDescriptor) -> None:
    if descriptor.format_info_size > 0xFFFFFFFF:
        raise VMAError("V2 FORMAT_INFO size exceeds the u32 wire range")
    if descriptor.payload_offset > 0xFFFFFFFFFFFFFFFF or descriptor.payload_size > 0xFFFFFFFFFFFFFFFF:
        raise VMAError("V2 payload fields exceed the u64 wire range")


def _copy_exact_source(source_path: Path, output, expected_size: int) -> None:
    copied = 0
    try:
        with source_path.open("rb") as source:
            while chunk := source.read(_COPY_CHUNK_SIZE):
                output.write(chunk)
                copied += len(chunk)
    except OSError as exc:
        raise VMAError(f"unable to read V2 source file: {source_path}") from exc
    if copied != expected_size:
        raise VMAError("V2 source file changed while it was being packaged")
