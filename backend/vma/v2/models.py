"""Data models that directly represent VMA v2 binary fields."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class V2Header:
    """The 56-byte VMA v2 fixed header, without reinterpretation."""

    magic: bytes
    version: int
    header_size: int
    stream_count: int
    header_flags: int
    metadata_offset: int
    metadata_size: int
    descriptor_table_offset: int
    descriptor_table_size: int
    reserved_1: int
    reserved_2: int


@dataclass(frozen=True)
class V2StreamDescriptor:
    """The 48-byte fixed part of a VMA v2 stream descriptor."""

    stream_id: int
    role: int
    stream_flags: int
    format_id: int
    reserved: int
    start_time: int
    duration: int
    payload_offset: int
    payload_size: int
    format_info_size: int


@dataclass(frozen=True)
class V2Stream:
    """A V2 descriptor and its still-opaque FORMAT_INFO byte block."""

    descriptor: V2StreamDescriptor
    format_info: bytes


@dataclass(frozen=True)
class V2File:
    """A parsed V2 container representation for later reader stages."""

    path: Path
    header: V2Header
    metadata: dict[str, Any] | None
    streams: tuple[V2Stream, ...]
