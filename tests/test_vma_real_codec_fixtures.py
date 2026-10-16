"""Opt-in real-codec integration checks for VMA's opaque V2 API path.

Set VMA_REAL_CODEC_FFMPEG to a full local ffmpeg executable.  The tests generate
short synthetic tones in pytest's temporary directory, inspect them with colocated
ffprobe, fully decode them, then verify VMA extraction is byte-exact.  They do not
claim browser codec support and never download or commit media fixtures.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


SINE_SOURCE = "sine=frequency=440:sample_rate=48000:duration=0.75"
FFMPEG_ENV = "VMA_REAL_CODEC_FFMPEG"


@pytest.fixture(scope="module")
def codec_tools() -> tuple[Path, Path]:
    raw_ffmpeg = os.environ.get(FFMPEG_ENV)
    if not raw_ffmpeg:
        pytest.skip(f"set {FFMPEG_ENV} to run real codec integration checks")
    ffmpeg = Path(raw_ffmpeg)
    ffprobe = ffmpeg.with_name("ffprobe.exe")
    if not ffmpeg.is_file() or not ffprobe.is_file():
        pytest.skip("full ffmpeg and colocated ffprobe are required for real codec checks")
    return ffmpeg, ffprobe


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _probe_and_decode(ffmpeg: Path, ffprobe: Path, source: Path, *, codec: str, container: str) -> None:
    probe = _run([
        str(ffprobe), "-v", "error", "-select_streams", "a:0",
        "-show_entries", "format=format_name,duration:stream=codec_name,sample_rate,channels",
        "-of", "json", str(source),
    ])
    metadata = json.loads(probe.stdout)
    stream = metadata["streams"][0]
    assert stream["codec_name"] == codec
    assert stream["sample_rate"] == "48000"
    assert stream["channels"] == 1
    assert container in metadata["format"]["format_name"].split(",")
    assert 0 < float(metadata["format"]["duration"]) < 2
    _run([str(ffmpeg), "-v", "error", "-i", str(source), "-f", "null", "-"])


@pytest.mark.parametrize(
    ("filename", "content_type", "encoder", "encoder_args", "expected_codec", "expected_container"),
    [
        ("tone.mp3", "audio/mpeg", "libmp3lame", ["-b:a", "96k"], "mp3", "mp3"),
        ("tone.m4a", "audio/mp4", "aac", ["-b:a", "96k", "-movflags", "+faststart"], "aac", "m4a"),
        ("tone-vorbis.ogg", "audio/ogg", "libvorbis", ["-q:a", "3"], "vorbis", "ogg"),
        ("tone-opus.ogg", "audio/ogg", "libopus", ["-b:a", "96k"], "opus", "ogg"),
    ],
)
def test_real_codec_source_round_trips_byte_exactly_via_v2_api(
    tmp_path: Path,
    codec_tools: tuple[Path, Path],
    filename: str,
    content_type: str,
    encoder: str,
    encoder_args: list[str],
    expected_codec: str,
    expected_container: str,
):
    """Valid encoded sources select V2 and remain exactly extractable."""
    ffmpeg, ffprobe = codec_tools
    vocal = tmp_path / filename
    music = tmp_path / "tone.wav"
    _run([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", SINE_SOURCE,
        "-ac", "1", "-c:a", encoder, *encoder_args, str(vocal),
    ])
    _run([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", SINE_SOURCE,
        "-ac", "1", "-c:a", "pcm_s16le", str(music),
    ])
    _probe_and_decode(ffmpeg, ffprobe, vocal, codec=expected_codec, container=expected_container)
    _probe_and_decode(ffmpeg, ffprobe, music, codec="pcm_s16le", container="wav")

    vocal_bytes = vocal.read_bytes()
    music_bytes = music.read_bytes()
    with TestClient(app) as client:
        created = client.post(
            "/api/create",
            files={
                "vocal": (filename, vocal_bytes, content_type),
                "music": ("tone.wav", music_bytes, "audio/wav"),
            },
            data={"title": "Synthetic codec fixture", "artist": "VMA tests"},
        )
        assert created.status_code == 200, created.text
        assert created.headers["X-VMA-Version"] == "2"
        session = created.headers["X-VMA-Session"]
        inspected = client.get(f"/api/vma/{session}")
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()["version"] == 2

        for stream_id, original in ((1, vocal_bytes), (2, music_bytes)):
            extracted = client.get(f"/api/vma/{session}/extract-stream/{stream_id}")
            assert extracted.status_code == 200, extracted.text
            assert extracted.content == original
            assert hashlib.sha256(extracted.content).digest() == hashlib.sha256(original).digest()