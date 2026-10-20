"""Build the standalone Windows x64 VMA folder and ZIP."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


DESKTOP = Path(__file__).resolve().parent
ROOT = DESKTOP.parents[1]
BUILD_PYTHON = DESKTOP / ".venv-build" / "Scripts" / "python.exe"


def run(*command: str, cwd: Path = DESKTOP) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    if os.name != "nt" or sys.version_info[:2] != (3, 13):
        raise RuntimeError("Build on Windows with Python 3.13.")
    if not BUILD_PYTHON.is_file():
        run(sys.executable, "-m", "venv", str(BUILD_PYTHON.parents[1]))
    run(str(BUILD_PYTHON), "-m", "pip", "install", "-r", str(ROOT / "requirements.lock"))
    run(str(BUILD_PYTHON), "-m", "pip", "install", "pyinstaller==6.22.3")
    run("npm.cmd", "ci")
    run(
        str(BUILD_PYTHON), "-m", "PyInstaller", "--noconfirm",
        "--distpath", str(DESKTOP / "dist" / "backend"),
        "--workpath", str(DESKTOP / "build"),
        str(DESKTOP / "backend.spec"),
    )
    run(str(BUILD_PYTHON), str(DESKTOP / "verify_backend.py"))
    run("npm.cmd", "run", "package")
    packaged = DESKTOP / "dist" / "app" / "VMA-win32-x64"
    if not (packaged / "VMA.exe").is_file():
        raise RuntimeError("Packaged VMA.exe is missing.")
    subprocess.run(
        [str(packaged / "VMA.exe"), "--smoke-test"],
        cwd=DESKTOP,
        check=True,
        timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    zip_base = DESKTOP / "dist" / "VMA-windows-x64"
    archive = shutil.make_archive(
        str(zip_base), "zip", root_dir=packaged.parent, base_dir=packaged.name
    )
    run(str(BUILD_PYTHON), str(DESKTOP / "verify_distribution.py"))
    print(f"Build complete: {archive}")


if __name__ == "__main__":
    main()
