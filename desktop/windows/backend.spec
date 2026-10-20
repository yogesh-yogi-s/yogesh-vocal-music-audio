"""PyInstaller spec: keep application assets at their existing relative paths."""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]
ENTRY = ROOT / "desktop" / "windows" / "backend_main.py"

a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "frontend"), "frontend"),
        (str(ROOT / "backend" / "app" / "assets"), "backend/app/assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "httpx"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VMA-Backend",
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VMA-Backend",
)
