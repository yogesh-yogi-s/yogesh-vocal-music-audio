"""Deterministic, recognition-only format identification."""

from __future__ import annotations

from .models import FormatLookup
from .registry import FORMAT_REGISTRY
from .riff_wave import RIFF_WAVE_CANONICAL_NAME, is_riff_wave


def identify_format(data: bytes | bytearray | memoryview) -> FormatLookup:
    """Identify only established container signatures, otherwise return UNKNOWN."""
    if is_riff_wave(data):
        for entry in FORMAT_REGISTRY.entries:
            if entry.canonical_name == RIFF_WAVE_CANONICAL_NAME:
                return FORMAT_REGISTRY.lookup(entry.format_id)
    return FORMAT_REGISTRY.lookup(0x0000)
