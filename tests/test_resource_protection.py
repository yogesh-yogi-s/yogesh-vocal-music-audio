import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import os
from types import SimpleNamespace
import threading
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import Headers, UploadFile

from backend.app import main as app_main
from backend.app import resource_control
from backend.app import vma_service
from backend.app.main import app


UPLOAD_ROUTES = (
    ("/api/create", 2),
    ("/api/vma/create", 2),
    ("/api/open", 1),
    ("/api/vma/validate", 1),
    ("/api/vma/info", 1),
    ("/api/vma/extract/vocal", 1),
    ("/api/vma/extract/music", 1),
    ("/api/vma/extract/all", 1),
)


def test_configured_upload_limit_keeps_product_ceiling(monkeypatch):
    monkeypatch.delenv("VMA_MAX_UPLOAD_BYTES", raising=False)
    assert vma_service._configured_upload_limit() == 500 * resource_control.MIB

    monkeypatch.setenv("VMA_MAX_UPLOAD_BYTES", str(10 * resource_control.MIB))
    assert vma_service._configured_upload_limit() == 10 * resource_control.MIB

    for invalid in ("0", str(500 * resource_control.MIB + 1), "invalid"):
        monkeypatch.setenv("VMA_MAX_UPLOAD_BYTES", invalid)
        with pytest.raises(RuntimeError, match="VMA_MAX_UPLOAD_BYTES"):
            vma_service._configured_upload_limit()


def test_small_preview_budget_allows_demo_streams_with_lower_upload_ceiling(monkeypatch):
    monkeypatch.setattr(vma_service, "MAX_UPLOAD_BYTES", 10 * resource_control.MIB)
    monkeypatch.setattr(resource_control, "MAX_PROCESS_TEMP_BYTES", 200 * resource_control.MIB)

    with TestClient(app) as client:
        opened = client.post("/api/demo")
        assert opened.status_code == 200, opened.text
        session = opened.json()["session_id"]
        for kind in ("vocal", "music"):
            response = client.get(f"/api/vma/{session}/stream/{kind}")
            assert response.status_code == 200, response.text
            assert response.content.startswith(b"RIFF")


@pytest.mark.parametrize(("path", "file_count"), UPLOAD_ROUTES)
def test_content_length_limits_reject_every_multipart_route_before_parsing(
    monkeypatch, path, file_count
):
    monkeypatch.setattr(vma_service, "MAX_UPLOAD_BYTES", 8)
    monkeypatch.setattr(resource_control, "MULTIPART_OVERHEAD_BYTES", 64)
    limit = file_count * 8 + 64

    with TestClient(app) as client:
        response = client.post(path, content=b"x" * (limit + 1))

    assert response.status_code == 413
    assert response.json() == {"detail": "request body is too large"}


def test_multipart_overhead_is_allowed_but_is_not_unbounded(monkeypatch):
    monkeypatch.setattr(vma_service, "MAX_UPLOAD_BYTES", 8)
    monkeypatch.setattr(resource_control, "MULTIPART_OVERHEAD_BYTES", 1024)
    files = {
        "vocal": ("vocal.bin", b"12345678", "application/octet-stream"),
        "music": ("music.bin", b"abcdefgh", "application/octet-stream"),
    }

    with TestClient(app) as client:
        accepted = client.post("/api/create", files=files)
        rejected = client.post(
            "/api/create", files=files, data={"title": "x" * 2048}
        )

    assert accepted.status_code == 200, accepted.text
    assert rejected.status_code == 413
    assert rejected.json() == {"detail": "request body is too large"}


def test_chunked_demo_body_is_limited_without_content_length(monkeypatch):
    monkeypatch.setattr(resource_control, "DEMO_REQUEST_BYTES", 8)

    def chunks():
        yield b"12345"
        yield b"67890"

    with TestClient(app) as client:
        response = client.post("/api/demo", content=chunks())
        assert list(app.state.storage.iterdir()) == []

    assert response.status_code == 413
    assert response.json() == {"detail": "request body is too large"}


