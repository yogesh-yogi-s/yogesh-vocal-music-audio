"""Smoke-test the actual frozen backend, including its bundled demo and UI."""

from __future__ import annotations

import json
import http.cookiejar
import io
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave


ROOT = Path(__file__).resolve().parent
EXECUTABLE = ROOT / "dist" / "backend" / "VMA-Backend" / "VMA-Backend.exe"


def post_files(opener, origin: str, route: str, files: dict[str, tuple[str, bytes, str]]):
    boundary = uuid.uuid4().hex
    body = bytearray()
    for field, (filename, payload, media_type) in files.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: {media_type}\r\n\r\n".encode()
        )
        body.extend(payload)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        origin + route, data=bytes(body), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return opener.open(request, timeout=15)


def pcm_wav() -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(bytes(48000))
    return stream.getvalue()


def main() -> None:
    if not EXECUTABLE.is_file():
        raise RuntimeError(f"Missing frozen backend: {EXECUTABLE}")
    child = subprocess.Popen(
        [str(EXECUTABLE)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    lines: queue.Queue[str] = queue.Queue()

    def read_stdout() -> None:
        assert child.stdout is not None
        for line in child.stdout:
            lines.put(line)

    threading.Thread(target=read_stdout, daemon=True).start()
    try:
        try:
            handshake = lines.get(timeout=30).strip()
        except queue.Empty as exc:
            raise RuntimeError("Frozen backend did not send a port handshake") from exc
        match = re.fullmatch(r"VMA_PORT=(\d+)", handshake)
        if not match:
            raise RuntimeError(f"Invalid frozen backend handshake: {handshake!r}")
        origin = f"http://127.0.0.1:{int(match.group(1))}"
        for _ in range(100):
            if child.poll() is not None:
                raise RuntimeError(f"Frozen backend exited: {child.stderr.read()}")
            try:
                with urllib.request.urlopen(origin + "/api/ready", timeout=1) as response:
                    if json.load(response).get("status") == "ready":
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(0.2)
        else:
            raise RuntimeError("Frozen backend did not become ready")
        with urllib.request.urlopen(origin, timeout=5) as response:
            if b"VMA" not in response.read():
                raise RuntimeError("Frontend HTML is missing from frozen backend")
        with urllib.request.urlopen(origin + "/js/app.js", timeout=5) as response:
            if b"decodeAudioData" not in response.read():
                raise RuntimeError("Frontend JavaScript is missing from frozen backend")
        request = urllib.request.Request(origin + "/api/demo", method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            if json.load(response).get("version") != 1:
                raise RuntimeError("Bundled VMA demo did not open")
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        wav = pcm_wav()
        with post_files(opener, origin, "/api/create", {
            "vocal": ("vocal.wav", wav, "audio/wav"),
            "music": ("music.wav", wav, "audio/wav"),
        }) as response:
            if response.headers.get("X-VMA-Version") != "1":
                raise RuntimeError("Frozen backend did not create V1")
            v1_bytes = response.read()
        with post_files(opener, origin, "/api/open", {
            "file": ("song.vma", v1_bytes, "application/vnd.vma")
        }) as response:
            opened_v1 = json.load(response)
        if opened_v1.get("version") != 1:
            raise RuntimeError("Frozen backend did not open V1")
        with opener.open(
            origin + f"/api/vma/{opened_v1['session_id']}/extract/vocal", timeout=10
        ) as response:
            if response.read() != wav:
                raise RuntimeError("Frozen backend changed canonical V1 WAV extraction")

        mp3_bytes = b"ID3\x03\x00\x00\x00\x00\x00\x21" + bytes(range(64))
        with post_files(opener, origin, "/api/create", {
            "vocal": ("vocal.wav", wav, "audio/wav"),
            "music": ("music.mp3", mp3_bytes, "audio/mpeg"),
        }) as response:
            if response.headers.get("X-VMA-Version") != "2":
                raise RuntimeError("Frozen backend did not create V2")
            v2_bytes = response.read()
        with post_files(opener, origin, "/api/open", {
            "file": ("song.vma", v2_bytes, "application/vnd.vma")
        }) as response:
            opened_v2 = json.load(response)
        if opened_v2.get("version") != 2:
            raise RuntimeError("Frozen backend did not open V2")
        with opener.open(
            origin + f"/api/vma/{opened_v2['session_id']}/extract-stream/2", timeout=10
        ) as response:
            if response.read() != mp3_bytes:
                raise RuntimeError("Frozen backend changed V2 payload bytes")
        print("Frozen backend: ready, frontend, demo, V1 and V2 passed")
    finally:
        if child.poll() is None:
            assert child.stdin is not None
            child.stdin.write("shutdown\n")
            child.stdin.flush()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


if __name__ == "__main__":
    main()
