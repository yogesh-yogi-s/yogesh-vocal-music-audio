"""Check a deployed HTTPS VMA instance using only the Python standard library."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
import wave
from http.cookiejar import CookieJar


def wav_bytes(sample: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(sample.to_bytes(2, "little", signed=True) * 80)
    return output.getvalue()


def multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "vma-smoke-" + secrets.token_hex(16)
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, (filename, content, media_type) in files.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f'Content-Type: {media_type}\r\n\r\n'.encode() + content + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Base URL, for example https://audio.example.com")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment:
        parser.error("url must be a bare HTTPS origin")

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def request(path: str, data: bytes | None = None, headers: dict[str, str] | None = None):
        req = urllib.request.Request(base + path, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
        try:
            with opener.open(req, timeout=120) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    for path, expected in (("/api/health", "ok"), ("/api/ready", "ready")):
        status, _, body = request(path)
        assert status == 200 and json.loads(body) == {"status": expected}, (path, status, body[:200])

    status, _, _ = request("/api/health", headers={"Host": "hostile.example"})
    assert 400 <= status < 500, f"hostile Host was not rejected: HTTP {status}"

    status, headers, body = request("/api/demo", b"", {"Origin": base})
    assert status == 200 and json.loads(body).get("demo") is True, (status, body[:200])
    cookie = " ".join(headers.get_all("Set-Cookie", [])).lower()
    assert "secure" in cookie and "httponly" in cookie, "demo cookie lacks Secure/HttpOnly"

    vocal, music = wav_bytes(1000), wav_bytes(-1000)
    for version in (1, 2):
        upload, content_type = multipart(
            {"title": "Live smoke", "version": str(version)},
            {"vocal": ("vocal.wav", vocal, "audio/wav"), "music": ("music.wav", music, "audio/wav")},
        )
        status, headers, container = request(
            "/api/vma/create", upload, {"Content-Type": content_type, "Origin": base}
        )
        assert status == 200 and headers.get("X-VMA-Version") == str(version), (version, status, container[:200])
        if version == 1:
            upload, content_type = multipart({}, {"file": ("song.vma", container, "application/vnd.vma")})
            status, _, extracted = request(
                "/api/vma/extract/vocal", upload, {"Content-Type": content_type, "Origin": base}
            )
            assert status == 200, (status, extracted[:200])
            with wave.open(io.BytesIO(extracted), "rb") as output:
                with wave.open(io.BytesIO(vocal), "rb") as original:
                    assert output.readframes(output.getnframes()) == original.readframes(original.getnframes())
        else:
            upload, content_type = multipart({}, {"file": ("song.vma", container, "application/vnd.vma")})
            status, _, body = request("/api/open", upload, {"Content-Type": content_type, "Origin": base})
            assert status == 200, (status, body[:200])
            session = json.loads(body)
            assert session["version"] == 2
            session_id = urllib.parse.quote(session["session_id"], safe="")
            for stream_id, original in ((1, vocal), (2, music)):
                status, _, extracted = request(f"/api/vma/{session_id}/extract-stream/{stream_id}")
                assert status == 200, (stream_id, status, extracted[:200])
                assert hashlib.sha256(extracted).digest() == hashlib.sha256(original).digest(), stream_id

    print("PASS: HTTPS health/readiness, hostile Host, secure cookie, demo, V1 PCM and V2 SHA-256 round trips")


if __name__ == "__main__":
    main()
