import sys
import wave
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
FIXTURE_PACK = ROOT / "tests" / "VMA_test_audio_pack"


@dataclass(frozen=True)
class FixtureCase:
    name: str
    vocal_path: Path
    music_path: Path
    expected: dict


def discover_audio_fixture_cases() -> list[FixtureCase]:
    """Discover every fixture pair; new fixture directories require no test edits."""
    manifest = {entry["case"]: entry for entry in json.loads((FIXTURE_PACK / "manifest.json").read_text("utf-8"))}
    cases = []
    for directory in sorted(path for path in FIXTURE_PACK.iterdir() if path.is_dir()):
        vocal_path = directory / "synthetic_vocal.wav"
        music_path = directory / "synthetic_music.wav"
        if vocal_path.is_file() and music_path.is_file():
            cases.append(FixtureCase(directory.name, vocal_path, music_path, manifest[directory.name]))
    return cases


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
