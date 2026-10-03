"""Structural reader for VMA v2 containers.

V2 payloads are opaque source-file bytes.  This reader validates their ranges
only; it does not inspect or decode any payload content.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import BinaryIO

from vma.models import VMAError

from .constants import (
    DESCRIPTOR_FIXED_SIZE_V2,
    HEADER_SIZE_V2,
    MAGIC,
    MAX_FORMAT_INFO_BYTES_V2,
    MAX_METADATA_BYTES_V2,
    MAX_STREAMS_V2,
    VERSION_V2,
)
from .format_info import FormatInfoError, parse_format_info
from .models import V2File, V2Header, V2Stream, V2StreamDescriptor
from .wire import V2WireError, unpack_descriptor, unpack_header


def read_vma_v2(vma_path: str | Path) -> V2File:
    """Read and structurally validate a version-2 VMA container only."""
    path = Path(vma_path)
    file_size = path.stat().st_size
    if file_size < HEADER_SIZE_V2:
        raise VMAError("VMA is too small for its V2 fixed header")

    with path.open("rb") as source:
        header = _read_header(source)
        _validate_header(header, file_size)

        metadata = _read_metadata(source, header, file_size)
        streams = _read_streams(source, header, file_size)

    _validate_payload_regions(header, streams, file_size)
    return V2File(path=path, header=header, metadata=metadata, streams=streams)


def _read_header(source: BinaryIO) -> V2Header:
    try:
        header = unpack_header(_read_exact(source, HEADER_SIZE_V2, "V2 fixed header"))
    except V2WireError as exc:
        raise VMAError("truncated V2 fixed header") from exc
    if header.magic != MAGIC:
        raise VMAError("invalid VMA magic bytes")
    if header.version != VERSION_V2:
        raise VMAError(f"unsupported VMA version {header.version}")
    # This guard intentionally precedes every descriptor allocation or read.
    if header.stream_count > MAX_STREAMS_V2:
        raise VMAError(f"V2 stream count exceeds the reference limit of {MAX_STREAMS_V2}")
    return header


def _validate_header(header: V2Header, file_size: int) -> None:
    if header.header_size != HEADER_SIZE_V2:
        raise VMAError("invalid V2 header size")
    if header.header_flags != 0 or header.reserved_1 != 0 or header.reserved_2 != 0:
        raise VMAError("V2 header flags and reserved fields must be zero")
    if header.metadata_offset != HEADER_SIZE_V2:
        raise VMAError("invalid V2 metadata offset")
    if header.descriptor_table_offset != header.metadata_offset + header.metadata_size:
        raise VMAError("invalid V2 descriptor table offset")
    if header.metadata_size > MAX_METADATA_BYTES_V2:
        raise VMAError(f"V2 metadata exceeds the {MAX_METADATA_BYTES_V2}-byte reference implementation limit")
    _validate_range(header.metadata_offset, header.metadata_size, file_size, "V2 metadata")
    _validate_range(header.descriptor_table_offset, header.descriptor_table_size, file_size, "V2 descriptor table")


def _read_metadata(source: BinaryIO, header: V2Header, file_size: int) -> dict | None:
    if header.metadata_size == 0:
        return None
    source.seek(header.metadata_offset)
    raw = _read_exact(source, header.metadata_size, "V2 metadata")
    try:
        metadata = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VMAError("V2 metadata is not valid UTF-8 JSON") from exc
    if not isinstance(metadata, dict):
        raise VMAError("V2 metadata must be a JSON object")
    if type(metadata.get("schema_version")) is not int or metadata["schema_version"] != 1:
        raise VMAError("V2 metadata schema_version must be the integer 1")
    return metadata


def _read_streams(source: BinaryIO, header: V2Header, file_size: int) -> tuple[V2Stream, ...]:
    source.seek(header.descriptor_table_offset)
    table_end = header.descriptor_table_offset + header.descriptor_table_size
    streams: list[V2Stream] = []
    stream_ids: set[int] = set()

    for _ in range(header.stream_count):
        if table_end - source.tell() < DESCRIPTOR_FIXED_SIZE_V2:
            raise VMAError("truncated V2 stream descriptor")
        try:
            descriptor = unpack_descriptor(_read_exact(source, DESCRIPTOR_FIXED_SIZE_V2, "V2 stream descriptor"))
        except V2WireError as exc:
            raise VMAError("truncated V2 stream descriptor") from exc
        _validate_descriptor(descriptor, stream_ids)
        if descriptor.format_info_size > MAX_FORMAT_INFO_BYTES_V2:
            raise VMAError(
                f"V2 FORMAT_INFO exceeds the {MAX_FORMAT_INFO_BYTES_V2}-byte reference implementation limit"
            )
        if descriptor.format_info_size > table_end - source.tell():
            raise VMAError("V2 FORMAT_INFO exceeds the descriptor table boundary")
        format_info = _read_exact(source, descriptor.format_info_size, "V2 FORMAT_INFO")
        try:
            parse_format_info(format_info, format_info_size=descriptor.format_info_size)
        except FormatInfoError as exc:
            raise VMAError(f"invalid V2 FORMAT_INFO: {exc}") from exc
        streams.append(V2Stream(descriptor=descriptor, format_info=format_info))

    if source.tell() != table_end:
        raise VMAError("V2 descriptor table size is inconsistent with stream descriptors")
    return tuple(streams)


def _validate_descriptor(descriptor: V2StreamDescriptor, stream_ids: set[int]) -> None:
    if descriptor.stream_id == 0:
        raise VMAError("V2 stream ID must be non-zero")
    if descriptor.stream_id in stream_ids:
        raise VMAError("V2 stream IDs must be unique")
    stream_ids.add(descriptor.stream_id)
    if descriptor.stream_flags != 0 or descriptor.reserved != 0:
        raise VMAError("V2 stream flags and reserved fields must be zero")


def _validate_payload_regions(header: V2Header, streams: tuple[V2Stream, ...], file_size: int) -> None:
    protected = [
        (0, HEADER_SIZE_V2, "V2 fixed header"),
        (header.metadata_offset, header.metadata_offset + header.metadata_size, "V2 metadata"),
        (
            header.descriptor_table_offset,
            header.descriptor_table_offset + header.descriptor_table_size,
            "V2 descriptor table",
        ),
    ]
    payloads: list[tuple[int, int, str]] = []
    for stream in streams:
        descriptor = stream.descriptor
        _validate_range(descriptor.payload_offset, descriptor.payload_size, file_size, "V2 stream payload")
        payload = (descriptor.payload_offset, descriptor.payload_offset + descriptor.payload_size, "V2 stream payload")
        if any(_ranges_overlap(payload, region) for region in protected):
            raise VMAError("V2 stream payload overlaps a container region")
        payloads.append(payload)

    ordered = sorted(payloads)
    for left, right in zip(ordered, ordered[1:], strict=False):
        if _ranges_overlap(left, right):
            raise VMAError("V2 stream payload regions overlap")


def _validate_range(offset: int, size: int, file_size: int, name: str) -> None:
    # Integers originate from unsigned fixed-width wire fields; retaining this
    # check keeps range validation explicit without imposing a new size limit.
    if offset > file_size or size > file_size - offset:
        raise VMAError(f"{name} range is outside the file")


def _ranges_overlap(left: tuple[int, int, str], right: tuple[int, int, str]) -> bool:
    left_start, left_end, _ = left
    right_start, right_end, _ = right
    return left_start < right_end and right_start < left_end


def _read_exact(source: BinaryIO, size: int, name: str) -> bytes:
    value = source.read(size)
    if len(value) != size:
        raise VMAError(f"unexpected end of file while reading {name}")
    return value
