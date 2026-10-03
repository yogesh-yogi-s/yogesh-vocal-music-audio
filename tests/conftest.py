import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def write_pcm_wav(path: Path, *, channels: int, sample_rate: int, bit_depth: int, frames: int) -> bytes:
    bytes_per_frame = channels * (bit_depth // 8)
    data = bytes((index * 17 + 3) % 256 for index in range(frames * bytes_per_frame))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(bit_depth // 8)
        output.setframerate(sample_rate)
        output.writeframes(data)
    return data


@pytest.fixture
def wav_pair(tmp_path):
    vocal = tmp_path / "vocal.wav"
    music = tmp_path / "music.wav"
    vocal_data = write_pcm_wav(vocal, channels=1, sample_rate=44_100, bit_depth=16, frames=1000)
    music_data = write_pcm_wav(music, channels=2, sample_rate=48_000, bit_depth=24, frames=1500)
    return vocal, music, vocal_data, music_data
