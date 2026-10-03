"""Tests for start_sample authoring introduced in VMA v0.2 Step 2.

Covers:
- default values remain 0 (backward compatibility)
- non-zero vocal_start_sample round-trips correctly
- non-zero music_start_sample round-trips correctly
- start_seconds is calculated correctly from start_sample / sample_rate
- negative start_sample values are rejected with VMAError
"""
import pytest

from vma import create_vma, read_vma
from vma.models import StreamType, VMAError

from conftest import write_pcm_wav


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_RATE = 44_100


@pytest.fixture()
def wav_pair_44k(tmp_path):
    vocal = tmp_path / "vocal.wav"
    music = tmp_path / "music.wav"
    write_pcm_wav(vocal, channels=1, sample_rate=SAMPLE_RATE, bit_depth=16, frames=4410)
    write_pcm_wav(music, channels=1, sample_rate=SAMPLE_RATE, bit_depth=16, frames=4410)
    return vocal, music


# ---------------------------------------------------------------------------
# Default behaviour — backward compatibility
# ---------------------------------------------------------------------------

def test_default_start_samples_are_zero(tmp_path, wav_pair_44k):
    """Omitting the new kwargs must produce start_sample=0 for both streams."""
    vocal, music = wav_pair_44k
    vma = create_vma(vocal, music, tmp_path / "default.vma")
    container = read_vma(vma)
    vocal_stream = container.stream_for(StreamType.VOCAL)
    music_stream = container.stream_for(StreamType.MUSIC)
    assert vocal_stream.start_sample == 0
    assert music_stream.start_sample == 0


def test_explicit_zero_start_samples_are_zero(tmp_path, wav_pair_44k):
    """Explicitly passing 0 must be identical to the default."""
    vocal, music = wav_pair_44k
    vma = create_vma(
        vocal, music, tmp_path / "explicit_zero.vma",
        vocal_start_sample=0,
        music_start_sample=0,
    )
    container = read_vma(vma)
    assert container.stream_for(StreamType.VOCAL).start_sample == 0
    assert container.stream_for(StreamType.MUSIC).start_sample == 0


# ---------------------------------------------------------------------------
# Non-zero vocal_start_sample
# ---------------------------------------------------------------------------

def test_nonzero_vocal_start_sample_round_trips(tmp_path, wav_pair_44k):
    """A non-zero vocal_start_sample must be read back exactly from the container."""
    vocal, music = wav_pair_44k
    offset = 88_200  # 2 seconds at 44 100 Hz
    vma = create_vma(
        vocal, music, tmp_path / "vocal_offset.vma",
        vocal_start_sample=offset,
    )
    container = read_vma(vma)
    vocal_stream = container.stream_for(StreamType.VOCAL)
    music_stream = container.stream_for(StreamType.MUSIC)
    assert vocal_stream.start_sample == offset
    assert music_stream.start_sample == 0  # music unchanged


def test_nonzero_vocal_start_seconds_is_correct(tmp_path, wav_pair_44k):
    """start_seconds must equal start_sample / sample_rate."""
    vocal, music = wav_pair_44k
    offset = 44_100  # exactly 1.0 second
    vma = create_vma(
        vocal, music, tmp_path / "vocal_1s.vma",
        vocal_start_sample=offset,
    )
    stream = read_vma(vma).stream_for(StreamType.VOCAL)
    assert stream.start_seconds == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Non-zero music_start_sample
# ---------------------------------------------------------------------------

def test_nonzero_music_start_sample_round_trips(tmp_path, wav_pair_44k):
    """A non-zero music_start_sample must be read back exactly from the container."""
    vocal, music = wav_pair_44k
    offset = 22_050  # 0.5 seconds at 44 100 Hz
    vma = create_vma(
        vocal, music, tmp_path / "music_offset.vma",
        music_start_sample=offset,
    )
    container = read_vma(vma)
    vocal_stream = container.stream_for(StreamType.VOCAL)
    music_stream = container.stream_for(StreamType.MUSIC)
    assert vocal_stream.start_sample == 0  # vocal unchanged
    assert music_stream.start_sample == offset


