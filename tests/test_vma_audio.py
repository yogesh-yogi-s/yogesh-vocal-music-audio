import struct

import pytest

from vma.audio import parse_pcm_wav
from vma.models import VMAError


def _chunk(chunk_id: bytes, payload: bytes) -> bytes:
    padding = b"\0" if len(payload) % 2 else b""
    return chunk_id + struct.pack("<I", len(payload)) + payload + padding


def _wav_bytes(
    *,
    format_code: int = 1,
    channels: int = 1,
    sample_rate: int = 44_100,
    bit_depth: int = 16,
    byte_rate: int | None = None,
    block_align: int | None = None,
    fmt_payload: bytes | None = None,
    chunks: tuple[bytes, ...] | None = None,
    data: bytes = b"\0\0",
) -> bytes:
    expected_align = channels * (bit_depth // 8)
    fmt = fmt_payload or struct.pack(
        "<HHIIHH",
        format_code,
        channels,
        sample_rate,
        byte_rate if byte_rate is not None else sample_rate * expected_align,
        block_align if block_align is not None else expected_align,
        bit_depth,
    )
    body = b"".join(chunks) if chunks is not None else _chunk(b"fmt ", fmt) + _chunk(b"data", data)
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: b"BAD!" + raw[4:],
        lambda raw: raw[:4] + struct.pack("<I", len(raw)) + raw[8:],
        lambda raw: raw[:12] + _chunk(b"fmt ", b"\0" * 8) + _chunk(b"data", b"\0\0"),
        lambda raw: _wav_bytes(chunks=(_chunk(b"data", b"\0\0"),)),
        lambda raw: _wav_bytes(chunks=(_chunk(b"fmt ", raw[20:36]),)),
        lambda raw: _wav_bytes(chunks=(_chunk(b"fmt ", raw[20:36]), _chunk(b"data", b"\0"))),
        lambda raw: _wav_bytes(chunks=(_chunk(b"fmt ", raw[20:36]), _chunk(b"data", b"\0\0"), _chunk(b"data", b"\0\0"))),
    ],
    ids=["bad-magic", "riff-boundary", "short-fmt", "missing-fmt", "missing-data", "unaligned-data", "duplicate-data"],
)
def test_parser_rejects_malformed_riff_mutations(tmp_path, mutation):
    source = tmp_path / "mutated.wav"
    valid = _wav_bytes()
    source.write_bytes(mutation(valid))

    with pytest.raises(VMAError):
        parse_pcm_wav(source)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"format_code": 3},
        {"channels": 3},
        {"bit_depth": 20},
        {"byte_rate": 1},
        {"block_align": 1},
        {"sample_rate": 0},
        {"sample_rate": 384_001},
    ],
    ids=["compressed-format", "unsupported-channels", "unsupported-bit-depth", "bad-byte-rate", "bad-block-align", "zero-rate", "rate-too-high"],
)
def test_parser_rejects_invalid_pcm_format_fields(tmp_path, kwargs):
    source = tmp_path / "invalid-format.wav"
    source.write_bytes(_wav_bytes(**kwargs))

    with pytest.raises(VMAError):
        parse_pcm_wav(source)


def test_parser_rejects_non_pcm_extensible_format(tmp_path):
    source = tmp_path / "non-pcm-extensible.wav"
    fmt = struct.pack("<HHIIHHH", 0xFFFE, 1, 44_100, 88_200, 2, 16, 22)
    fmt += struct.pack("<HI", 16, 3) + b"\0" * 16
    source.write_bytes(_wav_bytes(fmt_payload=fmt))

    with pytest.raises(VMAError, match="only PCM WAV"):
        parse_pcm_wav(source)
