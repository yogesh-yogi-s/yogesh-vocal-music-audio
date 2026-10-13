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


def test_create_v2_with_wav_and_mp3_auto_detects_and_preserves_bytes(tmp_path):
    vocal = tmp_path / "my_vocal.wav"
    write_pcm_wav(vocal, channels=1, sample_rate=44_100, bit_depth=16, frames=32)
    vocal_bytes = vocal.read_bytes()
    mp3_bytes = b"ID3\x03\x00\x00\x00\x00\x00\x21" + bytes(range(64)) + b"\xff\xfb\x90\x00tail"

    with TestClient(app) as client:
        # Test /api/create with auto-detection (no version specified)
        created = client.post(
            "/api/create",
            data={"title": "Mixed Track", "artist": "Format Agnostic"},
            files={
                "vocal": ("my_vocal.wav", vocal_bytes, "audio/wav"),
                "music": ("instrumental.mp3", mp3_bytes, "audio/mpeg"),
            },
        )
        assert created.status_code == 200, created.text
        assert created.headers.get("X-VMA-Version") == "2"
        session = created.headers.get("X-VMA-Session")
        assert session is not None

        opened = client.post(
            "/api/open",
            files={"file": ("song.vma", created.content, "application/vnd.vma")},
        )
        assert opened.status_code == 200
        payload = opened.json()
        assert payload["version"] == 2
        assert payload["metadata"]["title"] == "Mixed Track"
        assert payload["stream_count"] == 2

        s1, s2 = payload["streams"]
        assert s1["stream_id"] == 1
        assert s1["format_id"] == 0x1000
        assert s1["source_filename"] == "my_vocal.wav"
        assert s1["media_type"] == "audio/wav"
        assert s1["file_extension"] == "wav"
        assert s1["download_filename"] == "my_vocal.wav"

        assert s2["stream_id"] == 2
        assert s2["format_id"] == 0x0000
        assert s2["source_filename"] == "instrumental.mp3"
        assert s2["media_type"] == "audio/mpeg"
        assert s2["file_extension"] == "mp3"
        assert s2["download_filename"] == "instrumental.mp3"

        # Byte-for-byte extraction verification
        ext1 = client.get(f"/api/vma/{session}/extract-stream/1")
        assert ext1.status_code == 200
        assert ext1.content == vocal_bytes
        assert hashlib.sha256(ext1.content).hexdigest() == hashlib.sha256(vocal_bytes).hexdigest()
        assert ext1.headers["content-type"].startswith("audio/wav")

        ext2 = client.get(f"/api/vma/{session}/extract-stream/2")
        assert ext2.status_code == 200
        assert ext2.content == mp3_bytes
        assert hashlib.sha256(ext2.content).hexdigest() == hashlib.sha256(mp3_bytes).hexdigest()
        assert ext2.headers["content-type"].startswith("audio/mpeg")


def test_create_v2_explicit_version_2_forces_v2_for_two_wavs(tmp_path):
    vocal = tmp_path / "vocal.wav"
    music = tmp_path / "music.wav"
    write_pcm_wav(vocal, channels=1, sample_rate=44_100, bit_depth=16, frames=20)
    write_pcm_wav(music, channels=2, sample_rate=48_000, bit_depth=24, frames=30)
    vocal_bytes = vocal.read_bytes()
    music_bytes = music.read_bytes()

    with TestClient(app) as client:
        created = client.post(
            "/api/create",
            data={"title": "V2 Forced", "artist": "Artist", "version": 2},
            files={
                "vocal": ("vocal.wav", vocal_bytes, "audio/wav"),
                "music": ("music.wav", music_bytes, "audio/wav"),
            },
        )
        assert created.status_code == 200
        assert created.headers.get("X-VMA-Version") == "2"

        opened = client.post(
            "/api/open",
            files={"file": ("song.vma", created.content, "application/vnd.vma")},
        )
        assert opened.status_code == 200
        payload = opened.json()
        assert payload["version"] == 2
        session = payload["session_id"]

        ext1 = client.get(f"/api/vma/{session}/extract-stream/1")
        assert ext1.status_code == 200
        assert ext1.content == vocal_bytes
        assert hashlib.sha256(ext1.content).hexdigest() == hashlib.sha256(vocal_bytes).hexdigest()

        ext2 = client.get(f"/api/vma/{session}/extract-stream/2")
        assert ext2.status_code == 200
        assert ext2.content == music_bytes
        assert hashlib.sha256(ext2.content).hexdigest() == hashlib.sha256(music_bytes).hexdigest()