def test_nonzero_music_start_seconds_is_correct(tmp_path, wav_pair_44k):
    """music start_seconds must equal music_start_sample / music sample_rate."""
    vocal, music = wav_pair_44k
    offset = 44_100  # exactly 1.0 second at 44 100 Hz
    vma = create_vma(
        vocal, music, tmp_path / "music_1s.vma",
        music_start_sample=offset,
    )
    stream = read_vma(vma).stream_for(StreamType.MUSIC)
    assert stream.start_seconds == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Both streams offset simultaneously
# ---------------------------------------------------------------------------

def test_both_start_samples_round_trip_independently(tmp_path, wav_pair_44k):
    """Both offsets can be set independently and must survive the round-trip."""
    vocal, music = wav_pair_44k
    vocal_offset = 11_025   # 0.25 s
    music_offset = 33_075   # 0.75 s
    vma = create_vma(
        vocal, music, tmp_path / "both_offset.vma",
        vocal_start_sample=vocal_offset,
        music_start_sample=music_offset,
    )
    container = read_vma(vma)
    assert container.stream_for(StreamType.VOCAL).start_sample == vocal_offset
    assert container.stream_for(StreamType.MUSIC).start_sample == music_offset


# ---------------------------------------------------------------------------
# Validation — negative values are rejected
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("kwargs", "expected_fragment"),
    [
        ({"vocal_start_sample": -1}, "vocal_start_sample"),
        ({"music_start_sample": -1}, "music_start_sample"),
        ({"vocal_start_sample": -44_100}, "vocal_start_sample"),
        ({"music_start_sample": -1000}, "music_start_sample"),
    ],
)
def test_negative_start_sample_raises_vma_error(tmp_path, wav_pair_44k, kwargs, expected_fragment):
    """Negative start_sample values must raise VMAError before any file is written."""
    vocal, music = wav_pair_44k
    with pytest.raises(VMAError, match=expected_fragment):
        create_vma(vocal, music, tmp_path / "rejected.vma", **kwargs)
    # Confirm no output file was created (validation fires before WAV parsing).
    assert not (tmp_path / "rejected.vma").exists()


# ---------------------------------------------------------------------------
# Binary format unchanged — VERSION and layout
# ---------------------------------------------------------------------------

def test_version_field_is_still_1(tmp_path, wav_pair_44k):
    """Adding start_sample kwargs must not alter the binary VERSION field."""
    from vma.format import HEADER_STRUCT, VERSION
    vocal, music = wav_pair_44k
    vma = create_vma(
        vocal, music, tmp_path / "version_check.vma",
        vocal_start_sample=1000,
        music_start_sample=2000,
    )
    raw = vma.read_bytes()
    _, version, *_ = HEADER_STRUCT.unpack_from(raw)
    assert version == VERSION == 1


def test_stream_entry_size_unchanged(tmp_path, wav_pair_44k):
    """The stream entry byte size must remain 64 bytes."""
    from vma.format import STREAM_ENTRY_SIZE
    assert STREAM_ENTRY_SIZE == 64


def test_reserved_bytes_remain_zero_with_nonzero_start_sample(tmp_path, wav_pair_44k):
    """The 16-byte per-stream reserved field must remain all-zero."""
    from vma.format import HEADER_STRUCT, STREAM_ENTRY_SIZE, STREAM_STRUCT
    vocal, music = wav_pair_44k
    vma = create_vma(
        vocal, music, tmp_path / "reserved_check.vma",
        vocal_start_sample=12_345,
        music_start_sample=67_890,
    )
    raw = vma.read_bytes()
    metadata_size = HEADER_STRUCT.unpack_from(raw)[5]
    from vma.format import HEADER_SIZE
    for i in range(2):
        entry_offset = HEADER_SIZE + metadata_size + i * STREAM_ENTRY_SIZE
        fields = STREAM_STRUCT.unpack_from(raw, entry_offset)
        reserved = fields[-1]  # last field: 16s
        assert reserved == b"\0" * 16, f"stream {i} reserved bytes are non-zero"
