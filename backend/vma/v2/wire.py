"""Exact fixed-structure VMA v2 serialization helpers.

This module intentionally performs no semantic validation.  It only converts
the specification's fixed little-endian structures to and from model objects.
"""

from __future__ import annotations

import struct

from .constants import DESCRIPTOR_FIXED_SIZE_V2, DESCRIPTOR_STRUCT_V2, HEADER_SIZE_V2, HEADER_STRUCT_V2
from .models import V2Header, V2StreamDescriptor


class V2WireError(ValueError):
    """Raised when a fixed V2 structure cannot be read from the supplied bytes."""


def _unpack_exactly(structure: struct.Struct, data: bytes | bytearray | memoryview, offset: int, label: str) -> tuple:
    if offset < 0 or len(data) - offset < structure.size:
        raise V2WireError(f"truncated V2 {label}")
    return structure.unpack_from(data, offset)


def pack_header(header: V2Header) -> bytes:
    """Serialize one V2 fixed header using its specified little-endian layout."""
    return HEADER_STRUCT_V2.pack(
        header.magic,
        header.version,
        header.header_size,
        header.stream_count,
        header.header_flags,
        header.metadata_offset,
        header.metadata_size,
        header.descriptor_table_offset,
        header.descriptor_table_size,
        header.reserved_1,
        header.reserved_2,
    )


def unpack_header(data: bytes | bytearray | memoryview, offset: int = 0) -> V2Header:
    """Read a V2 fixed header at *offset* without applying V2 validity rules."""
    fields = _unpack_exactly(HEADER_STRUCT_V2, data, offset, "header")
    return V2Header(*fields)


def pack_descriptor(descriptor: V2StreamDescriptor) -> bytes:
    """Serialize the fixed 48-byte portion of a V2 stream descriptor."""
    return DESCRIPTOR_STRUCT_V2.pack(
        descriptor.stream_id,
        descriptor.role,
        descriptor.stream_flags,
        descriptor.format_id,
        descriptor.reserved,
        descriptor.start_time,
        descriptor.duration,
        descriptor.payload_offset,
        descriptor.payload_size,
        descriptor.format_info_size,
    )


def unpack_descriptor(data: bytes | bytearray | memoryview, offset: int = 0) -> V2StreamDescriptor:
    """Read a fixed V2 descriptor at *offset*, excluding FORMAT_INFO bytes."""
    fields = _unpack_exactly(DESCRIPTOR_STRUCT_V2, data, offset, "descriptor")
    return V2StreamDescriptor(*fields)


assert HEADER_STRUCT_V2.size == HEADER_SIZE_V2
assert DESCRIPTOR_STRUCT_V2.size == DESCRIPTOR_FIXED_SIZE_V2
