"""Install the locked app dependencies and run VMA on this computer only."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
VENV_PYTHON = VENV / "Scripts" / "python.exe" if os.name == "nt" else VENV / "bin" / "python"
LOCK = ROOT / "requirements.lock"
STAMP = VENV / ".vma-requirements.sha256"
URL = "http://127.0.0.1:8000"


def prepare_environment() -> None:
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("Install Python 3.13 and launch VMA with it.")
    if not VENV_PYTHON.is_file():
        print("Creating the local Python environment...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], cwd=ROOT, check=True)
    installed_lock = hashlib.sha256(LOCK.read_bytes()).hexdigest()
    if not STAMP.is_file() or STAMP.read_text(encoding="ascii").strip() != installed_lock:
        print("Installing the pinned VMA dependencies (internet is needed for the first run)...")
        subprocess.run(
            [str(VENV_PYTHON), "-m", "pip", "install", "-r", str(LOCK)],
            cwd=ROOT,
            check=True,
        )
        STAMP.write_text(installed_lock + "\n", encoding="ascii")


def open_browser_when_ready() -> None:
    for _ in range(100):
        try:
            with urllib.request.urlopen(URL + "/api/ready", timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(URL)
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)


def serve() -> None:
    import uvicorn

    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    print(f"VMA is available only on this computer: {URL}")
    print("Press Ctrl+C to stop VMA. Your original audio files stay on your computer.")
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, proxy_headers=False, workers=1)


def main() -> None:
    os.chdir(ROOT)
    if "--serve" in sys.argv:
        serve()
        return
    prepare_environment()
    local_env = os.environ.copy()
    local_env["VMA_ENVIRONMENT"] = "development"
    local_env["VMA_TRUSTED_HOSTS"] = "127.0.0.1,localhost"
    local_env["VMA_ALLOWED_ORIGINS"] = URL
    local_env["VMA_HEALTHCHECK_HOST"] = "127.0.0.1"
    subprocess.run([str(VENV_PYTHON), str(Path(__file__).resolve()), "--serve"], cwd=ROOT, env=local_env, check=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"VMA startup failed: {exc}", file=sys.stderr)
        sys.exit(1)