def test_chunked_multipart_body_is_counted_when_content_length_is_missing(monkeypatch):
    monkeypatch.setattr(vma_service, "MAX_UPLOAD_BYTES", 8)
    monkeypatch.setattr(resource_control, "MULTIPART_OVERHEAD_BYTES", 64)

    payload = (
        b"--phase2\r\n"
        b'Content-Disposition: form-data; name="file"; filename="song.vma"\r\n'
        b"Content-Type: application/vnd.vma\r\n\r\n"
        + b"x" * 100
        + b"\r\n--phase2--\r\n"
    )

    def chunks():
        for offset in range(0, len(payload), 32):
            yield payload[offset : offset + 32]

    with TestClient(app) as client:
        response = client.post(
            "/api/open",
            content=chunks(),
            headers={"content-type": "multipart/form-data; boundary=phase2"},
        )
        assert list(app.state.storage.iterdir()) == []

    assert response.status_code == 413
    assert response.json() == {"detail": "request body is too large"}


def test_rate_limit_boundary_uses_direct_peer_and_ignores_forwarded_ip():
    with TestClient(app) as client:
        governor = app.state.resource_governor
        governor.rate_limits["demo"] = 2

        assert client.post(
            "/api/demo", headers={"x-forwarded-for": "198.51.100.1"}
        ).status_code == 200
        assert client.post(
            "/api/demo", headers={"x-forwarded-for": "198.51.100.2"}
        ).status_code == 200
        limited = client.post(
            "/api/demo", headers={"x-forwarded-for": "198.51.100.3"}
        )

    assert limited.status_code == 429
    assert limited.json() == {"detail": "rate limit exceeded"}
    assert int(limited.headers["retry-after"]) >= 1


def test_process_storage_admission_accepts_boundary_then_rejects_without_eviction(monkeypatch):
    monkeypatch.setattr(resource_control, "MAX_PROCESS_TEMP_BYTES", resource_control.MIB)
    with TestClient(app) as client:
        first = client.post("/api/demo")
        assert first.status_code == 200, first.text
        session = first.json()["session_id"]

        rejected = client.post("/api/demo")
        assert rejected.status_code == 507
        assert rejected.json() == {"detail": "temporary storage capacity is unavailable"}
        assert client.get(f"/api/vma/{session}").status_code == 200


def test_process_concurrency_boundary_returns_predictable_429():
    with TestClient(app) as client:
        governor = app.state.resource_governor
        governor.active_expensive = resource_control.MAX_ACTIVE_EXPENSIVE_REQUESTS
        response = client.post("/api/demo")
        governor.active_expensive = 0

    assert response.status_code == 429
    assert response.json() == {"detail": "server is busy"}
    assert response.headers["retry-after"] == "1"


def test_browser_session_quota_rejects_new_session_without_deleting_existing(monkeypatch):
    monkeypatch.setattr(app_main, "MAX_BROWSER_SESSIONS", 1)
    with TestClient(app) as client:
        first = client.post("/api/demo")
        assert first.status_code == 200
        session = first.json()["session_id"]

        rejected = client.post("/api/demo")
        assert rejected.status_code == 429
        assert rejected.json() == {"detail": "browser session limit exceeded"}
        assert client.get(f"/api/vma/{session}").status_code == 200


def test_process_session_quota_rejects_without_evicting_another_browser(monkeypatch):
    monkeypatch.setattr(app_main, "MAX_PROCESS_SESSIONS", 1)
    with TestClient(app) as client:
        first = client.post("/api/demo")
        first_directory = app.state.storage / first.json()["session_id"]
        client.cookies.clear()

        rejected = client.post("/api/demo")
        assert rejected.status_code == 429
        assert rejected.json() == {"detail": "server session limit exceeded"}
        assert first_directory.exists()


def test_per_session_storage_limit_is_derived_from_file_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(vma_service, "MAX_UPLOAD_BYTES", 4)
    monkeypatch.setattr(app_main, "MULTIPART_OVERHEAD_BYTES", 2)
    (tmp_path / "song.vma").write_bytes(b"x" * 11)

    with pytest.raises(HTTPException) as error:
        app_main._enforce_session_size(tmp_path)

    assert error.value.status_code == 507


