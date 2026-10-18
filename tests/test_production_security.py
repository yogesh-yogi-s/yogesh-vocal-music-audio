import pytest
from fastapi.testclient import TestClient

from backend.app.deployment_security import load_deployment_settings
from backend.app.main import app


PRODUCTION = {
    "VMA_ENVIRONMENT": "production",
    "VMA_TRUSTED_HOSTS": "audio.example.test",
    "VMA_ALLOWED_ORIGINS": "https://audio.example.test",
    "VMA_HEALTHCHECK_HOST": "audio.example.test",
}

STATELESS_MULTIPART_ROUTES = (
    "/api/vma/create",
    "/api/vma/validate",
    "/api/vma/info",
    "/api/vma/extract/vocal",
    "/api/vma/extract/music",
    "/api/vma/extract/all",
)

SESSION_MULTIPART_ROUTES = ("/api/create", "/api/open")
ALL_MULTIPART_ROUTES = STATELESS_MULTIPART_ROUTES + SESSION_MULTIPART_ROUTES


def _production_client(monkeypatch, **updates):
    for name, value in {**PRODUCTION, **updates}.items():
        monkeypatch.setenv(name, value)
    return TestClient(app, base_url="http://audio.example.test")


def test_production_configuration_fails_closed_without_hosts_and_origins(monkeypatch):
    monkeypatch.setenv("VMA_ENVIRONMENT", "production")
    monkeypatch.delenv("VMA_TRUSTED_HOSTS", raising=False)
    monkeypatch.delenv("VMA_ALLOWED_ORIGINS", raising=False)
    with pytest.raises(RuntimeError, match="VMA_TRUSTED_HOSTS"):
        with TestClient(app):
            pass


def test_environment_mode_must_be_explicit(monkeypatch):
    monkeypatch.delenv("VMA_ENVIRONMENT", raising=False)
    with pytest.raises(RuntimeError, match="VMA_ENVIRONMENT must be explicitly set"):
        load_deployment_settings()


def test_unknown_environment_mode_fails_closed(monkeypatch):
    monkeypatch.setenv("VMA_ENVIRONMENT", "staging-ish")
    with pytest.raises(RuntimeError, match="development, production, or test"):
        load_deployment_settings()


def test_production_requires_an_explicit_healthcheck_host(monkeypatch):
    for name, value in PRODUCTION.items():
        if name != "VMA_HEALTHCHECK_HOST":
            monkeypatch.setenv(name, value)
    monkeypatch.delenv("VMA_HEALTHCHECK_HOST", raising=False)
    with pytest.raises(RuntimeError, match="VMA_HEALTHCHECK_HOST"):
        load_deployment_settings()


def test_exact_healthcheck_host_can_match_a_trusted_wildcard(monkeypatch):
    monkeypatch.setenv("VMA_ENVIRONMENT", "production")
    monkeypatch.setenv("VMA_TRUSTED_HOSTS", "*.example.test")
    monkeypatch.setenv("VMA_ALLOWED_ORIGINS", "https://audio.example.test")
    monkeypatch.setenv("VMA_HEALTHCHECK_HOST", "health.example.test")

    settings = load_deployment_settings()

    assert settings.healthcheck_host == "health.example.test"
    assert settings.host_is_trusted(settings.healthcheck_host)


@pytest.mark.parametrize(
    "healthcheck_host",
    ("*.example.test", "untrusted.invalid", "audio.example.test:99999"),
)
def test_invalid_or_untrusted_healthcheck_hosts_fail_startup(
    monkeypatch, healthcheck_host
):
    for name, value in PRODUCTION.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("VMA_HEALTHCHECK_HOST", healthcheck_host)

    with pytest.raises(RuntimeError, match="VMA_HEALTHCHECK_HOST"):
        load_deployment_settings()


@pytest.mark.parametrize("path", SESSION_MULTIPART_ROUTES)
def test_session_multipart_routes_reject_hostile_origin_before_parsing(
    monkeypatch, path
):
    with _production_client(monkeypatch) as client:
        response = client.post(
            path,
            content=b"not multipart",
            headers={
                "Content-Type": "application/octet-stream",
                "Origin": "https://hostile.example",
            },
        )
        assert app.state.resource_governor.requests == {}

    assert response.status_code == 403
    assert response.json() == {"detail": "request origin is not allowed"}


@pytest.mark.parametrize("path", SESSION_MULTIPART_ROUTES)
def test_permitted_session_multipart_requests_reach_existing_validation(
    monkeypatch, path
):
    with _production_client(monkeypatch) as client:
        response = client.post(
            path,
            content=b"not multipart",
            headers={
                "Content-Type": "application/octet-stream",
                "Origin": "https://audio.example.test",
            },
        )

    assert response.status_code == 422


@pytest.mark.parametrize("path", ALL_MULTIPART_ROUTES)
@pytest.mark.parametrize(
    "origin",
    (
        "http://[",
        "https://bad host",
        "https://:443",
        "https://audio.example.test:99999",
    ),
)
def test_malformed_origins_fail_before_multipart_parsing(monkeypatch, path, origin):
    with _production_client(monkeypatch) as client:
        response = client.post(
            path,
            content=b"not multipart",
            headers={
                "Content-Type": "application/octet-stream",
                "Origin": origin,
            },
        )
        assert app.state.resource_governor.requests == {}

    assert response.status_code == 403
    assert response.json() == {"detail": "request origin is not allowed"}


