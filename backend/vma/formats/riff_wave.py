"""Conservative RIFF/WAVE container signature recognition only."""

from __future__ import annotations


RIFF_WAVE_CANONICAL_NAME = "RIFF_WAVE"
_RIFF = b"RIFF"
_WAVE = b"WAVE"
_MINIMUM_HEADER_SIZE = 12


def is_riff_wave(data: bytes | bytearray | memoryview) -> bool:
    """Return whether bytes establish a RIFF container with WAVE form type.

    This intentionally does not validate the RIFF size, parse chunks, inspect
    ``fmt `` data, or make any PCM/decoder capability determination.
    """
    view = memoryview(data)
    return len(view) >= _MINIMUM_HEADER_SIZE and view[:4].tobytes() == _RIFF and view[8:12].tobytes() == _WAVE