def test_per_session_active_operation_boundary_is_predictable():
    with TestClient(app) as client:
        opened = client.post("/api/demo")
        session = opened.json()["session_id"]
        app.state.active_sessions[session] = resource_control.MAX_ACTIVE_SESSION_OPERATIONS

        limited = client.get(f"/api/vma/{session}/extract/vocal")
        app.state.active_sessions.pop(session, None)

    assert limited.status_code == 429
    assert limited.json() == {"detail": "session operation limit exceeded"}
    assert limited.headers["retry-after"] == "1"


def test_v2_stream_extraction_has_extract_limits_and_a_safe_reservation():
    policy = resource_control.request_policy(
        "GET", "/api/vma/00000000-0000-0000-0000-000000000000/extract-stream/1"
    )

    assert policy.category == "extract"
    assert policy.body_limit is None
    assert policy.expensive is True
    assert policy.storage_reservation == (
        2 * vma_service.MAX_UPLOAD_BYTES + resource_control.MULTIPART_OVERHEAD_BYTES
    )


def test_v2_stream_extraction_obeys_rate_and_storage_limits(monkeypatch):
    files = {
        "vocal": ("vocal.bin", b"vocal payload", "application/octet-stream"),
        "music": (
            "music.bin",
            b"instrumental payload",
            "application/octet-stream",
        ),
    }
    with TestClient(app) as client:
        created = client.post("/api/vma/create", files=files)
        assert created.status_code == 200, created.text
        opened = client.post(
            "/api/open",
            files={
                "file": ("created.vma", created.content, "application/vnd.vma")
            },
        )
        assert opened.status_code == 200, opened.text
        session = opened.json()["session_id"]
        governor = app.state.resource_governor
        governor.active_expensive = resource_control.MAX_ACTIVE_EXPENSIVE_REQUESTS
        busy = client.get(f"/api/vma/{session}/extract-stream/1")
        governor.active_expensive = 0
        governor.requests.clear()
        assert busy.status_code == 429
        assert busy.json() == {"detail": "server is busy"}

        governor.rate_limits["extract"] = 1

        first = client.get(f"/api/vma/{session}/extract-stream/1")
        assert first.status_code == 200, first.text
        assert first.content == b"vocal payload"
        assert governor.reserved_temp_bytes == 0

        limited = client.get(f"/api/vma/{session}/extract-stream/2")
        assert limited.status_code == 429
        assert limited.json() == {"detail": "rate limit exceeded"}

        governor.requests.clear()
        monkeypatch.setattr(resource_control, "MAX_PROCESS_TEMP_BYTES", 1)
        unavailable = client.get(f"/api/vma/{session}/extract-stream/2")
        assert unavailable.status_code == 507
        assert unavailable.json() == {
            "detail": "temporary storage capacity is unavailable"
        }
        assert governor.reserved_temp_bytes == 0


def test_failed_v2_stream_extraction_releases_storage_and_cleans_output(monkeypatch):
    def fail_extract(_source, _stream_id, target):
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b"partial")
        raise HTTPException(500, "synthetic extraction failure")

    monkeypatch.setattr(vma_service, "extract_track_v2", fail_extract)
    files = {
        "vocal": ("vocal.bin", b"vocal", "application/octet-stream"),
        "music": ("music.bin", b"music", "application/octet-stream"),
    }
    with TestClient(app) as client:
        created = client.post("/api/vma/create", files=files)
        assert created.status_code == 200, created.text
        opened = client.post(
            "/api/open",
            files={
                "file": ("created.vma", created.content, "application/vnd.vma")
            },
        )
        assert opened.status_code == 200, opened.text
        session = opened.json()["session_id"]
        response = client.get(f"/api/vma/{session}/extract-stream/1")
        directory = app.state.storage / session

        assert response.status_code == 500
        assert not list(directory.glob(".response-*"))
        assert app.state.resource_governor.reserved_temp_bytes == 0


