"""Focused tests for raw RIFF/WAVE metadata probing."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import inspect
import struct

import pytest

from backend.vma.formats import WaveProbeResult, probe_riff_wave
import backend.vma.formats.wave_probe as wave_probe


def _chunk(chunk_id: bytes, payload: bytes, *, declared_size: int | None = None) -> bytes:
    size = len(payload) if declared_size is None else declared_size
    padding = b"\x00" if len(payload) == size and size & 1 else b""
    return chunk_id + struct.pack("<I", size) + payload + padding


def _base_fmt(
    format_tag: int = 1,
    channels: int = 2,
    sample_rate: int = 48_000,
    byte_rate: int = 192_000,
    block_align: int = 4,
    bits_per_sample: int = 16,
) -> bytes:
    return struct.pack(
        "<HHIIHH",
        format_tag,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
    )


def _riff(*chunks: bytes, declared_size: int | None = None, form_type: bytes = b"WAVE") -> bytes:
    payload = form_type + b"".join(chunks)
    size = len(payload) if declared_size is None else declared_size
    return b"RIFF" + struct.pack("<I", size) + payload


def test_probe_valid_minimal_wave_extracts_exact_raw_fmt_fields() -> None:
    result = probe_riff_wave(_riff(_chunk(b"fmt ", _base_fmt())))

    assert result == WaveProbeResult(
        format=result.format,
        riff_declared_size=28,
        fmt_chunk_size=16,
        format_tag=1,
        channels=2,
        sample_rate=48_000,
        byte_rate=192_000,
        block_align=4,
        bits_per_sample=16,
    )
    assert result.format.format_id == 0x1000
    assert result.format.entry is not None
    assert result.format.entry.canonical_name == "RIFF_WAVE"


def test_probe_preserves_non_pcm_raw_values_without_validation() -> None:
    result = probe_riff_wave(_riff(_chunk(b"fmt ", _base_fmt(0x0055, 9, 0, 1, 3, 7))))

    assert result is not None
    assert (result.format_tag, result.channels, result.sample_rate) == (0x0055, 9, 0)
    assert (result.byte_rate, result.block_align, result.bits_per_sample) == (1, 3, 7)


def test_probe_preserves_raw_riff_declared_size_without_file_size_validation() -> None:
    result = probe_riff_wave(_riff(_chunk(b"fmt ", _base_fmt()), declared_size=0xFFFFFFFF))

    assert result is not None
    assert result.riff_declared_size == 0xFFFFFFFF


@pytest.mark.parametrize(
    "data",
    [
        _riff(_chunk(b"fmt ", _base_fmt()), form_type=b"AVI "),
        b"RF64" + struct.pack("<I", 0) + b"WAVE" + _chunk(b"fmt ", _base_fmt()),
        b"RIFX" + struct.pack(">I", 0) + b"WAVE" + _chunk(b"fmt ", _base_fmt()),
        b"RIFF\x00\x00",
        b"not a wave file",
    ],
)
def test_probe_rejects_non_riff_wave_or_truncated_container_signature(data: bytes) -> None:
    assert probe_riff_wave(data) is None


@pytest.mark.parametrize(
    "data",
    [
        _riff(b"fmt "),
        _riff(b"fmt " + struct.pack("<I", 16) + _base_fmt()[:-1]),
        _riff(_chunk(b"fmt ", _base_fmt()[:-1])),
    ],
)
def test_probe_rejects_incomplete_chunk_or_unusable_fmt_payload(data: bytes) -> None:
    assert probe_riff_wave(data) is None


def test_probe_locates_fmt_after_unknown_odd_sized_chunk_and_padding() -> None:
    result = probe_riff_wave(_riff(_chunk(b"JUNK", b"abc"), _chunk(b"fmt ", _base_fmt())))

    assert result is not None
    assert result.format_tag == 1
    assert result.fmt_chunk_size == 16


def test_probe_does_not_validate_data_chunk_semantics() -> None:
    malformed_data_chunk = b"data" + struct.pack("<I", 10_000)
    result = probe_riff_wave(_riff(_chunk(b"fmt ", _base_fmt()) + malformed_data_chunk))

    assert result is not None
    assert result.format.format_id == 0x1000


def test_probe_result_is_immutable() -> None:
    result = probe_riff_wave(_riff(_chunk(b"fmt ", _base_fmt())))

    assert result is not None
    with pytest.raises(FrozenInstanceError):
        result.channels = 1  # type: ignore[misc]


def test_probe_accepts_bytes_only() -> None:
    with pytest.raises(TypeError, match="data must be bytes"):
        probe_riff_wave(bytearray(_riff(_chunk(b"fmt ", _base_fmt()))))  # type: ignore[arg-type]


def test_probe_has_no_v1_parser_dependency() -> None:
    source = inspect.getsource(wave_probe)

    assert "parse_pcm_wav" not in source
    assert "ParsedWav" not in source
    assert "AudioFormat" not in source
    assert "vma.audio" not in source
