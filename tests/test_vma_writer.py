import json

import pytest

from conftest import discover_audio_fixture_cases
from vma import create_vma, read_vma
from vma.format import HEADER_SIZE, HEADER_STRUCT, MAGIC, MAX_METADATA_SIZE, STREAM_ENTRY_SIZE, STREAM_STRUCT, VERSION
from vma.models import Codec, StreamType, VMAError
from vma_test_support import assert_stream_matches_wav


CASES = discover_audio_fixture_cases()


def _title_for_metadata_size(vocal_path, music_path, size):
    fixed = {
        "title": "",
        "artist": "",
        "vocal_filename": vocal_path.name,
        "music_filename": music_path.name,
        "created_utc": "0" * 32,
    }
    base_size = len(json.dumps(fixed, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return "x" * (size - base_size)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_vma_writer_encodes_documented_header_and_stream_table(tmp_path, case):
    output = create_vma(case.vocal_path, case.music_path, tmp_path / f"{case.name}.vma", {"title": case.name, "artist": "VMA tests"})
    raw = output.read_bytes()
    assert output.is_file() and output.stat().st_size > 0
    magic, version, reserved, header_size, stream_count, metadata_size, entry_size, flags = HEADER_STRUCT.unpack_from(raw)
    assert raw[:4] == MAGIC == b"VMAF"
    assert raw[4:6] == b"\x01\x00"  # Version is little-endian uint16.
    assert magic == MAGIC and version == VERSION and reserved == 0 and flags == 0
    assert stream_count == 2 and entry_size == STREAM_ENTRY_SIZE
    assert header_size == HEADER_SIZE + metadata_size + stream_count * STREAM_ENTRY_SIZE
    assert header_size < len(raw)
    metadata = json.loads(raw[HEADER_SIZE:HEADER_SIZE + metadata_size].decode("utf-8"))
    assert metadata["title"] == case.name
    entries = [STREAM_STRUCT.unpack_from(raw, HEADER_SIZE + metadata_size + index * STREAM_ENTRY_SIZE) for index in range(2)]
    expected = [(1, StreamType.VOCAL, case.vocal_path), (2, StreamType.MUSIC, case.music_path)]
    previous_end = header_size
    for entry, (stream_id, stream_type, source) in zip(entries, expected, strict=True):
        actual_id, actual_type, codec, rate, channels, bits, start, sample_count, offset, size, entry_reserved = entry
        assert (actual_id, actual_type, codec, start, entry_reserved) == (stream_id, stream_type, Codec.PCM_WAV_LE, 0, b"\0" * 16)
        assert offset == previous_end
        assert offset + size <= len(raw)
        stream = read_vma(output).stream_for(stream_type)
        assert_stream_matches_wav(stream, source)
        assert (rate, channels, bits, sample_count, size) == (
            stream.audio.sample_rate, stream.audio.channels, stream.audio.bit_depth, stream.audio.sample_count, stream.data_size,
        )
        previous_end = offset + size
    assert previous_end == len(raw)


def test_vma_writer_accepts_metadata_at_documented_limit(tmp_path, wav_pair):
    vocal, music, _, _ = wav_pair
    title = _title_for_metadata_size(vocal, music, MAX_METADATA_SIZE)
    output = create_vma(vocal, music, tmp_path / "metadata-limit.vma", {"title": title})

    raw = output.read_bytes()
    assert HEADER_STRUCT.unpack_from(raw)[5] == MAX_METADATA_SIZE
    assert read_vma(output).metadata["title"] == title


def test_vma_writer_rejects_metadata_above_documented_limit(tmp_path, wav_pair):
    vocal, music, _, _ = wav_pair
    title = _title_for_metadata_size(vocal, music, MAX_METADATA_SIZE + 1)
    output = tmp_path / "metadata-too-large.vma"

    with pytest.raises(VMAError, match="metadata"):
        create_vma(vocal, music, output, {"title": title})
    assert not output.exists()