def test_concurrent_v2_stream_extractions_honor_storage_reservations(monkeypatch):
    original = vma_service.extract_track_v2
    started = threading.Event()
    release = threading.Event()

    def blocking_extract(source, stream_id, target):
        result = original(source, stream_id, target)
        started.set()
        release.wait(timeout=5)
        return result

    monkeypatch.setattr(vma_service, "extract_track_v2", blocking_extract)
    files = {
        "vocal": ("vocal.bin", b"vocal payload", "application/octet-stream"),
        "music": ("music.bin", b"music payload", "application/octet-stream"),
    }
    with TestClient(app) as client:
        created = client.post("/api/vma/create", files=files)
        opened = client.post(
            "/api/open",
            files={
                "file": ("created.vma", created.content, "application/vnd.vma")
            },
        )
        session = opened.json()["session_id"]
        policy = resource_control.request_policy(
            "GET", f"/api/vma/{session}/extract-stream/1"
        )
        actual_size = resource_control.directory_size(app.state.temp_root)
        monkeypatch.setattr(
            resource_control,
            "MAX_PROCESS_TEMP_BYTES",
            actual_size + policy.storage_reservation,
        )

        with ThreadPoolExecutor(max_workers=1) as executor:
            first_future = executor.submit(
                client.get, f"/api/vma/{session}/extract-stream/1"
            )
            assert started.wait(timeout=5)
            second = client.get(f"/api/vma/{session}/extract-stream/2")
            release.set()
            first = first_future.result(timeout=5)

        assert first.status_code == 200
        assert first.content == b"vocal payload"
        assert second.status_code == 507
        assert second.json() == {
            "detail": "temporary storage capacity is unavailable"
        }
        assert app.state.resource_governor.reserved_temp_bytes == 0
        assert not list((app.state.storage / session).glob(".response-*"))


def test_cancelled_v2_stream_request_releases_reserved_storage(tmp_path):
    entered = asyncio.Event()

    async def downstream(_scope, _receive, _send):
        entered.set()
        await asyncio.Future()

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    async def scenario():
        governor = resource_control.ResourceGovernor(tmp_path)
        application = SimpleNamespace(
            state=SimpleNamespace(resource_governor=governor, temp_root=tmp_path)
        )
        middleware = resource_control.ResourceProtectionMiddleware(downstream)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/vma/session/extract-stream/1",
            "headers": [],
            "client": ("127.0.0.1", 50000),
            "app": application,
        }
        task = asyncio.create_task(middleware(scope, receive, send))
        await entered.wait()
        expected = (
            2 * vma_service.MAX_UPLOAD_BYTES
            + resource_control.MULTIPART_OVERHEAD_BYTES
        )
        assert governor.reserved_temp_bytes == expected
        assert governor.active_expensive == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert governor.reserved_temp_bytes == 0
        assert governor.active_expensive == 0

    asyncio.run(scenario())


def test_concurrent_extractions_use_unique_outputs_and_cleanup(monkeypatch):
    original = app_main.extract_vocal
    barrier = threading.Barrier(2)
    targets = []
    targets_lock = threading.Lock()

    def observed_extract(source, target):
        with targets_lock:
            targets.append(target)
        barrier.wait(timeout=5)
        return original(source, target)

    monkeypatch.setattr(app_main, "extract_vocal", observed_extract)
    with TestClient(app) as client:
        opened = client.post("/api/demo")
        session = opened.json()["session_id"]
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    lambda _: client.get(f"/api/vma/{session}/extract/vocal"),
                    range(2),
                )
            )

        assert all(response.status_code == 200 for response in responses)
        assert responses[0].content == responses[1].content
        assert len({target.parent for target in targets}) == 2
        assert all(not target.parent.exists() for target in targets)
        assert session not in app.state.active_sessions


def test_failed_session_extraction_cleans_partial_output_and_releases_lease(monkeypatch):
    def fail_extract(_source, target):
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b"partial")
        raise HTTPException(500, "synthetic extraction failure")

    monkeypatch.setattr(app_main, "extract_vocal", fail_extract)
    with TestClient(app) as client:
        opened = client.post("/api/demo")
        session = opened.json()["session_id"]
        response = client.get(f"/api/vma/{session}/extract/vocal")
        directory = app.state.storage / session

        assert response.status_code == 500
        assert not list(directory.glob(".response-*"))
        assert session not in app.state.active_sessions


