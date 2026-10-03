import pytest

from vma.formats import FormatIdRange, identify_format
from vma.formats.riff_wave import is_riff_wave


def test_identify_riff_wave_from_container_signature_only():
    result = identify_format(b"RIFF\x00\x00\x00\x00WAVE")
    assert result.known
    assert result.format_id == 0x1000
    assert result.range is FormatIdRange.VMA_DEFINED
    assert result.entry is not None
    assert result.entry.canonical_name == "RIFF_WAVE"


@pytest.mark.parametrize(
    "data",
    [
        b"RIFF\x00\x00\x00\x00AVI ",
        b"RIFF\x00\x00\x00\x00WAV",
        b"RIFX\x00\x00\x00\x00WAVE",
        b"RIFF\x00\x00\x00\x00WAVX",
        b"not an audio file",
        b"",
        b"RIFF\x00\x00",
    ],
)
def test_identify_returns_unknown_when_riff_wave_identity_is_not_established(data):
    result = identify_format(data)
    assert result.format_id == 0x0000
    assert result.range is FormatIdRange.UNKNOWN
    assert not result.known


def test_identify_does_not_require_fmt_or_pcm_information():
    data = bytearray(b"RIFF\xff\xff\xff\xffWAVE")
    assert is_riff_wave(data)
    assert identify_format(memoryview(data)).format_id == 0x1000


def test_identify_is_deterministic_for_repeated_calls():
    data = b"RIFF\x04\x00\x00\x00WAVEanything"
    assert [identify_format(data) for _ in range(3)] == [identify_format(data)] * 3