def test_create_explicit_version_1_rejects_mp3_without_silent_fallback(tmp_path):
    vocal = tmp_path / "vocal.wav"
    write_pcm_wav(vocal, channels=1, sample_rate=44_100, bit_depth=16, frames=20)
    mp3_bytes = b"ID3\x03\x00\x00\x00\x00\x00\x21" + b"\xff\xfb\x90\x00mp3data"

    with TestClient(app) as client:
        # /api/create with version=1
        res1 = client.post(
            "/api/create",
            data={"version": 1},
            files={
                "vocal": ("vocal.wav", vocal.read_bytes(), "audio/wav"),
                "music": ("song.mp3", mp3_bytes, "audio/mpeg"),
            },
        )
        assert res1.status_code == 400
        assert "RIFF/WAVE" in res1.json()["detail"] or "VMA" in res1.json()["detail"]

        # /api/vma/create with version=1
        res2 = client.post(
            "/api/vma/create",
            data={"version": 1},
            files={
                "vocal": ("vocal.wav", vocal.read_bytes(), "audio/wav"),
                "music": ("song.mp3", mp3_bytes, "audio/mpeg"),
            },
        )
        assert res2.status_code == 422
        assert "RIFF/WAVE" in res2.json()["detail"] or "VMA" in res2.json()["detail"]


def test_api_vma_create_endpoint_consistency(tmp_path):
    vocal = tmp_path / "vocal.wav"
    write_pcm_wav(vocal, channels=1, sample_rate=44_100, bit_depth=16, frames=16)
    vocal_bytes = vocal.read_bytes()
    mp3_bytes = b"ID3\x03\x00\x00\x00\x00\x00\x21" + bytes(range(32)) + b"\xff\xfb\x90\x00tail"

    with TestClient(app) as client:
        # /api/vma/create auto-detects V2 for WAV + MP3
        created = client.post(
            "/api/vma/create",
            data={"title": "VMA API Mixed", "artist": "Artist"},
            files={
                "vocal": ("lead.wav", vocal_bytes, "audio/wav"),
                "music": ("beat.mp3", mp3_bytes, "audio/mpeg"),
            },
        )
        assert created.status_code == 200, created.text
        assert created.headers.get("X-VMA-Version") == "2"
        assert created.headers.get("X-VMA-Stream-Count") == "2"

        opened = client.post(
            "/api/open",
            files={"file": ("song.vma", created.content, "application/vnd.vma")},
        )
        assert opened.status_code == 200
        payload = opened.json()
        assert payload["version"] == 2
        session = payload["session_id"]

        ext_vocal = client.get(f"/api/vma/{session}/extract-stream/1")
        assert ext_vocal.status_code == 200
        assert ext_vocal.content == vocal_bytes

        ext_music = client.get(f"/api/vma/{session}/extract-stream/2")
        assert ext_music.status_code == 200
        assert ext_music.content == mp3_bytes