def test_upload_copy_removes_partial_file_when_cancelled(tmp_path):
    upload = UploadFile(
        BytesIO(b"unused"),
        size=None,
        filename="cancelled.bin",
        headers=Headers({"content-type": "application/octet-stream"}),
    )
    calls = 0

    async def cancelled_read(_size):
        nonlocal calls
        calls += 1
        if calls == 1:
            return b"partial"
        raise asyncio.CancelledError

    upload.read = cancelled_read
    destination = tmp_path / "partial.bin"
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(vma_service.store_upload(upload, destination))
    assert not destination.exists()


def test_blocking_worker_finishes_before_cancellation_cleanup_can_continue():
    started = threading.Event()
    release = threading.Event()

    def blocking_work():
        started.set()
        release.wait(timeout=5)

    async def scenario():
        task = asyncio.create_task(app_main._run_blocking(blocking_work))
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_file_response_cleanup_runs_when_sending_is_cancelled(tmp_path):
    directory = tmp_path / "response"
    directory.mkdir()
    output = directory / "payload.bin"
    output.write_bytes(b"payload")
    response = app_main.GuaranteedCleanupFileResponse(
        output,
        cleanup=vma_service.cleanup_directory,
        cleanup_args=(directory,),
    )
    scope = {
        "type": "http",
        "method": "GET",
        "headers": [],
        "asgi": {"spec_version": "2.4"},
    }

    async def receive():
        return {"type": "http.disconnect"}

    async def cancelled_send(message):
        if message["type"] == "http.response.body":
            raise asyncio.CancelledError

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await response(scope, receive, cancelled_send)

    asyncio.run(scenario())
    assert not directory.exists()


def test_expiry_cleanup_never_removes_an_active_session(monkeypatch):
    monkeypatch.setattr(app_main, "SESSION_TTL_SECONDS", 1)
    with TestClient(app) as client:
        opened = client.post("/api/demo")
        session = opened.json()["session_id"]
        directory = app.state.storage / session
        song = directory / "song.vma"
        old = time.time() - 5
        os.utime(song, (old, old))

        app.state.active_sessions[session] = 1
        app_main._cleanup_expired_sessions_once(app)
        assert directory.exists()

        app.state.active_sessions.pop(session)
        app_main._cleanup_expired_sessions_once(app)
        assert not directory.exists()


def test_docker_image_declares_non_root_runtime_and_dedicated_temp_directory():
    dockerfile = (app_main.ROOT / "Dockerfile").read_text("utf-8")
    assert (
        "FROM python:3.13-alpine3.24@sha256:"
        "2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a\n"
        in dockerfile
    )
    assert "--upgrade pip" not in dockerfile
    assert "COPY requirements.lock ./" in dockerfile
    assert "-r requirements.lock" in dockerfile
    assert "-r requirements.txt" not in dockerfile
    runtime_lock = (app_main.ROOT / "requirements.lock").read_text("utf-8")
    dev_lock = (app_main.ROOT / "requirements-dev.lock").read_text("utf-8")
    assert "--require-hashes" in runtime_lock
    assert "--only-binary=:all:" in runtime_lock
    assert "fastapi==0.141.1" in runtime_lock
    assert "uvloop==0.23.0" in runtime_lock
    assert "-r requirements.lock" in dev_lock
    assert "pytest==9.1.1" in dev_lock
    assert "VMA_ENVIRONMENT=production" in dockerfile
    assert "VMA_HEALTHCHECK_HOST" in dockerfile
    assert "os.getenv('VMA_TRUSTED_HOSTS'" not in dockerfile
    assert "TMPDIR=/tmp/vma" in dockerfile
    assert "USER vma" in dockerfile
    compose = (app_main.ROOT / "deploy" / "docker-compose.yml").read_text("utf-8")
    assert "target: /tmp/vma" in compose
    assert "VMA_MAX_PROCESS_TEMP_BYTES" in compose
    assert "read_only: true" in compose
    assert "cap_drop: [ALL]" in compose
