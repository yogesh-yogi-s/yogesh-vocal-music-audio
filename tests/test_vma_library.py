import struct
from pathlib import Path

import pytest

from vma import create_vma, extract_all, extract_music, extract_vocal, read_vma, validate_vma
from vma.format import HEADER_SIZE, HEADER_STRUCT, STREAM_ENTRY_SIZE, STREAM_STRUCT
from vma.audio import PCM_SUBFORMAT_GUID
from vma.models import VMAError

from conftest import write_pcm_wav


def test_create_read_and_extract_losslessly(tmp_path, wav_pair):
    vocal, music, vocal_data, music_data = wav_pair
    container_path = create_vma(vocal, music, tmp_path / "song.vma", {"title": "Test", "artist": "RMV"})
    container = read_vma(container_path)
    assert container.metadata["title"] == "Test"
    assert {stream.stream_type.name for stream in container.streams} == {"VOCAL", "MUSIC"}
    assert container.duration_seconds == pytest.approx(1500 / 48_000)
    vocal_output = extract_vocal(container_path, tmp_path / "out-vocal.wav")
    music_output = extract_music(container_path, tmp_path / "out-music.wav")
    assert vocal_output.read_bytes()[44:] == vocal_data
    assert music_output.read_bytes()[44:] == music_data


@pytest.mark.parametrize("bit_depth", [8, 16, 24, 32])
@pytest.mark.parametrize("channels", [1, 2])
def test_pcm_bit_depths_and_channels(tmp_path, bit_depth, channels):
    vocal, music = tmp_path / "v.wav", tmp_path / "m.wav"
    vocal_data = write_pcm_wav(vocal, channels=channels, sample_rate=22_050, bit_depth=bit_depth, frames=20)
    write_pcm_wav(music, channels=1, sample_rate=44_100, bit_depth=16, frames=40)
    vma = create_vma(vocal, music, tmp_path / "format.vma")
    output = extract_vocal(vma, tmp_path / "result.wav")
    assert output.read_bytes()[44:] == vocal_data


def test_extract_all_and_validation(tmp_path, wav_pair):
    vocal, music, _, _ = wav_pair
    vma = create_vma(vocal, music, tmp_path / "song.vma")
    validated = validate_vma(vma)
    outputs = extract_all(vma, tmp_path / "tracks")
    assert validated.path == vma
    assert [path.name for path in outputs] == ["vocal.wav", "music.wav"]


def test_pcm_wave_format_extensible_is_accepted(tmp_path):
    vocal, music = tmp_path / "vocal-extensible.wav", tmp_path / "music.wav"
    data = b"\0\1\2\3" * 20
    fmt = struct.pack("<HHIIHHH", 0xFFFE, 2, 48_000, 192_000, 4, 16, 22) + struct.pack("<HI", 16, 3) + PCM_SUBFORMAT_GUID
    vocal.write_bytes(b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(data)) + b"WAVEfmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data)
    write_pcm_wav(music, channels=1, sample_rate=48_000, bit_depth=16, frames=30)
    container = create_vma(vocal, music, tmp_path / "song.vma")
    assert extract_vocal(container, tmp_path / "output.wav").read_bytes()[44:] == data


def test_nonzero_start_sample_is_read(tmp_path, wav_pair):
    vocal, music, _, _ = wav_pair
    vma = create_vma(vocal, music, tmp_path / "song.vma")
    raw = bytearray(vma.read_bytes())
    fields = list(STREAM_STRUCT.unpack_from(raw, HEADER_SIZE + HEADER_STRUCT.unpack_from(raw)[5]))
    fields[6] = 2205
    STREAM_STRUCT.pack_into(raw, HEADER_SIZE + HEADER_STRUCT.unpack_from(raw)[5], *fields)
    vma.write_bytes(raw)
    assert read_vma(vma).stream_for(1).start_sample == 2205


@pytest.mark.parametrize("mutator", ["magic", "offset", "overlap", "truncated"])
def test_corrupt_files_are_rejected(tmp_path, wav_pair, mutator):
    vocal, music, _, _ = wav_pair
    vma = create_vma(vocal, music, tmp_path / "song.vma")
    raw = bytearray(vma.read_bytes())
    metadata_size = HEADER_STRUCT.unpack_from(raw)[5]
    stream0 = HEADER_SIZE + metadata_size
    stream1 = stream0 + STREAM_ENTRY_SIZE
    if mutator == "magic":
        raw[:4] = b"BAD!"
    elif mutator == "offset":
        fields = list(STREAM_STRUCT.unpack_from(raw, stream0))
        fields[8] = len(raw) + 1
        STREAM_STRUCT.pack_into(raw, stream0, *fields)
    elif mutator == "overlap":
        first = STREAM_STRUCT.unpack_from(raw, stream0)
        fields = list(STREAM_STRUCT.unpack_from(raw, stream1))
        fields[8] = first[8]
        STREAM_STRUCT.pack_into(raw, stream1, *fields)
    else:
        raw = raw[:-10]
    vma.write_bytes(raw)
    with pytest.raises(VMAError):
        validate_vma(vma)
