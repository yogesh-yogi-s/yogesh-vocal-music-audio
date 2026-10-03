"""FORMAT_INFO TLV parsing and serialization for VMA v2.

The caller supplies the exact FORMAT_INFO block.  This module neither reads a
descriptor nor interprets unknown TLVs for decoding or playback.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Iterable


TLV_HEADER_STRUCT = struct.Struct("<BH")
CRITICAL_BIT = 0x80
BASE_TYPE_MASK = 0x7F

SOURCE_FILENAME = 0x01
MEDIA_TYPE = 0x02
FILE_EXTENSION = 0x03
DEFINED_BASE_TYPES = frozenset({SOURCE_FILENAME, MEDIA_TYPE, FILE_EXTENSION})


class FormatInfoError(ValueError):
    """Raised when a FORMAT_INFO block violates the VMA v2 TLV rules."""


@dataclass(frozen=True)
class FormatInfoTLV:
    """One raw FORMAT_INFO TLV, including unknown and critical values."""

    type: int
    value: bytes

    @property
    def is_critical(self) -> bool:
        return bool(self.type & CRITICAL_BIT)

    @property
    def base_type(self) -> int:
        return self.type & BASE_TYPE_MASK

    @property
    def is_known(self) -> bool:
        return self.base_type in DEFINED_BASE_TYPES


@dataclass(frozen=True)
class ParsedFormatInfo:
    """A FORMAT_INFO block and whether an unknown critical TLV was present."""

    tlvs: tuple[FormatInfoTLV, ...]

    @property
    def has_unknown_critical_tlv(self) -> bool:
        return any(tlv.is_critical and not tlv.is_known for tlv in self.tlvs)


def _validate_defined_value(tlv: FormatInfoTLV) -> None:
    """Apply only the text rules defined for V2's three known base types."""
    base_type = tlv.base_type
    if base_type == SOURCE_FILENAME:
        if not tlv.value:
            raise FormatInfoError("SOURCE_FILENAME must be non-empty")
        try:
            tlv.value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FormatInfoError("SOURCE_FILENAME must be valid UTF-8") from exc
        if b"/" in tlv.value or b"\\" in tlv.value:
            raise FormatInfoError("SOURCE_FILENAME must be a basename without path separators")
    elif base_type in {MEDIA_TYPE, FILE_EXTENSION}:
        if not tlv.value:
            name = "MEDIA_TYPE" if base_type == MEDIA_TYPE else "FILE_EXTENSION"
            raise FormatInfoError(f"{name} must be non-empty")
        try:
            tlv.value.decode("ascii")
        except UnicodeDecodeError as exc:
            name = "MEDIA_TYPE" if base_type == MEDIA_TYPE else "FILE_EXTENSION"
            raise FormatInfoError(f"{name} must be valid ASCII") from exc
        if base_type == FILE_EXTENSION and tlv.value.startswith(b"."):
            raise FormatInfoError("FILE_EXTENSION must not begin with a dot")


def _ensure_exact_boundary(data: bytes | bytearray | memoryview, format_info_size: int | None) -> memoryview:
    block = memoryview(data)
    if format_info_size is None:
        return block
    if format_info_size < 0 or format_info_size != len(block):
        raise FormatInfoError("FORMAT_INFO boundary does not match supplied bytes")
    return block


def parse_format_info(
    data: bytes | bytearray | memoryview,
    *,
    format_info_size: int | None = None,
) -> ParsedFormatInfo:
    """Parse exactly one bounded V2 FORMAT_INFO block.

    Unknown TLVs are retained.  Unknown critical TLVs are reported through the
    returned object and are not treated as a structural parsing failure.
    """
    block = _ensure_exact_boundary(data, format_info_size)
    position = 0
    tlvs: list[FormatInfoTLV] = []
    while position < len(block):
        remaining = len(block) - position
        if remaining < TLV_HEADER_STRUCT.size:
            raise FormatInfoError("truncated FORMAT_INFO TLV header")
        tlv_type, length = TLV_HEADER_STRUCT.unpack_from(block, position)
        position += TLV_HEADER_STRUCT.size
        if length > len(block) - position:
            raise FormatInfoError("truncated FORMAT_INFO TLV value")
        value = bytes(block[position : position + length])
        position += length
        tlv = FormatInfoTLV(tlv_type, value)
        if tlv.is_known:
            _validate_defined_value(tlv)
        tlvs.append(tlv)
    return ParsedFormatInfo(tuple(tlvs))


def serialize_format_info(tlvs: Iterable[FormatInfoTLV]) -> bytes:
    """Serialize known V2 TLVs in caller-provided order.

    The specification defines no canonical ordering, so serialization preserves
    the supplied sequence.  Writers may only emit TLVs whose base type is
    defined by V2; critical known base types remain permitted by section 8.
    """
    encoded = bytearray()
    for tlv in tlvs:
        if not 0 <= tlv.type <= 0xFF:
            raise FormatInfoError("TLV type is outside the u8 range")
        if tlv.base_type not in DEFINED_BASE_TYPES:
            raise FormatInfoError("writers may only emit defined V2 TLV types")
        if len(tlv.value) > 0xFFFF:
            raise FormatInfoError("TLV value exceeds the u16 length field")
        _validate_defined_value(tlv)
        encoded.extend(TLV_HEADER_STRUCT.pack(tlv.type, len(tlv.value)))
        encoded.extend(tlv.value)
    return bytes(encoded)
