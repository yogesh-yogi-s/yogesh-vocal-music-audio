"""Extract the ZIP and launch its app without developer runtimes on PATH."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import zipfile


DIST = Path(__file__).resolve().parent / "dist"
ARCHIVE = DIST / "VMA-windows-x64.zip"


def main() -> None:
    if not ARCHIVE.is_file():
        raise RuntimeError(f"Missing distribution: {ARCHIVE}")
    with tempfile.TemporaryDirectory(prefix="vma-zip-check-", dir=DIST) as temporary:
        target = Path(temporary).resolve()
        if not target.is_relative_to(DIST.resolve()):
            raise RuntimeError("Distribution test directory escaped dist")
        with zipfile.ZipFile(ARCHIVE) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise RuntimeError(f"Corrupt ZIP member: {bad_member}")
            for member in archive.namelist():
                if not (target / member).resolve().is_relative_to(target):
                    raise RuntimeError("Unsafe ZIP member path")
            archive.extractall(target)
        executable = target / "VMA-win32-x64" / "VMA.exe"
        if not executable.is_file():
            raise RuntimeError("VMA.exe is missing from the extracted ZIP")
        environment = os.environ.copy()
        windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        environment["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
        for key in ("PYTHONPATH", "NODE_PATH", "ELECTRON_RUN_AS_NODE"):
            environment.pop(key, None)
        subprocess.run(
            [str(executable), "--smoke-test"],
            cwd=target,
            env=environment,
            check=True,
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    print("Extracted ZIP: packaged UI and demo passed without Python/Node on PATH")


if __name__ == "__main__":
    main()
