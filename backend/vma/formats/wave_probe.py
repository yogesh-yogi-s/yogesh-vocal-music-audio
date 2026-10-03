"""Raw, bytes-only metadata probing for RIFF/WAVE containers."""

from __future__ import annotations

from dataclasses import dataclass

from .models import FormatLookup
from .registry import FORMAT_REGISTRY
from .riff_wave import RIFF_WAVE_CANONICAL_NAME, is_riff_wave


@dataclass(frozen=True)
class WaveProbeResult:
    """Raw facts from a RIFF/WAVE header and one usable ``fmt `` chunk.

    The values are intentionally not interpreted as a decoding or PCM
    capability claim.  They are values declared by the supplied byte buffer.
    """

    format: FormatLookup
    riff_declared_size: int
    fmt_chunk_size: int | None
    format_tag: int | None
    channels: int | None
    sample_rate: int | None
    byte_rate: int | None
    block_align: int | None
    bits_per_sample: int | None


_CHUNK_HEADER_SIZE = 8
_BASE_FMT_SIZE = 16


def _riff_wave_lookup() -> FormatLookup:
    for entry in FORMAT_REGISTRY.entries:
        if entry.canonical_name == RIFF_WAVE_CANONICAL_NAME:
            return FORMAT_REGISTRY.lookup(entry.format_id)
    raise RuntimeError("RIFF_WAVE is not registered")


def probe_riff_wave(data: bytes) -> WaveProbeResult | None:
    """Return raw RIFF/WAVE and base ``fmt `` facts, or ``None`` if unavailable.

    This probe accepts only an in-memory ``bytes`` buffer.  It requires a
    complete base 16-byte ``fmt `` payload, but deliberately does not validate
    PCM rules, data chunks, or the RIFF declared file size.
    """
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    if not is_riff_wave(data):
        return None

    riff_declared_size = int.from_bytes(data[4:8], "little")
    offset = 12

    while offset < len(data):
        if len(data) - offset < _CHUNK_HEADER_SIZE:
            return None

        chunk_id = data[offset : offset + 4]
        chunk_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        payload_offset = offset + _CHUNK_HEADER_SIZE
        payload_end = payload_offset + chunk_size
        if payload_end > len(data):
            return None

        next_offset = payload_end + (chunk_size & 1)
        if next_offset > len(data):
            return None

        if chunk_id == b"fmt " and chunk_size >= _BASE_FMT_SIZE:
            base_fmt = data[payload_offset : payload_offset + _BASE_FMT_SIZE]
            return WaveProbeResult(
                format=_riff_wave_lookup(),
                riff_declared_size=riff_declared_size,
                fmt_chunk_size=chunk_size,
                format_tag=int.from_bytes(base_fmt[0:2], "little"),
                channels=int.from_bytes(base_fmt[2:4], "little"),
                sample_rate=int.from_bytes(base_fmt[4:8], "little"),
                byte_rate=int.from_bytes(base_fmt[8:12], "little"),
                block_align=int.from_bytes(base_fmt[12:14], "little"),
                bits_per_sample=int.from_bytes(base_fmt[14:16], "little"),
            )

        offset = next_offset

    return None
