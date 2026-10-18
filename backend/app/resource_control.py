"""Single-process request, rate, concurrency, and temporary-storage controls."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backend.app import vma_service


MIB = 1024 * 1024
GIB = 1024 * MIB


def _positive_environment_integer(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


MULTIPART_OVERHEAD_BYTES = _positive_environment_integer(
    "VMA_MULTIPART_OVERHEAD_BYTES", 2 * MIB
)
DEMO_REQUEST_BYTES = _positive_environment_integer("VMA_DEMO_REQUEST_BYTES", 64 * 1024)
MAX_PROCESS_TEMP_BYTES = _positive_environment_integer("VMA_MAX_PROCESS_TEMP_BYTES", 8 * GIB)
MAX_ACTIVE_EXPENSIVE_REQUESTS = _positive_environment_integer(
    "VMA_MAX_ACTIVE_EXPENSIVE_REQUESTS", 3
)
MAX_ACTIVE_SESSION_OPERATIONS = _positive_environment_integer(
    "VMA_MAX_ACTIVE_SESSION_OPERATIONS", 2
)
MAX_PROCESS_SESSIONS = _positive_environment_integer("VMA_MAX_PROCESS_SESSIONS", 128)
MAX_BROWSER_SESSIONS = _positive_environment_integer("VMA_MAX_BROWSER_SESSIONS", 16)
RATE_WINDOW_SECONDS = _positive_environment_integer("VMA_RATE_WINDOW_SECONDS", 60)


def _rate(name: str, default: int) -> int:
    return _positive_environment_integer(f"VMA_RATE_{name.upper()}_PER_WINDOW", default)


DEFAULT_RATE_LIMITS = {
    "demo": _rate("demo", 12),
    "create": _rate("create", 10),
    "open": _rate("open", 20),
    "inspect": _rate("inspect", 120),
    "extract": _rate("extract", 60),
    "validate": _rate("validate", 30),
}


@dataclass(frozen=True)
class RequestPolicy:
    category: str
    body_limit: int | None
    storage_reservation: int
    expensive: bool = True


_SINGLE_UPLOAD_ROUTES = {
    "/api/open": "open",
    "/api/vma/validate": "validate",
    "/api/vma/info": "validate",
    "/api/vma/extract/vocal": "extract",
    "/api/vma/extract/music": "extract",
    "/api/vma/extract/all": "extract",
}


def request_policy(method: str, path: str) -> RequestPolicy | None:
    per_file = vma_service.MAX_UPLOAD_BYTES
    session_container_limit = 2 * per_file + MULTIPART_OVERHEAD_BYTES
    if method == "POST" and path in {"/api/create", "/api/vma/create"}:
        body_limit = 2 * per_file + MULTIPART_OVERHEAD_BYTES
        return RequestPolicy("create", body_limit, 2 * body_limit)
    if method == "POST" and path in _SINGLE_UPLOAD_ROUTES:
        body_limit = per_file + MULTIPART_OVERHEAD_BYTES
        category = _SINGLE_UPLOAD_ROUTES[path]
        multiplier = 3 if path == "/api/vma/extract/all" else (2 if category == "extract" else 1)
        return RequestPolicy(category, body_limit, multiplier * body_limit)
    if method == "POST" and path == "/api/demo":
        return RequestPolicy("demo", DEMO_REQUEST_BYTES, MIB)
    if method == "GET" and path.startswith("/api/vma/"):
        if "/extract-stream/" in path:
            # One V2 payload can occupy the entire validated browser-session
            # container. Session creation caps that container at two uploads
            # plus multipart overhead; extraction copies exactly one payload.
            return RequestPolicy("extract", None, session_container_limit)
        if any(part in path for part in ("/stream/", "/extract/", "/extract-all")):
            return RequestPolicy("extract", None, 2 * session_container_limit)
        return RequestPolicy("inspect", None, 0)
    return None


def directory_size(root: Path) -> int:
    total = 0
    try:
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


class ResourceGovernor:
    """In-memory controls for the documented single-process deployment model."""

    def __init__(self, temp_root: Path):
        self.temp_root = temp_root
        self.lock = threading.Lock()
        self.active_expensive = 0
        self.reserved_temp_bytes = 0
        self.rate_window_seconds = RATE_WINDOW_SECONDS
        self.rate_limits = dict(DEFAULT_RATE_LIMITS)
        self.requests: dict[tuple[str, str], deque[float]] = {}

    def admit(
        self,
        client: str,
        policy: RequestPolicy,
        actual_temp_bytes: int,
    ) -> tuple[str | None, int]:
        now = time.monotonic()
        with self.lock:
            key = (client, policy.category)
            timestamps = self.requests.setdefault(key, deque())
            cutoff = now - self.rate_window_seconds
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            rate_limit = self.rate_limits[policy.category]
            if len(timestamps) >= rate_limit:
                retry_after = max(1, int(self.rate_window_seconds - (now - timestamps[0]) + 0.999))
                return "rate", retry_after
            timestamps.append(now)
            if policy.expensive and self.active_expensive >= MAX_ACTIVE_EXPENSIVE_REQUESTS:
                return "busy", 1
            if (
                policy.storage_reservation
                and
                actual_temp_bytes
                + self.reserved_temp_bytes
                + policy.storage_reservation
                > MAX_PROCESS_TEMP_BYTES
            ):
                return "storage", 1
            if policy.expensive:
                self.active_expensive += 1
            self.reserved_temp_bytes += policy.storage_reservation
            return None, 0

    def release(self, policy: RequestPolicy) -> None:
        with self.lock:
            if policy.expensive:
                self.active_expensive = max(0, self.active_expensive - 1)
            self.reserved_temp_bytes = max(
                0, self.reserved_temp_bytes - policy.storage_reservation
            )

    def prune_rates(self) -> None:
        now = time.monotonic()
        with self.lock:
            cutoff = now - self.rate_window_seconds
            for key, timestamps in list(self.requests.items()):
                while timestamps and timestamps[0] <= cutoff:
                    timestamps.popleft()
                if not timestamps:
                    self.requests.pop(key, None)


async def _json_response(send: Callable, status: int, detail: str, retry_after: int | None = None):
    body = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if retry_after is not None:
        headers.append((b"retry-after", str(retry_after).encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class ResourceProtectionMiddleware:
    """Reject abusive requests before FastAPI performs multipart parsing."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        policy = request_policy(scope["method"], scope["path"])
        if policy is None:
            await self.app(scope, receive, send)
            return

        content_length = None
        for name, value in scope.get("headers", ()):
            if name.lower() == b"content-length":
                try:
                    content_length = int(value)
                except ValueError:
                    await _json_response(send, 400, "invalid Content-Length header")
                    return
                break
        if policy.body_limit is not None and content_length is not None:
            if content_length < 0:
                await _json_response(send, 400, "invalid Content-Length header")
                return
            if content_length > policy.body_limit:
                await _json_response(send, 413, "request body is too large")
                return

        if policy.category == "demo" and content_length is None:
            consumed = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                if message["type"] != "http.request":
                    continue
                consumed += len(message.get("body", b""))
                if consumed > policy.body_limit:
                    await _json_response(send, 413, "request body is too large")
                    return
                if not message.get("more_body", False):
                    break

            async def receive_empty_body():
                return {"type": "http.request", "body": b"", "more_body": False}

            receive = receive_empty_body

        application = scope["app"]
        governor: ResourceGovernor = application.state.resource_governor
        actual_size = (
            await asyncio.to_thread(directory_size, application.state.temp_root)
            if policy.storage_reservation
            else 0
        )
        client = scope.get("client")
        client_key = str(client[0]) if client else "unknown"
        rejection, retry_after = governor.admit(client_key, policy, actual_size)
        if rejection in {"rate", "busy"}:
            detail = "rate limit exceeded" if rejection == "rate" else "server is busy"
            await _json_response(send, 429, detail, retry_after)
            return
        if rejection == "storage":
            await _json_response(send, 507, "temporary storage capacity is unavailable", retry_after)
            return

        consumed = 0
        body_limit_exceeded = False
        replacement_body_sent = False

        async def limited_receive():
            nonlocal consumed, body_limit_exceeded
            message = await receive()
            if message["type"] == "http.request" and policy.body_limit is not None:
                consumed += len(message.get("body", b""))
                if consumed > policy.body_limit:
                    body_limit_exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def tracked_send(message):
            nonlocal replacement_body_sent
            if message["type"] == "http.response.start":
                if body_limit_exceeded:
                    body = b'{"detail":"request body is too large"}'
                    message = {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
            elif message["type"] == "http.response.body" and body_limit_exceeded:
                if replacement_body_sent:
                    return
                replacement_body_sent = True
                message = {
                    "type": "http.response.body",
                    "body": b'{"detail":"request body is too large"}',
                }
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        finally:
            governor.release(policy)