def test_arbitrary_binary_payloads_create_and_extract_byte_identical_via_api_create():
    vocal_bytes = bytes([i % 256 for i in range(1024)])
    instrumental_bytes = bytes([(i * 13 + 37) % 256 for i in range(2048)])

    with TestClient(app) as client:
        # Submit arbitrary binary payloads with unknown extensions
        created = client.post(
            "/api/create",
            data={"title": "Binary Test", "artist": "Format Agnostic"},
            files={
                "vocal": ("vocal_payload.dat", vocal_bytes, "application/octet-stream"),
                "music": ("instrumental_payload.xyz", instrumental_bytes, "application/octet-stream"),
            },
        )
        assert created.status_code == 200, created.text
        assert created.headers.get("X-VMA-Version") == "2"
        session = created.headers.get("X-VMA-Session")
        assert session is not None

        opened = client.post(
            "/api/open",
            files={"file": ("song.vma", created.content, "application/vnd.vma")},
        )
        assert opened.status_code == 200
        payload = opened.json()
        assert payload["version"] == 2
        assert payload["metadata"]["title"] == "Binary Test"
        assert payload["metadata"]["vocal_filename"] == "vocal_payload.dat"
        assert payload["metadata"]["music_filename"] == "instrumental_payload.xyz"
        assert payload["stream_count"] == 2

        s1, s2 = payload["streams"]
        # Verify stream 1: unknown data is NOT identified or labeled as WAV or MP3
        assert s1["stream_id"] == 1
        assert s1["role_name"] == "AUDIO_PRIMARY"
        assert s1["format_id"] == 0x0000
        assert s1["format_name"] is None
        assert s1["format_range"] == "unknown"
        assert s1["source_filename"] == "vocal_payload.dat"
        assert s1["file_extension"] == "dat"
        assert s1["download_filename"] == "vocal_payload.dat"
        assert s1["media_type"] == "application/octet-stream"
        assert s1["payload_size"] == len(vocal_bytes)

        # Verify stream 2: unknown data is NOT identified or labeled as WAV or MP3
        assert s2["stream_id"] == 2
        assert s2["role_name"] == "AUDIO_SUPPLEMENTAL"
        assert s2["format_id"] == 0x0000
        assert s2["format_name"] is None
        assert s2["format_range"] == "unknown"
        assert s2["source_filename"] == "instrumental_payload.xyz"
        assert s2["file_extension"] == "xyz"
        assert s2["download_filename"] == "instrumental_payload.xyz"
        assert s2["media_type"] == "application/octet-stream"
        assert s2["payload_size"] == len(instrumental_bytes)

        # Extraction: exact byte equality and matching SHA-256
        ext1 = client.get(f"/api/vma/{session}/extract-stream/1")
        assert ext1.status_code == 200
        assert ext1.content == vocal_bytes
        assert hashlib.sha256(ext1.content).digest() == hashlib.sha256(vocal_bytes).digest()
        assert ext1.headers["content-type"].startswith("application/octet-stream")
        assert "vocal_payload.dat" in ext1.headers.get("content-disposition", "")

        ext2 = client.get(f"/api/vma/{session}/extract-stream/2")
        assert ext2.status_code == 200
        assert ext2.content == instrumental_bytes
        assert hashlib.sha256(ext2.content).digest() == hashlib.sha256(instrumental_bytes).digest()
        assert ext2.headers["content-type"].startswith("application/octet-stream")
        assert "instrumental_payload.xyz" in ext2.headers.get("content-disposition", "")


def test_arbitrary_binary_payloads_via_api_vma_create():
    vocal_bytes = b"ARBITRARY_VOCAL_BINARY_CONTENT_\x00\xff\xfe\x01\x02" * 20
    music_bytes = b"DIFFERENT_INSTRUMENTAL_DATA_\x7f\x80\xaa\x55" * 30

    with TestClient(app) as client:
        created = client.post(
            "/api/vma/create",
            data={"title": "VMA Create Arbitrary", "artist": "Artist"},
            files={
                "vocal": ("track_vocal.custom", vocal_bytes, "application/octet-stream"),
                "music": ("track_music.raw", music_bytes, "application/octet-stream"),
            },
        )
        assert created.status_code == 200, created.text
        assert created.headers.get("X-VMA-Version") == "2"
        assert created.headers.get("X-VMA-Stream-Count") == "2"
        assert created.headers["content-type"].startswith("application/vnd.vma")

        opened = client.post(
            "/api/open",
            files={"file": ("song.vma", created.content, "application/vnd.vma")},
        )
        assert opened.status_code == 200
        payload = opened.json()
        assert payload["version"] == 2
        session = payload["session_id"]

        ext_vocal = client.get(f"/api/vma/{session}/extract-stream/1")
        assert ext_vocal.status_code == 200
        assert ext_vocal.content == vocal_bytes
        assert hashlib.sha256(ext_vocal.content).digest() == hashlib.sha256(vocal_bytes).digest()
        assert "track_vocal.custom" in ext_vocal.headers.get("content-disposition", "")

        ext_music = client.get(f"/api/vma/{session}/extract-stream/2")
        assert ext_music.status_code == 200
        assert ext_music.content == music_bytes
        assert hashlib.sha256(ext_music.content).digest() == hashlib.sha256(music_bytes).digest()
        assert "track_music.raw" in ext_music.headers.get("content-disposition", "")


