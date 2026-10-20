# VMA Windows Desktop

This separate project packages the working repository backend and frontend as a Windows x64 desktop application. It does not implement another container codec or parser. The app runs a bundled FastAPI executable on a dynamically selected loopback port and displays the existing Web Audio interface in bundled Chromium.

## Design documents

1. [Product requirements](docs/PRD.md)
2. [Technical requirements](docs/TRD.md)
3. [App flow](docs/APP_FLOW.md)
4. [UI/UX design](docs/UI_UX_DESIGN.md)
5. [Backend schema](docs/BACKEND_SCHEMA.md)
6. [Implementation plan](docs/IMPLEMENTATION_PLAN.md)

## Run the built app

Extract `dist/VMA-windows-x64.zip` and run `VMA-win32-x64/VMA.exe`. Keep the entire extracted folder together. Python, Node, FFmpeg, and a browser installation are not needed by the user; the required Python and Chromium components are bundled. The app does not upload audio to a cloud service.

This initial ZIP is unsigned and intended for local testing. Before a public release, verify it on a clean Windows x64 computer without the build tools installed and arrange Windows code signing.

## Build from source

On a Windows x64 build computer, install Python 3.13, Node.js, and npm. From the repository root run:

```powershell
py -3.13 desktop\windows\build.py
```

The build script creates an ignored `.venv-build`, installs the hash-locked VMA runtime requirements plus pinned PyInstaller, installs the pinned Electron dependencies from `package-lock.json`, freezes the backend, verifies the frozen API and assets, packages Electron, launches the packaged app in smoke-test mode, writes `dist/VMA-windows-x64.zip`, then extracts and tests that ZIP with Python and Node removed from `PATH`. Internet access is needed for the build. The output is ignored by Git.

## Verification performed during the build

- Frozen backend `/api/ready`, frontend HTML/JavaScript, and bundled synthetic demo.
- Frozen backend V1 creation, reopening, and canonical WAV extraction.
- Frozen backend V2 creation, reopening, and exact payload extraction.
- Packaged Electron window loads the current UI and demo workflow, then shuts down its backend.

The existing repository test suite still owns comprehensive V1/V2, resource, and security behavior. Desktop packaging does not replace it.
