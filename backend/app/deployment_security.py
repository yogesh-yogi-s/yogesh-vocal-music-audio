"""Production-facing host, proxy, origin, header, and logging controls."""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


logger = logging.getLogger("vma.http")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_HOST = re.compile(r"^(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(?::[0-9]{1,5})?$")
_STATELESS_MULTIPART_PATHS = {
    "/api/vma/create",
    "/api/vma/validate",
    "/api/vma/info",
    "/api/vma/extract/vocal",
    "/api/vma/extract/music",
    "/api/vma/extract/all",
}
_SESSION_MULTIPART_PATHS = {"/api/create", "/api/open"}
_PRODUCTION_DISABLED_DOC_PATHS = {"/docs", "/redoc"}

CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self'",
        "img-src 'self' data:",
        "media-src 'self' blob:",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)


def _csv(name: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, "").split(",") if value.strip())


def _canonical_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except (UnicodeError, ValueError) as exc:
        raise RuntimeError("origin must be a valid absolute HTTP(S) origin") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or hostname is None
        or not _HOST.fullmatch(parsed.netloc)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("VMA_ALLOWED_ORIGINS entries must be absolute HTTP(S) origins")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


@dataclass(frozen=True)
class DeploymentSettings:
    environment: str
    trusted_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    trusted_proxy_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    temp_base: Path | None
    healthcheck_host: str

    @property
    def production(self) -> bool:
        return self.environment == "production"

    def peer_is_trusted_proxy(self, peer: str | None) -> bool:
        if not peer:
            return False
        try:
            address = ipaddress.ip_address(peer)
        except ValueError:
            return False
        return any(address in network for network in self.trusted_proxy_networks)

    def host_is_trusted(self, host: str) -> bool:
        hostname = _hostname_without_port(host)
        for pattern in self.trusted_hosts:
            normalized = pattern.lower().rstrip(".")
            if normalized == "*":
                return True
            if normalized.startswith("*."):
                suffix = normalized[1:]
                if hostname.endswith(suffix) and hostname != suffix[1:]:
                    return True
            elif hostname == normalized:
                return True
        return False


def load_deployment_settings() -> DeploymentSettings:
    raw_environment = os.getenv("VMA_ENVIRONMENT")
    if raw_environment is None or not raw_environment.strip():
        raise RuntimeError(
            "VMA_ENVIRONMENT must be explicitly set to development, production, or test"
        )
    environment = raw_environment.strip().lower()
    if environment not in {"development", "production", "test"}:
        raise RuntimeError("VMA_ENVIRONMENT must be development, production, or test")

    configured_hosts = _csv("VMA_TRUSTED_HOSTS")
    trusted_hosts = configured_hosts or (("*",) if environment != "production" else ())
    if environment == "production" and (not trusted_hosts or "*" in trusted_hosts):
        raise RuntimeError("production requires explicit VMA_TRUSTED_HOSTS without '*'")

    origins = tuple(_canonical_origin(value) for value in _csv("VMA_ALLOWED_ORIGINS"))
    if environment == "production":
        if not origins:
            raise RuntimeError("production requires explicit VMA_ALLOWED_ORIGINS")
        if any(not origin.startswith("https://") for origin in origins):
            raise RuntimeError("production VMA_ALLOWED_ORIGINS must use HTTPS")

    networks = []
    for value in _csv("VMA_TRUSTED_PROXIES"):
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError as exc:
            raise RuntimeError(f"invalid VMA_TRUSTED_PROXIES entry: {value}") from exc

    raw_temp = os.getenv("VMA_TEMP_ROOT", "").strip()
    temp_base = Path(raw_temp).expanduser().resolve() if raw_temp else None
    healthcheck_host = os.getenv("VMA_HEALTHCHECK_HOST", "").strip()
    if environment == "production" and not healthcheck_host:
        raise RuntimeError("production requires explicit VMA_HEALTHCHECK_HOST")
    healthcheck_host = healthcheck_host or "127.0.0.1"
    try:
        parsed_healthcheck = urlsplit(f"//{healthcheck_host}")
        parsed_healthcheck.port
    except (UnicodeError, ValueError) as exc:
        raise RuntimeError("VMA_HEALTHCHECK_HOST must be an exact valid hostname") from exc
    if (
        "*" in healthcheck_host
        or not _HOST.fullmatch(healthcheck_host)
        or parsed_healthcheck.hostname is None
    ):
        raise RuntimeError("VMA_HEALTHCHECK_HOST must be an exact valid hostname")
    settings = DeploymentSettings(
        environment,
        trusted_hosts,
        origins,
        tuple(networks),
        temp_base,
        healthcheck_host.lower(),
    )
    if not settings.host_is_trusted(settings.healthcheck_host):
        raise RuntimeError("VMA_HEALTHCHECK_HOST must match VMA_TRUSTED_HOSTS")
    return settings


def _hostname_without_port(host: str) -> str:
    value = host.strip().lower().rstrip(".")
    if value.startswith("["):
        closing = value.find("]")
        return value[1:closing] if closing != -1 else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _header_map(scope) -> dict[bytes, bytes]:
    return {name.lower(): value for name, value in scope.get("headers", ())}


