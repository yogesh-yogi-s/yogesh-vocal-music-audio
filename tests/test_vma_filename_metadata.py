"""Upload metadata must handle both filename separators on every host OS."""

from pathlib import PurePosixPath, PureWindowsPath

import pytest
from fastapi.testclient import TestClient

from backend.app import vma_service
from backend.app.main import app


@pytest.mark.parametrize("path_flavor", [PurePosixPath, PureWindowsPath], ids=["posix", "windows"])
@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("../../evil_vocal.dat", "evil_vocal.dat"),
        (r"..\..\evil_music.bin", "evil_music.bin"),
        (r"folder/subfolder\evil_music.bin", "evil_music.bin"),
        (r"C:\uploads\evil_music.bin", "evil_music.bin"),
        ("plain.bin", "plain.bin"),
        ("folder/音声.bin", "音声.bin"),
        ("", "stored.bin"),
        (None, "stored.bin"),
    ],
)
def test_source_filename_basename_is_portable(tmp_path, monkeypatch, path_flavor, filename, expected):
    payload = b"SAFE_MUSIC_BYTES"
    stored = tmp_path / "stored.bin"
    stored.write_bytes(payload)
    # Only lexical filename parsing varies; IO still uses the real temporary path.
    monkeypatch.setattr(vma_service, "Path", path_flavor)

    format_id, basename, media_type, extension = vma_service.resolve_format_metadata(
        stored, filename, "application/octet-stream"
    )

    assert basename == expected
    assert "/" not in basename and "\\" not in basename
    assert format_id == 0
    assert media_type == "application/octet-stream"
    assert extension == expected.rsplit(".", 1)[-1]
    assert stored.read_bytes() == payload


@pytest.mark.parametrize("path_flavor", [PurePosixPath, PureWindowsPath], ids=["posix", "windows"])
@pytest.mark.parametrize(
    ("filename", "expected", "extension"),
    [
        ("../../folder//./evil_music.bin", "evil_music.bin", "bin"),
        (r"folder\\..\\evil_music.bin", "evil_music.bin", "bin"),
        ("/tmp/evil_music.bin", "evil_music.bin", "bin"),
        (r"\\server\share\evil_music.bin", "evil_music.bin", "bin"),
        ("   ", "stored.bin", "bin"),
        ("folder/ 音声.BIN ", "音声.BIN", "bin"),
        ("CON.bin", "CON.bin", "bin"),
        ("bad<name>?.bin", "bad<name>?.bin", "bin"),
        ("evil\x00_music.bin", "evil_music.bin", "bin"),
        ("evil_music", "evil_music", "bin"),
        (".", "stored.bin", "bin"),
        ("..", "stored.bin", "bin"),
    ],
)
def test_filename_edge_cases_remain_metadata(tmp_path, monkeypatch, path_flavor, filename, expected, extension):
    stored = tmp_path / "stored.bin"
    stored.write_bytes(b"OPAQUE_PAYLOAD")
    monkeypatch.setattr(vma_service, "Path", path_flavor)
    assert vma_service.resolve_format_metadata(stored, filename, "application/octet-stream") == (
        0, expected, "application/octet-stream", extension
    )
    assert stored.read_bytes() == b"OPAQUE_PAYLOAD"


@pytest.mark.parametrize(
    ("filename", "expected", "extension"),
    [
        ("evil_music.bin", "evil_music.bin", "bin"),
        (r"..\..\evil_music.bin", "evil_music.bin", "bin"),
        ("../../evil_music.bin", "evil_music.bin", "bin"),
        (r"folder/subfolder\evil_music.bin", "evil_music.bin", "bin"),
        ("../../folder//./evil_music.bin", "evil_music.bin", "bin"),
        ("/tmp/evil_music.bin", "evil_music.bin", "bin"),
        (r"C:\uploads\evil_music.bin", "evil_music.bin", "bin"),
        (r"\\server\share\evil_music.bin", "evil_music.bin", "bin"),
        ("   ", "music-input.bin", "bin"),
        ("folder/音声.BIN", "音声.BIN", "bin"),
        ("CON.bin", "CON.bin", "bin"),
        ("bad<name>?.bin", "bad<name>?.bin", "bin"),
        ("evil_music", "evil_music", "bin"),
    ],
)
def test_api_filename_roundtrip_and_resolved_storage_containment(monkeypatch, filename, expected, extension):
    original_store = vma_service.store_upload
    destinations = []

    async def record_upload(upload, destination):
        root = app.state.storage.resolve()
        relative = destination.resolve().relative_to(root)
        assert len(relative.parts) == 2
        assert len(relative.parts[0]) == 32
        assert all(char in "0123456789abcdef" for char in relative.parts[0])
        assert relative.parts[1] in {"vocal-input.bin", "music-input.bin", "song.vma"}
        saved = await original_store(upload, destination)
        assert saved.resolve().is_relative_to(root)
        destinations.append(saved)
        return saved

    monkeypatch.setattr(vma_service, "store_upload", record_upload)
    payloads = (b"SAFE_VOCAL_BYTES", b"SAFE_MUSIC_BYTES\x00\xff")
    with TestClient(app) as client:
        root = app.state.storage.resolve()
        created = client.post("/api/create", files={
            "vocal": ("vocal.bin", payloads[0], "application/octet-stream"),
            "music": (filename, payloads[1], "application/octet-stream"),
        })
        assert created.status_code == 200
        assert created.headers["X-VMA-Version"] == "2"
        assert destinations[0].read_bytes() == payloads[0]
        assert destinations[1].read_bytes() == payloads[1]
        opened = client.post("/api/open", files={"file": ("song.vma", created.content, "application/vnd.vma")})
        assert opened.status_code == 200
        body = opened.json()
        stream = body["streams"][1]
        assert stream["source_filename"] == expected
        assert stream["file_extension"] == extension
        assert stream["download_filename"] == expected
        assert "/" not in expected and "\\" not in expected
        for stream_id, original in enumerate(payloads, start=1):
            extracted = client.get(f"/api/vma/{body['session_id']}/extract-stream/{stream_id}")
            assert extracted.status_code == 200
            assert extracted.content == original
        assert len(destinations) == 3
        for stored in root.rglob("*"):
            assert stored.resolve().is_relative_to(root)
            if stored.is_file():
                assert stored.name in {"vocal-input.bin", "music-input.bin", "song.vma", "v2-stream-1.bin", "v2-stream-2.bin"}
    assert not root.exists()


@pytest.mark.parametrize("filename", ["", None], ids=["empty", "missing"])
def test_api_rejects_missing_upload_filename_without_creating_storage(filename):
    with TestClient(app) as client:
        root = app.state.storage.resolve()
        response = client.post("/api/create", files={
            "vocal": ("vocal.bin", b"SAFE_VOCAL_BYTES", "application/octet-stream"),
            "music": (filename, b"SAFE_MUSIC_BYTES", "application/octet-stream"),
        })
        assert response.status_code == 422
        assert list(root.iterdir()) == []
    assert not root.exists()
