"""API coverage for opening, inspecting, and extracting V2 containers.

V2 stores opaque source-file bytes.  These tests prove the application reaches
the frozen V2 reader/extractor through the version dispatcher and returns each
payload byte-for-byte, while V2 never enters the V1-only playback path.
"""

import hashlib

from fastapi.testclient import TestClient

from backend.app.main import app
from conftest import write_pcm_wav
from vma.v2.format_info import FILE_EXTENSION, MEDIA_TYPE, SOURCE_FILENAME, FormatInfoTLV
from vma.v2.writer import V2StreamInput, create_vma_v2


def _build_mixed_v2(tmp_path):
    """A WAV stream plus an MP3-signature opaque stream, packaged as V2."""
    vocal_wav = tmp_path / "vocal.wav"
    write_pcm_wav(vocal_wav, channels=1, sample_rate=44_100, bit_depth=16, frames=64)
    vocal_bytes = vocal_wav.read_bytes()
    mp3_bytes = b"ID3\x03\x00\x00\x00\x00\x00\x21" + bytes(range(64)) + b"\xff\xfb\x90\x00tail"
    mp3_path = tmp_path / "song.mp3"
    mp3_path.write_bytes(mp3_bytes)

    container = create_vma_v2(
        [
            V2StreamInput(
                1, vocal_wav, role=1, format_id=0x1000,
                format_info=(
                    FormatInfoTLV(SOURCE_FILENAME, b"vocal.wav"),
                    FormatInfoTLV(MEDIA_TYPE, b"audio/wav"),
                    FormatInfoTLV(FILE_EXTENSION, b"wav"),
                ),
            ),
            V2StreamInput(
                2, mp3_path, role=2, format_id=0x0000,
                format_info=(
                    FormatInfoTLV(SOURCE_FILENAME, b"song.mp3"),
                    FormatInfoTLV(MEDIA_TYPE, b"audio/mpeg"),
                    FormatInfoTLV(FILE_EXTENSION, b"mp3"),
                ),
            ),
        ],
        tmp_path / "mixed.vma",
        metadata={"schema_version": 1, "title": "Mixed", "artist": "Artist"},
    )
    return container, vocal_bytes, mp3_bytes


def _open_v2(client, container):
    response = client.post(
        "/api/open",
        files={"file": ("mixed.vma", container.read_bytes(), "application/vnd.vma")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_v2_container_opens_and_inspects_through_the_api_with_version_two(tmp_path):
    container, vocal_bytes, _ = _build_mixed_v2(tmp_path)
    with TestClient(app) as client:
        payload = _open_v2(client, container)
        assert payload["version"] == 2
        assert payload["metadata"]["title"] == "Mixed"
        assert payload["stream_count"] == 2
        assert [stream["stream_id"] for stream in payload["streams"]] == [1, 2]

        first, second = payload["streams"]
        # V2 descriptors must not pretend to be V1 stream dictionaries.
        for stream in payload["streams"]:
            assert "codec" not in stream and "audio" not in stream and "type" not in stream
        assert first["role_name"] == "AUDIO_PRIMARY"
        assert first["format_id"] == 0x1000 and first["format_name"] == "RIFF_WAVE"
        assert first["source_filename"] == "vocal.wav"
        assert first["media_type"] == "audio/wav"
        assert first["download_filename"] == "vocal.wav"
        assert first["payload_size"] == len(vocal_bytes)
        assert second["role_name"] == "AUDIO_SUPPLEMENTAL"
        assert second["format_id"] == 0x0000 and second["format_name"] is None
        assert second["format_range"] == "unknown"
        assert second["source_filename"] == "song.mp3"
        assert second["media_type"] == "audio/mpeg"

        inspected = client.get(f"/api/vma/{payload['session_id']}")
        assert inspected.status_code == 200
        assert inspected.json()["version"] == 2


def test_v2_stream_extraction_returns_byte_identical_payloads(tmp_path):
    container, vocal_bytes, mp3_bytes = _build_mixed_v2(tmp_path)
    with TestClient(app) as client:
        session = _open_v2(client, container)["session_id"]
        for stream_id, original, filename, media in (
            (1, vocal_bytes, "vocal.wav", "audio/wav"),
            (2, mp3_bytes, "song.mp3", "audio/mpeg"),
        ):
            response = client.get(f"/api/vma/{session}/extract-stream/{stream_id}")
            assert response.status_code == 200, response.text
            assert hashlib.sha256(response.content).digest() == hashlib.sha256(original).digest()
            assert response.headers["content-type"].startswith(media)
            assert filename in response.headers.get("content-disposition", "")


def test_v2_never_enters_the_v1_playback_or_extraction_paths(tmp_path):
    container, _, _ = _build_mixed_v2(tmp_path)
    with TestClient(app) as client:
        session = _open_v2(client, container)["session_id"]
        assert client.get(f"/api/vma/{session}/stream/vocal").status_code == 409
        assert client.get(f"/api/vma/{session}/extract/vocal").status_code == 409
        assert client.get(f"/api/vma/{session}/extract-all").status_code == 409


def test_v2_unknown_stream_id_and_malformed_container_return_client_errors(tmp_path):
    container, _, _ = _build_mixed_v2(tmp_path)
    with TestClient(app) as client:
        session = _open_v2(client, container)["session_id"]
        assert client.get(f"/api/vma/{session}/extract-stream/99").status_code == 404

        truncated = container.read_bytes()[:-4]
        response = client.post(
            "/api/open",
            files={"file": ("broken.vma", truncated, "application/vnd.vma")},
        )
        # A V2 structural failure must be reported as a client error, not a 500.
        assert response.status_code == 400, response.text
        assert "V2" in response.json()["detail"]


def test_v1_containers_still_round_trip_through_open_playback_and_extraction(tmp_path):
    vocal = tmp_path / "vocal.wav"
    music = tmp_path / "music.wav"
    write_pcm_wav(vocal, channels=1, sample_rate=44_100, bit_depth=16, frames=20)
    write_pcm_wav(music, channels=2, sample_rate=48_000, bit_depth=24, frames=30)
    with TestClient(app) as client:
        created = client.post(
            "/api/create",
            data={"title": "V1", "artist": "Artist"},
            files={
                "vocal": ("vocal.wav", vocal.read_bytes(), "audio/wav"),
                "music": ("music.wav", music.read_bytes(), "audio/wav"),
            },
        )
        assert created.status_code == 200
        opened = client.post(
            "/api/open",
            files={"file": ("song.vma", created.content, "application/vnd.vma")},
        )
        assert opened.status_code == 200
        payload = opened.json()
        assert payload["version"] == 1
        assert "audio" in payload["streams"][0]
        session = payload["session_id"]
        assert client.get(f"/api/vma/{session}/stream/vocal").status_code == 200
        # The version-aware single-stream route also serves V1 by stream id.
        v1_stream = client.get(f"/api/vma/{session}/extract-stream/1")
        assert v1_stream.status_code == 200
        assert v1_stream.headers["content-type"].startswith("audio/wav")