def _forwarded_client(value: str, settings: DeploymentSettings, peer: str) -> str:
    candidates = [item.strip() for item in value.split(",") if item.strip()]
    current = peer
    for candidate in reversed(candidates):
        if not settings.peer_is_trusted_proxy(current):
            break
        try:
            current = str(ipaddress.ip_address(candidate))
        except ValueError:
            break
    return current


def _apply_forwarded_headers(scope, settings: DeploymentSettings) -> None:
    headers = _header_map(scope)
    peer = scope.get("client", (None, 0))[0]
    trusted = settings.peer_is_trusted_proxy(peer)
    forwarded_proto = headers.get(b"x-forwarded-proto")
    forwarded_host = headers.get(b"x-forwarded-host")
    forwarded_for = headers.get(b"x-forwarded-for")

    scope["headers"] = [
        (name, value)
        for name, value in scope.get("headers", ())
        if name.lower() not in {b"x-forwarded-proto", b"x-forwarded-host", b"x-forwarded-for"}
    ]
    if not trusted:
        return

    if forwarded_proto:
        scheme = forwarded_proto.decode("latin-1").split(",", 1)[0].strip().lower()
        if scheme in {"http", "https"}:
            scope["scheme"] = scheme
    if forwarded_host:
        host = forwarded_host.decode("latin-1").split(",", 1)[0].strip()
        if _HOST.fullmatch(host):
            scope["headers"] = [
                (name, value) for name, value in scope["headers"] if name.lower() != b"host"
            ]
            scope["headers"].append((b"host", host.encode("latin-1")))
    if forwarded_for and peer:
        client = _forwarded_client(forwarded_for.decode("latin-1"), settings, peer)
        scope["client"] = (client, scope.get("client", (None, 0))[1])


def _security_headers(request_id: str, production: bool) -> list[tuple[bytes, bytes]]:
    headers = [
        (b"content-security-policy", CONTENT_SECURITY_POLICY.encode("ascii")),
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
        (b"x-request-id", request_id.encode("ascii")),
    ]
    if production:
        headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
    return headers


async def _reject(send, status: int, detail: str, request_id: str, production: bool) -> None:
    body = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    headers.extend(_security_headers(request_id, production))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _stateless_browser_request_allowed(
    scope, headers: dict[bytes, bytes], settings: DeploymentSettings
) -> bool:
    if scope["method"] != "POST" or scope["path"] not in (
        _STATELESS_MULTIPART_PATHS | _SESSION_MULTIPART_PATHS
    ):
        return True
    if headers.get(b"sec-fetch-site", b"").decode("latin-1").lower() == "cross-site":
        return False
    raw_origin = headers.get(b"origin")
    if raw_origin is None:
        return not (
            settings.production and scope["path"] in _SESSION_MULTIPART_PATHS
        )
    try:
        origin = _canonical_origin(raw_origin.decode("latin-1"))
    except RuntimeError:
        return False
    host = headers.get(b"host", b"").decode("latin-1").lower()
    expected = f"{scope.get('scheme', 'http').lower()}://{host}"
    allowed = settings.allowed_origins or (expected,)
    return origin in allowed


class DeploymentSecurityMiddleware:
    """Fail-closed deployment boundary and common response protections."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        application = scope["app"]
        settings = getattr(application.state, "deployment_settings", None)
        if settings is None:
            settings = load_deployment_settings()
        _apply_forwarded_headers(scope, settings)
        headers = _header_map(scope)
        supplied_request_id = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = supplied_request_id if _REQUEST_ID.fullmatch(supplied_request_id) else secrets.token_hex(12)
        host = headers.get(b"host", b"").decode("latin-1")
        started = time.monotonic()
        status = 500

        if not host or not _HOST.fullmatch(host) or not settings.host_is_trusted(host):
            await _reject(send, 400, "invalid host header", request_id, settings.production)
            logger.warning("request_complete request_id=%s method=%s category=invalid-host status=400", request_id, scope["method"])
            return
        if settings.production and scope["path"] in _PRODUCTION_DISABLED_DOC_PATHS:
            await _reject(send, 404, "not found", request_id, settings.production)
            return
        if not _stateless_browser_request_allowed(scope, headers, settings):
            await _reject(
                send, 403, "request origin is not allowed", request_id, settings.production
            )
            return

        async def protected_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                existing = {name.lower() for name, _ in message.get("headers", ())}
                message.setdefault("headers", []).extend(
                    header for header in _security_headers(request_id, settings.production)
                    if header[0] not in existing
                )
            await send(message)

        try:
            await self.app(scope, receive, protected_send)
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                "request_complete request_id=%s method=%s category=%s status=%s duration_ms=%s",
                request_id, scope["method"], _request_category(scope["path"]), status, elapsed_ms,
            )


def _request_category(path: str) -> str:
    if path in {"/api/health", "/api/ready"}:
        return path.rsplit("/", 1)[-1]
    if path == "/api/demo":
        return "demo"
    if path in {"/api/create", "/api/vma/create"}:
        return "create"
    if path == "/api/open":
        return "open"
    if path.startswith("/api/vma/"):
        return "session"
    if path.startswith("/api/"):
        return "api"
    return "frontend"
