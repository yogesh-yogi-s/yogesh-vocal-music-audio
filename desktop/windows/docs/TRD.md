# VMA Windows Desktop — Technical Requirements

## Runtime design

- Electron owns the application window and bundles Chromium for the current Web Audio frontend.
- A PyInstaller one-folder build contains CPython 3.13, the locked runtime dependencies, existing FastAPI app, VMA library, frontend assets, and bundled demo.
- Electron starts the bundled backend as a child process, reads its selected loopback port from a one-line startup handshake, probes `/api/ready`, then loads `http://127.0.0.1:<port>/`.
- The backend remains single-process; sessions remain ephemeral in the existing application temp area.
- The parent requests a graceful child shutdown when the last window closes, with a bounded termination fallback.

## Security

- Bind to `127.0.0.1` only; select an OS-assigned port.
- Set explicit local trusted host and origin values for that port. Disable proxy-header trust.
- Electron renderer: `nodeIntegration: false`, `contextIsolation: true`, `sandbox: true`, and `webSecurity: true`.
- Deny permission requests and new windows; prevent navigation away from the app origin.
- Preserve the backend's host, origin, cookie, upload, rate, and temporary-storage protections.
- Do not give untrusted VMA metadata access to Electron or Node APIs.
- Package only runtime dependencies; keep build tools out of the release folder.

## Build inputs and output

- Build host: Windows x64 with Python 3.13, Node.js, npm, and internet during build.
- Python runtime dependencies: repository `requirements.lock`, installed with its hashes.
- Build-only dependencies: a pinned PyInstaller version and pinned Electron/packager versions.
- Output: ignored `desktop/windows/dist/VMA-win32-x64/` plus a ZIP of that folder.
- Users need no Python, npm, FFmpeg, or browser installation to run the completed package.

## Compatibility and performance

- Keep the established `/api` contracts and frontend assets unchanged unless a packaging defect requires a narrow fix.
- Preserve native Web Audio decoding. Unsupported/invalid audio remains inspectable and extractable under existing V2 rules.
- Preserve 500 MiB per-file upload limits and 8 GiB process temp admission defaults.
- Only one backend instance per Electron application instance. A second app instance focuses the first window.

## Verification

- Verify the frozen backend executable's health, ready, demo, Create, Open, and Extract behavior.
- Verify Electron launches the frozen backend and loads the actual UI, not just a mock page.
- Run existing V1/V2 parser and API tests and check the release folder contains all assets.
- Perform an offline clean-machine launch and real browser-engine playback before publishing a release.
