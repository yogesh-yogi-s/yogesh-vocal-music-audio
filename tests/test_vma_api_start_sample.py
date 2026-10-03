"""API/service propagation tests for start_sample — VMA v0.2 Step 3.

Covers both endpoint families:
- /api/vma/create  (stateless)
- /api/create      (session-based)

Assertions:
- omitted fields → start_sample=0
- vocal_start_sample propagates correctly
- music_start_sample propagates correctly
- both propagate independently
- negative values rejected via existing library VMAError → HTTP 422/400
"""
import io
import json
import struct

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from conftest import write_pcm_wav
from vma.format import HEADER_SIZE, HEADER_STRUCT, STREAM_ENTRY_SIZE, STREAM_STRUCT


SAMPLE_RATE = 44_100


@pytest.fixture()
def wav_bytes(tmp_path):
    vocal = tmp_path / "v.wav"
    music = tmp_path / "m.wav"
    write_pcm_wav(vocal, channels=1, sample_rate=SAMPLE_RATE, bit_depth=16, frames=SAMPLE_RATE)
    write_pcm_wav(music, channels=1, sample_rate=SAMPLE_RATE, bit_depth=16, frames=SAMPLE_RATE)
    return vocal.read_bytes(), music.read_bytes()


def _start_samples_from_vma(vma_bytes: bytes) -> tuple[int, int]:
    """Parse start_sample fields directly from raw VMA bytes for both streams."""
    raw = vma_bytes
    metadata_size = HEADER_STRUCT.unpack_from(raw)[5]
    vocal_entry = STREAM_STRUCT.unpack_from(raw, HEADER_SIZE + metadata_size)
    music_entry = STREAM_STRUCT.unpack_from(raw, HEADER_SIZE + metadata_size + STREAM_ENTRY_SIZE)
    # field index 6 is start_sample (signed int64)
    return vocal_entry[6], music_entry[6]


# ---------------------------------------------------------------------------
# Helpers to post to each endpoint family
# ---------------------------------------------------------------------------

def _post_stateless(client, vocal_bytes, music_bytes, **extra_data):
    return client.post(
        "/api/vma/create",
        data={"title": "T", "artist": "A", **extra_data},
        files={
            "vocal": ("v.wav", vocal_bytes, "audio/wav"),
            "music": ("m.wav", music_bytes, "audio/wav"),
        },
    )


def _post_session(client, vocal_bytes, music_bytes, **extra_data):
    return client.post(
        "/api/create",
        data={"title": "T", "artist": "A", **extra_data},
        files={
            "vocal": ("v.wav", vocal_bytes, "audio/wav"),
            "music": ("m.wav", music_bytes, "audio/wav"),
        },
    )


# ---------------------------------------------------------------------------
# Stateless family: /api/vma/create
# ---------------------------------------------------------------------------

class TestStatelessStartSample:
    def test_omitted_fields_default_to_zero(self, wav_bytes):
        vocal_b, music_b = wav_bytes
        with TestClient(app) as client:
            r = _post_stateless(client, vocal_b, music_b)
        assert r.status_code == 200, r.text
        assert _start_samples_from_vma(r.content) == (0, 0)

    def test_vocal_start_sample_propagates(self, wav_bytes):
        vocal_b, music_b = wav_bytes
        with TestClient(app) as client:
            r = _post_stateless(client, vocal_b, music_b, vocal_start_sample=44100)
        assert r.status_code == 200, r.text
        vocal_ss, music_ss = _start_samples_from_vma(r.content)
        assert vocal_ss == 44100
        assert music_ss == 0

    def test_music_start_sample_propagates(self, wav_bytes):
        vocal_b, music_b = wav_bytes
        with TestClient(app) as client:
            r = _post_stateless(client, vocal_b, music_b, music_start_sample=22050)
        assert r.status_code == 200, r.text
        vocal_ss, music_ss = _start_samples_from_vma(r.content)
        assert vocal_ss == 0
        assert music_ss == 22050

    def test_both_propagate_independently(self, wav_bytes):
        vocal_b, music_b = wav_bytes
        with TestClient(app) as client:
            r = _post_stateless(client, vocal_b, music_b, vocal_start_sample=11025, music_start_sample=33075)
        assert r.status_code == 200, r.text
        assert _start_samples_from_vma(r.content) == (11025, 33075)

    def test_negative_vocal_start_sample_rejected(self, wav_bytes):
        vocal_b, music_b = wav_bytes
        with TestClient(app) as client:
            r = _post_stateless(client, vocal_b, music_b, vocal_start_sample=-1)
        assert r.status_code == 422
        assert "vocal_start_sample" in r.json()["detail"]

    def test_negative_music_start_sample_rejected(self, wav_bytes):
        vocal_b, music_b = wav_bytes
        with TestClient(app) as client:
            r = _post_stateless(client, vocal_b, music_b, music_start_sample=-1)
        assert r.status_code == 422
        assert "music_start_sample" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Session-based family: /api/create
# ---------------------------------------------------------------------------

class TestSessionStartSample:
    def test_omitted_fields_default_to_zero(self, wav_bytes):
        vocal_b, music_b = wav_bytes
        with TestClient(app) as client:
            r = _post_session(client, vocal_b, music_b)
        assert r.status_code == 200, r.text
        assert _start_samples_from_vma(r.content) == (0, 0)

    def test_vocal_start_sample_propagates(self, wav_bytes):
        vocal_b, music_b = wav_bytes
        with TestClient(app) as client:
            r = _post_session(client, vocal_b, music_b, vocal_start_sample=44100)
        assert r.status_code == 200, r.text
        vocal_ss, music_ss = _start_samples_from_vma(r.content)
        assert vocal_ss == 44100
        assert music_ss == 0

    def test_music_start_sample_propagates(self, wav_bytes):
        vocal_b, music_b = wav_bytes
        with TestClient(app) as client:
            r = _post_session(client, vocal_b, music_b, music_start_sample=22050)
        assert r.status_code == 200, r.text
        vocal_ss, music_ss = _start_samples_from_vma(r.content)
        assert vocal_ss == 0
        assert music_ss == 22050

    def test_both_propagate_independently(self, wav_bytes):
        vocal_b, music_b = wav_bytes
        with TestClient(app) as client:
            r = _post_session(client, vocal_b, music_b, vocal_start_sample=11025, music_start_sample=33075)
        assert r.status_code == 200, r.text
        assert _start_samples_from_vma(r.content) == (11025, 33075)

    def test_negative_vocal_start_sample_rejected(self, wav_bytes):
        vocal_b, music_b = wav_bytes
        with TestClient(app) as client:
            r = _post_session(client, vocal_b, music_b, vocal_start_sample=-1)
        # /api/create maps VMAError to HTTP 400
        assert r.status_code == 400
        assert "vocal_start_sample" in r.json()["detail"]

    def test_negative_music_start_sample_rejected(self, wav_bytes):
        vocal_b, music_b = wav_bytes
        with TestClient(app) as client:
            r = _post_session(client, vocal_b, music_b, music_start_sample=-1)
        assert r.status_code == 400
        assert "music_start_sample" in r.json()["detail"]
