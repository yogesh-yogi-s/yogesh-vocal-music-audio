import os
import time

from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.main import OWNER_COOKIE_NAME, app


SESSION_ROUTES = (
    "/api/vma/{session}",
    "/api/vma/{session}/stream/vocal",
    "/api/vma/{session}/extract/music",
    "/api/vma/{session}/extract-all",
    "/api/vma/{session}/extract-stream/1",
)


def _open_demo(client: TestClient) -> tuple[str, str]:
    response = client.post("/api/demo")
    assert response.status_code == 200, response.text
    token = client.cookies.get(OWNER_COOKIE_NAME)
    assert token
    return response.json()["session_id"], token


def _use_owner(client: TestClient, token: str | None) -> None:
    client.cookies.clear()
    if token is not None:
        client.cookies.set(OWNER_COOKIE_NAME, token, path="/api")


def test_session_id_alone_and_wrong_browser_credential_cannot_access_any_route_category():
    with TestClient(app) as client:
        session, owner = _open_demo(client)

        for credential in (None, "x" * 43):
            _use_owner(client, credential)
            for route in SESSION_ROUTES:
                denied = client.get(route.format(session=session))
                assert denied.status_code == 404
                assert denied.json() == {"detail": "VMA session not found"}
                assert session not in denied.text
                assert owner not in denied.text

        _use_owner(client, owner)
        for route in SESSION_ROUTES:
            allowed = client.get(route.format(session=session))
            assert allowed.status_code == 200, (route, allowed.text)
            assert allowed.headers.get("cache-control") == "private, no-store"


def test_two_valid_browser_credentials_cannot_cross_access_sessions():
    with TestClient(app) as client:
        first_session, first_owner = _open_demo(client)
        _use_owner(client, None)
        second_session, second_owner = _open_demo(client)

        assert first_owner != second_owner
        assert client.get(f"/api/vma/{first_session}").status_code == 404
        assert client.get(f"/api/vma/{second_session}").status_code == 200

        _use_owner(client, first_owner)
        assert client.get(f"/api/vma/{first_session}").status_code == 200
        assert client.get(f"/api/vma/{second_session}").status_code == 404


def test_owner_cookie_is_httponly_strict_and_secure_outside_true_loopback_development():
    with TestClient(app) as local_client:
        local = local_client.post("/api/demo")
        cookie = local.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        assert "path=/api" in cookie
        assert "secure" not in cookie

    with TestClient(app, base_url="https://vma.example") as production_client:
        production = production_client.post("/api/demo")
        cookie = production.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        assert "secure" in cookie


def test_client_supplied_credential_is_replaced_instead_of_becoming_an_owner():
    planted = "p" * 43
    with TestClient(app) as client:
        _use_owner(client, planted)
        response = client.post("/api/demo")
        assert response.status_code == 200
        issued = response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
        assert issued and issued != planted

        session = response.json()["session_id"]
        _use_owner(client, planted)
        assert client.get(f"/api/vma/{session}").status_code == 404
        _use_owner(client, issued)
        assert client.get(f"/api/vma/{session}").status_code == 200


def test_one_browser_can_own_multiple_personal_and_demo_sessions_without_invalidation():
    files = {
        "vocal": ("vocal.bin", b"PERSONAL_VOCAL", "application/octet-stream"),
        "music": ("music.bin", b"PERSONAL_MUSIC", "application/octet-stream"),
    }
    with TestClient(app) as client:
        first = client.post("/api/create", files=files)
        assert first.status_code == 200, first.text
        first_session = first.headers["x-vma-session"]
        owner = client.cookies.get(OWNER_COOKIE_NAME)

        demo = client.post("/api/demo")
        second = client.post("/api/create", files=files)
        assert demo.status_code == 200
        assert second.status_code == 200
        assert client.cookies.get(OWNER_COOKIE_NAME) == owner

        sessions = (first_session, demo.json()["session_id"], second.headers["x-vma-session"])
        assert len(set(sessions)) == 3
        for session in sessions:
            assert client.get(f"/api/vma/{session}").status_code == 200

        _use_owner(client, "z" * 43)
        for session in sessions:
            assert client.get(f"/api/vma/{session}").status_code == 404


