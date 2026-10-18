import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import Headers, UploadFile

from backend.app import vma_service
from backend.app.main import app


def _upload(payload: bytes, *, size: int | None) -> UploadFile:
    return UploadFile(
        BytesIO(payload),
        size=size,
        filename="untrusted.bin",
        headers=Headers({"content-type": "application/octet-stream"}),
    )


@pytest.mark.parametrize("known_size", [True, False])
def test_store_upload_rejects_oversized_input_without_leaving_a_partial_file(
    tmp_path, monkeypatch, known_size
):
    monkeypatch.setattr(vma_service, "MAX_UPLOAD_BYTES", 8)
    destination = tmp_path / "stored.bin"
    upload = _upload(b"123456789", size=9 if known_size else None)

    with pytest.raises(HTTPException) as error:
        asyncio.run(vma_service.store_upload(upload, destination))

    assert error.value.status_code == 413
    assert not destination.exists()


def test_oversized_session_upload_is_cleaned_up_without_affecting_an_existing_session(
    monkeypatch,
):
    monkeypatch.setattr(vma_service, "MAX_UPLOAD_BYTES", 8)
    vocal_bytes = b"VOC1"
    music_bytes = b"MUS2"

    with TestClient(app) as client:
        created = client.post(
            "/api/create",
            files={
                "vocal": ("vocal.dat", vocal_bytes, "application/octet-stream"),
                "music": ("music.dat", music_bytes, "application/octet-stream"),
            },
        )
        assert created.status_code == 200, created.text
        session = created.headers["x-vma-session"]
        storage = app.state.storage
        assert {directory.name for directory in storage.iterdir()} == {session}

        rejected = client.post(
            "/api/create",
            files={
                "vocal": ("small.dat", b"small", "application/octet-stream"),
                "music": ("large.dat", b"123456789", "application/octet-stream"),
            },
        )
        assert rejected.status_code == 413
        assert {directory.name for directory in storage.iterdir()} == {session}

        inspected = client.get(f"/api/vma/{session}")
        extracted = client.get(f"/api/vma/{session}/extract-stream/1")
        assert inspected.status_code == 200
        assert inspected.json()["version"] == 2
        assert extracted.status_code == 200
        assert extracted.content == vocal_bytes


def test_stateless_create_enforces_the_same_per_file_limit(monkeypatch):
    monkeypatch.setattr(vma_service, "MAX_UPLOAD_BYTES", 8)
    with TestClient(app) as client:
        rejected = client.post(
            "/api/vma/create",
            files={
                "vocal": ("small.dat", b"small", "application/octet-stream"),
                "music": ("large.dat", b"123456789", "application/octet-stream"),
            },
        )
    assert rejected.status_code == 413


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/open",
        "/api/vma/validate",
        "/api/vma/info",
        "/api/vma/extract/vocal",
        "/api/vma/extract/music",
        "/api/vma/extract/all",
    ],
)
def test_single_file_upload_endpoints_enforce_the_same_limit_and_cleanup(
    monkeypatch, endpoint
):
    monkeypatch.setattr(vma_service, "MAX_UPLOAD_BYTES", 8)

    with TestClient(app) as client:
        rejected = client.post(
            endpoint,
            files={
                "file": (
                    "../../oversized.vma",
                    b"123456789",
                    "application/vnd.vma",
                )
            },
        )

        assert rejected.status_code == 413
        assert list(app.state.storage.iterdir()) == []


def test_deceptive_inputs_and_invalid_sessions_fail_without_leaving_session_state():
    with TestClient(app) as client:
        storage = app.state.storage

        deceptive = client.post(
            "/api/create",
            files={
                "vocal": ("../../fake.wav", b"not a RIFF/WAVE", "audio/wav"),
                "music": ("..\\..\\also-fake.wav", b"still not WAVE", "audio/wav"),
            },
        )
        assert deceptive.status_code == 400
        assert list(storage.iterdir()) == []

        malformed = client.post(
            "/api/open",
            files={"file": ("../../broken.vma", b"VMAF", "application/vnd.vma")},
        )
        assert malformed.status_code == 400
        assert list(storage.iterdir()) == []

        for session_id in ("../" + "0" * 29, "0" * 31, "g" * 32):
            assert client.get(f"/api/vma/{session_id}").status_code == 404
        assert list(storage.iterdir()) == []


def test_untrusted_filename_and_media_type_metadata_are_bounded_and_safe(tmp_path):
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"opaque payload")
    hostile_name = "..\\..\\folder/\r\nInjected-" + ("é" * 200) + ".dat"

    _, filename, media_type, extension = vma_service.resolve_format_metadata(
        payload,
        hostile_name,
        "application/json\r\nx-injected: true",
    )

    assert len(filename.encode("utf-8")) <= vma_service.MAX_SOURCE_FILENAME_BYTES
    assert not any(character in filename for character in ("/", "\\", "\r", "\n", "\x00"))
    assert media_type == "application/octet-stream"
    assert extension