@pytest.mark.parametrize("path", STATELESS_MULTIPART_ROUTES)
@pytest.mark.parametrize(
    "headers",
    (
        {"Origin": "https://hostile.example"},
        {
            "Origin": "https://audio.example.test",
            "Sec-Fetch-Site": "cross-site",
        },
    ),
)
def test_production_rejects_cross_site_stateless_multipart_before_body_limits(
    monkeypatch, path, headers
):
    with _production_client(monkeypatch) as client:
        response = client.post(
            path,
            content=b"x",
            headers={**headers, "Content-Length": "9999999999"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "request origin is not allowed"}


@pytest.mark.parametrize("path", STATELESS_MULTIPART_ROUTES)
@pytest.mark.parametrize(
    "headers",
    (
        {},
        {"Origin": "https://audio.example.test"},
    ),
)
def test_production_allows_non_browser_and_same_origin_stateless_clients(
    monkeypatch, path, headers
):
    with _production_client(monkeypatch) as client:
        response = client.post(
            path,
            content=b"x",
            headers={**headers, "Content-Length": "9999999999"},
        )

    assert response.status_code == 413
    assert response.json() == {"detail": "request body is too large"}


def test_production_disables_interactive_docs_but_keeps_openapi(monkeypatch):
    with _production_client(monkeypatch) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize("environment", ("development", "test"))
def test_non_production_keeps_interactive_docs(monkeypatch, environment):
    monkeypatch.setenv("VMA_ENVIRONMENT", environment)
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200


def test_trusted_host_and_security_headers(monkeypatch):
    with _production_client(monkeypatch) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.headers["content-security-policy"].startswith("default-src 'self'")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["strict-transport-security"].startswith("max-age=")
        assert response.headers["x-request-id"]
        denied = client.get("http://hostile.example/api/health")
        assert denied.status_code == 400
        assert denied.json() == {"detail": "invalid host header"}


def test_untrusted_forwarding_headers_cannot_change_origin_or_cookie_policy(monkeypatch):
    with _production_client(monkeypatch) as client:
        response = client.post(
            "/api/demo",
            headers={
                "Origin": "http://audio.example.test",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "audio.example.test",
                "X-Forwarded-For": "203.0.113.8",
            },
        )
        assert response.status_code == 403

        accepted = client.post("/api/demo", headers={"Origin": "https://audio.example.test"})
        assert accepted.status_code == 200
        assert "secure" in accepted.headers["set-cookie"].lower()


def test_explicit_trusted_proxy_supplies_scheme_host_and_client(monkeypatch):
    for name, value in {
        **PRODUCTION,
        "VMA_TRUSTED_PROXIES": "127.0.0.1/32",
    }.items():
        monkeypatch.setenv(name, value)
    with TestClient(
        app,
        base_url="http://internal.invalid",
        client=("127.0.0.1", 50000),
    ) as client:
        response = client.post(
            "/api/demo",
            headers={
                "Origin": "https://audio.example.test",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "audio.example.test",
                "X-Forwarded-For": "198.51.100.42",
            },
        )
        assert response.status_code == 200
        assert "secure" in response.headers["set-cookie"].lower()
        assert ("198.51.100.42", "demo") in app.state.resource_governor.requests


def test_production_csrf_requires_configured_https_origin(monkeypatch):
    with _production_client(monkeypatch) as client:
        assert client.post("/api/demo").status_code == 403
        assert client.post("/api/demo", headers={"Origin": "https://evil.test"}).status_code == 403
        assert client.post(
            "/api/demo", headers={"Origin": "https://audio.example.test"}
        ).status_code == 200


def test_no_credentialed_cors_is_enabled(monkeypatch):
    with _production_client(monkeypatch) as client:
        response = client.options(
            "/api/demo",
            headers={
                "Origin": "https://evil.test",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code in {400, 405}
        assert "access-control-allow-origin" not in response.headers
        assert "access-control-allow-credentials" not in response.headers


def test_liveness_and_readiness_are_distinct(monkeypatch):
    monkeypatch.setenv("VMA_ENVIRONMENT", "test")
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/ready").json() == {"status": "ready"}


def test_configured_temp_root_confines_application_storage(monkeypatch, tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    monkeypatch.setenv("VMA_ENVIRONMENT", "test")
    monkeypatch.setenv("VMA_TEMP_ROOT", str(root))
    with TestClient(app) as client:
        assert client.get("/api/ready").status_code == 200
        assert app.state.temp_root.parent == root.resolve()
        assert app.state.storage.parent == app.state.temp_root
        assert app.state.work_storage.parent == app.state.temp_root


def test_request_id_is_bounded_and_not_copied_when_malformed(monkeypatch):
    monkeypatch.setenv("VMA_ENVIRONMENT", "test")
    with TestClient(app) as client:
        accepted = client.get("/api/health", headers={"X-Request-ID": "trace_123456"})
        malformed = "x" * 100
        rejected = client.get("/api/health", headers={"X-Request-ID": malformed})
        assert accepted.headers["x-request-id"] == "trace_123456"
        assert rejected.headers["x-request-id"] != malformed
        assert len(rejected.headers["x-request-id"]) == 24
