import struct

import pytest

from conftest import discover_audio_fixture_cases
from vma import create_vma, read_vma, validate_vma
from vma.format import HEADER_SIZE, HEADER_STRUCT, STREAM_ENTRY_SIZE, STREAM_STRUCT
from vma.models import Codec, StreamType, VMAError
from vma_test_support import assert_stream_matches_wav


CASES = discover_audio_fixture_cases()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_reader_preserves_every_fixture_stream_metadata(tmp_path, case):
    container_path = create_vma(case.vocal_path, case.music_path, tmp_path / f"{case.name}.vma")
    container = read_vma(container_path)
    assert len(container.streams) == 2
    expected_streams = ((1, StreamType.VOCAL, case.vocal_path, case.expected["vocal"]), (2, StreamType.MUSIC, case.music_path, case.expected["music"]))
    for stream, (stream_id, stream_type, source, expected) in zip(container.streams, expected_streams, strict=True):
        assert stream.stream_id == stream_id
        assert stream.stream_type is stream_type
        assert stream.codec is Codec.PCM_WAV_LE
        assert stream.start_sample == 0
        assert_stream_matches_wav(stream, source)
        assert stream.audio.sample_rate == expected["sample_rate"]
        assert stream.audio.channels == expected["channels"]
        assert stream.audio.duration_seconds == pytest.approx(expected["duration_seconds"])
        assert stream.data_offset >= HEADER_SIZE
        assert stream.data_size == stream.audio.data_size
    assert validate_vma(container_path) == container


def test_vma_level_start_sample_metadata_is_distinct_from_leading_silence(tmp_path):
    case = next(case for case in CASES if case.name == "08_offset_example")
    container_path = create_vma(case.vocal_path, case.music_path, tmp_path / "offset.vma")
    raw = bytearray(container_path.read_bytes())
    metadata_size = HEADER_STRUCT.unpack_from(raw)[5]
    vocal_position = HEADER_SIZE + metadata_size
    vocal = list(STREAM_STRUCT.unpack_from(raw, vocal_position))
    vocal[6] = 2 * vocal[3]  # Two seconds in the stream's native sample rate.
    STREAM_STRUCT.pack_into(raw, vocal_position, *vocal)
    container_path.write_bytes(raw)
    stream = read_vma(container_path).stream_for(StreamType.VOCAL)
    assert stream.start_sample == 88_200
    assert stream.start_seconds == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("field", "value", "expected_message"),
    [
        (3, 0, "audio format"),
        (4, 3, "audio format"),
        (5, 20, "audio format"),
        (7, 0, "synchronization"),
        (9, 1, "data size"),
    ],
)
def test_reader_delegates_pcm_descriptor_validation(tmp_path, wav_pair, field, value, expected_message):
    vocal, music, _, _ = wav_pair
    path = create_vma(vocal, music, tmp_path / "invalid-pcm-descriptor.vma")
    raw = bytearray(path.read_bytes())
    metadata_size = HEADER_STRUCT.unpack_from(raw)[5]
    entry_offset = HEADER_SIZE + metadata_size
    entry = list(STREAM_STRUCT.unpack_from(raw, entry_offset))
    entry[field] = value
    STREAM_STRUCT.pack_into(raw, entry_offset, *entry)
    path.write_bytes(raw)

    with pytest.raises(VMAError, match=expected_message):
        read_vma(path)


def test_reader_preserves_pcm_format_error_precedence_over_negative_start_sample(tmp_path, wav_pair):
    vocal, music, _, _ = wav_pair
    path = create_vma(vocal, music, tmp_path / "invalid-format-and-start.vma")
    raw = bytearray(path.read_bytes())
    metadata_size = HEADER_STRUCT.unpack_from(raw)[5]
    entry_offset = HEADER_SIZE + metadata_size
    entry = list(STREAM_STRUCT.unpack_from(raw, entry_offset))
    entry[3] = 0
    entry[6] = -1
    STREAM_STRUCT.pack_into(raw, entry_offset, *entry)
    path.write_bytes(raw)

    with pytest.raises(VMAError, match="audio format"):
        read_vma(path)


def _valid_vma(tmp_path):
    case = CASES[0]
    path = create_vma(case.vocal_path, case.music_path, tmp_path / "valid.vma")
    return path, bytearray(path.read_bytes())


@pytest.mark.parametrize(
    ("corruption", "expected_message"),
    [
        ("magic", "magic"),
        ("version", "version"),
        ("truncated_header", "small"),
        ("truncated_metadata", "header size"),
        ("truncated_stream_table", "header size"),
        ("invalid_stream_offset", "range"),
        ("invalid_stream_size", "data size"),
        ("payload_beyond_eof", "range"),
        ("invalid_stream_count", "exactly two"),
        ("malformed_metadata", "metadata"),
    ],
)
def test_reader_rejects_corrupt_containers_cleanly(tmp_path, corruption, expected_message):
    path, raw = _valid_vma(tmp_path)
    metadata_size = HEADER_STRUCT.unpack_from(raw)[5]
    stream_position = HEADER_SIZE + metadata_size
    if corruption == "magic":
        raw[:4] = b"NOPE"
    elif corruption == "version":
        struct.pack_into("<H", raw, 4, 99)
    elif corruption == "truncated_header":
        raw = raw[: HEADER_SIZE - 1]
    elif corruption == "truncated_metadata":
        raw = raw[: HEADER_SIZE + 1]
    elif corruption == "truncated_stream_table":
        raw = raw[: HEADER_SIZE + metadata_size + STREAM_ENTRY_SIZE]
    elif corruption == "invalid_stream_offset":
        entry = list(STREAM_STRUCT.unpack_from(raw, stream_position))
        entry[8] = HEADER_SIZE - 1
        STREAM_STRUCT.pack_into(raw, stream_position, *entry)
    elif corruption == "invalid_stream_size":
        entry = list(STREAM_STRUCT.unpack_from(raw, stream_position))
        entry[9] -= 1
        STREAM_STRUCT.pack_into(raw, stream_position, *entry)
    elif corruption == "payload_beyond_eof":
        # Corrupt the final payload so EOF validation is reached before overlap validation.
        stream_position += STREAM_ENTRY_SIZE
        entry = list(STREAM_STRUCT.unpack_from(raw, stream_position))
        entry[7] += 1
        entry[9] += entry[4] * (entry[5] // 8)
        STREAM_STRUCT.pack_into(raw, stream_position, *entry)
    elif corruption == "invalid_stream_count":
        struct.pack_into("<I", raw, 12, 3)
    elif corruption == "malformed_metadata":
        raw[HEADER_SIZE:HEADER_SIZE + metadata_size] = b"!" * metadata_size
    path.write_bytes(raw)
    with pytest.raises(VMAError, match=expected_message):
        read_vma(path)