def test_arbitrary_payloads_explicit_version_1_strictly_rejected():
    vocal_bytes = b"BINARY_VOCAL_PAYLOAD"
    music_bytes = b"BINARY_MUSIC_PAYLOAD"

    with TestClient(app) as client:
        # /api/create with version=1 must return 400 and NOT fall back to V2
        res1 = client.post(
            "/api/create",
            data={"version": 1},
            files={
                "vocal": ("vocal.dat", vocal_bytes, "application/octet-stream"),
                "music": ("music.dat", music_bytes, "application/octet-stream"),
            },
        )
        assert res1.status_code == 400
        assert "X-VMA-Version" not in res1.headers

        # /api/vma/create with version=1 must return 422 and NOT fall back to V2
        res2 = client.post(
            "/api/vma/create",
            data={"version": 1},
            files={
                "vocal": ("vocal.dat", vocal_bytes, "application/octet-stream"),
                "music": ("music.dat", music_bytes, "application/octet-stream"),
            },
        )
        assert res2.status_code == 422
        assert "X-VMA-Version" not in res2.headers


def test_arbitrary_binary_payloads_without_extension():
    vocal_bytes = b"EXTENSIONLESS_VOCAL_PAYLOAD_BYTES"
    music_bytes = b"EXTENSIONLESS_MUSIC_PAYLOAD_BYTES"

    with TestClient(app) as client:
        created = client.post(
            "/api/create",
            data={"title": "Extensionless"},
            files={
                "vocal": ("vocal_blob", vocal_bytes, "application/octet-stream"),
                "music": ("music_blob", music_bytes, "application/octet-stream"),
            },
        )
        assert created.status_code == 200
        assert created.headers.get("X-VMA-Version") == "2"
        session = created.headers.get("X-VMA-Session")
        assert session is not None

        opened = client.post(
            "/api/open",
            files={"file": ("song.vma", created.content, "application/vnd.vma")},
        )
        assert opened.status_code == 200
        payload = opened.json()
        assert payload["version"] == 2
        s1, s2 = payload["streams"]
        # Defaults to bin extension, unknown format
        assert s1["file_extension"] == "bin"
        assert s1["format_id"] == 0x0000
        assert s1["format_name"] is None
        assert s2["file_extension"] == "bin"
        assert s2["format_id"] == 0x0000
        assert s2["format_name"] is None

        ext1 = client.get(f"/api/vma/{session}/extract-stream/1")
        assert ext1.status_code == 200
        assert ext1.content == vocal_bytes
        assert hashlib.sha256(ext1.content).digest() == hashlib.sha256(vocal_bytes).digest()

        ext2 = client.get(f"/api/vma/{session}/extract-stream/2")
        assert ext2.status_code == 200
        assert ext2.content == music_bytes
        assert hashlib.sha256(ext2.content).digest() == hashlib.sha256(music_bytes).digest()


def test_empty_upload_rejected_with_400():
    valid_bytes = b"NON_EMPTY_BINARY_DATA"

    with TestClient(app) as client:
        # Empty vocal on /api/create
        res1 = client.post(
            "/api/create",
            files={
                "vocal": ("empty.dat", b"", "application/octet-stream"),
                "music": ("valid.dat", valid_bytes, "application/octet-stream"),
            },
        )
        assert res1.status_code == 400
        assert "uploaded file is empty" in res1.json()["detail"]

        # Empty music on /api/vma/create
        res2 = client.post(
            "/api/vma/create",
            files={
                "vocal": ("valid.dat", valid_bytes, "application/octet-stream"),
                "music": ("empty.dat", b"", "application/octet-stream"),
            },
        )
        assert res2.status_code == 400
        assert "uploaded file is empty" in res2.json()["detail"]