def test_cross_site_creation_open_demo_and_deletion_requests_are_rejected():
    hostile = {"origin": "https://attacker.example", "sec-fetch-site": "cross-site"}
    files = {
        "vocal": ("vocal.bin", b"vocal", "application/octet-stream"),
        "music": ("music.bin", b"music", "application/octet-stream"),
    }
    with TestClient(app) as client:
        session, _ = _open_demo(client)
        original_directories = {path.name for path in app.state.storage.iterdir()}

        assert client.post("/api/demo", headers=hostile).status_code == 403
        assert client.post("/api/create", headers=hostile, files=files).status_code == 403
        assert client.post(
            "/api/open",
            headers=hostile,
            files={"file": ("song.vma", b"not-vma", "application/vnd.vma")},
        ).status_code == 403
        assert client.delete(f"/api/vma/{session}", headers=hostile).status_code == 403
        assert {path.name for path in app.state.storage.iterdir()} == original_directories
        assert client.get(f"/api/vma/{session}").status_code == 200

        same_origin = {"origin": "http://testserver", "sec-fetch-site": "same-origin"}
        assert client.delete(f"/api/vma/{session}", headers=same_origin).status_code == 204


def test_expired_session_returns_the_same_generic_response_and_is_removed(monkeypatch):
    monkeypatch.setattr(app_main, "SESSION_TTL_SECONDS", 1)
    with TestClient(app) as client:
        session, owner = _open_demo(client)
        directory = app.state.storage / session
        song = directory / "song.vma"
        expired = time.time() - 5
        os.utime(song, (expired, expired))

        response = client.get(f"/api/vma/{session}")
        assert response.status_code == 404
        assert response.json() == {"detail": "VMA session not found"}
        assert owner not in response.text
        assert not directory.exists()


def test_deletion_requires_ownership_revokes_immediately_and_preserves_other_sessions():
    with TestClient(app) as client:
        deleted_session, owner = _open_demo(client)
        retained_session, _ = _open_demo(client)
        deleted_directory = app.state.storage / deleted_session

        for credential in (None, "q" * 43):
            _use_owner(client, credential)
            denied = client.delete(f"/api/vma/{deleted_session}")
            assert denied.status_code == 404
            assert denied.json() == {"detail": "VMA session not found"}
            assert deleted_directory.exists()

        _use_owner(client, owner)
        assert client.delete(f"/api/vma/{deleted_session}").status_code == 204
        assert not deleted_directory.exists()
        assert client.get(f"/api/vma/{deleted_session}").status_code == 404
        assert client.get(f"/api/vma/{retained_session}").status_code == 200


def test_deletion_waits_for_an_active_response_but_blocks_new_access():
    with TestClient(app) as client:
        session, _ = _open_demo(client)
        directory = app.state.storage / session
        app.state.active_sessions[session] = 1

        assert client.delete(f"/api/vma/{session}").status_code == 204
        assert directory.exists()
        assert (directory / app_main.DELETED_FILE_NAME).exists()
        assert client.get(f"/api/vma/{session}").status_code == 404

        app_main._release_session(app, session)
        assert not directory.exists()


def test_frontend_exposes_owned_session_deletion_without_putting_a_secret_in_javascript():
    html = (app_main.ROOT / "frontend" / "index.html").read_text("utf-8")
    script = (app_main.ROOT / "frontend" / "js" / "app.js").read_text("utf-8")

    assert 'id="delete-session"' in html
    assert "fetch(`/api/vma/${session}`, { method: 'DELETE' })" in script
    assert OWNER_COOKIE_NAME not in html
    assert OWNER_COOKIE_NAME not in script