def test_untrusted_caller_audio_mime_does_not_mislabel_arbitrary_binary():
    vocal_bytes = b"BINARY_DATA_NOT_WAV" * 10
    music_bytes = b"BINARY_DATA_NOT_MP3" * 10

    with TestClient(app) as client:
        created = client.post(
            "/api/create",
            data={"title": "MIME Guard"},
            files={
                "vocal": ("vocal.dat", vocal_bytes, "audio/wav"),
                "music": ("music.xyz", music_bytes, "audio/mpeg"),
            },
        )
        assert created.status_code == 200
        assert created.headers.get("X-VMA-Version") == "2"
        session = created.headers.get("X-VMA-Session")

        opened = client.post(
            "/api/open",
            files={"file": ("song.vma", created.content, "application/vnd.vma")},
        )
        assert opened.status_code == 200
        payload = opened.json()
        s1, s2 = payload["streams"]

        # Neither stream should be mislabeled as WAV or MP3
        assert s1["format_id"] == 0x0000
        assert s1["format_name"] is None
        assert s1["media_type"] == "application/octet-stream"
        assert s1["file_extension"] == "dat"

        assert s2["format_id"] == 0x0000
        assert s2["format_name"] is None
        assert s2["media_type"] == "application/octet-stream"
        assert s2["file_extension"] == "xyz"

        ext1 = client.get(f"/api/vma/{session}/extract-stream/1")
        assert ext1.status_code == 200
        assert ext1.content == vocal_bytes

        ext2 = client.get(f"/api/vma/{session}/extract-stream/2")
        assert ext2.status_code == 200
        assert ext2.content == music_bytes


def test_valid_custom_mime_types_preserved():
    vocal_bytes = b"%PDF-1.4\n..."
    music_bytes = b'{"custom": true}'

    with TestClient(app) as client:
        created = client.post(
            "/api/create",
            data={"title": "Custom MIME"},
            files={
                "vocal": ("document.pdf", vocal_bytes, "application/pdf"),
                "music": ("data.json", music_bytes, "application/json"),
            },
        )
        assert created.status_code == 200
        session = created.headers.get("X-VMA-Session")

        opened = client.post(
            "/api/open",
            files={"file": ("song.vma", created.content, "application/vnd.vma")},
        )
        assert opened.status_code == 200
        payload = opened.json()
        s1, s2 = payload["streams"]
        assert s1["media_type"] == "application/pdf"
        assert s1["file_extension"] == "pdf"
        assert s2["media_type"] == "application/json"
        assert s2["file_extension"] == "json"

        ext1 = client.get(f"/api/vma/{session}/extract-stream/1")
        assert ext1.content == vocal_bytes
        ext2 = client.get(f"/api/vma/{session}/extract-stream/2")
        assert ext2.content == music_bytes


def test_id3_signature_in_unknown_extension_not_mislabeled_as_mp3():
    # File with unknown extension whose bytes happen to start with ID3
    vocal_bytes = b"ID3\x03\x00\x00\x00\x00\x00\x00_NOT_AN_MP3"
    music_bytes = b"REGULAR_BINARY_PAYLOAD"

    with TestClient(app) as client:
        created = client.post(
            "/api/create",
            files={
                "vocal": ("payload.dat", vocal_bytes, "application/octet-stream"),
                "music": ("music.bin", music_bytes, "application/octet-stream"),
            },
        )
        assert created.status_code == 200
        session = created.headers.get("X-VMA-Session")

        opened = client.post(
            "/api/open",
            files={"file": ("song.vma", created.content, "application/vnd.vma")},
        )
        assert opened.status_code == 200
        s1 = opened.json()["streams"][0]
        # Must retain its true extension and not be labeled as audio/mpeg
        assert s1["file_extension"] == "dat"
        assert s1["media_type"] == "application/octet-stream"
        assert s1["format_name"] is None

        ext1 = client.get(f"/api/vma/{session}/extract-stream/1")
        assert ext1.content == vocal_bytes


def test_path_traversal_filenames_safely_sanitized():
    vocal_bytes = b"SAFE_VOCAL_BYTES"
    music_bytes = b"SAFE_MUSIC_BYTES"

    with TestClient(app) as client:
        created = client.post(
            "/api/create",
            files={
                "vocal": ("../../evil_vocal.dat", vocal_bytes, "application/octet-stream"),
                "music": ("..\\..\\evil_music.bin", music_bytes, "application/octet-stream"),
            },
        )
        assert created.status_code == 200
        session = created.headers.get("X-VMA-Session")

        opened = client.post(
            "/api/open",
            files={"file": ("song.vma", created.content, "application/vnd.vma")},
        )
        assert opened.status_code == 200
        s1, s2 = opened.json()["streams"]
        # Filenames sanitized without path separators
        assert "/" not in s1["source_filename"] and "\\" not in s1["source_filename"]
        assert "/" not in s2["source_filename"] and "\\" not in s2["source_filename"]
        assert s1["source_filename"] == "evil_vocal.dat"
        assert s2["source_filename"] == "evil_music.bin"


