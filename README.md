# VMA

VMA (Vocal Music Audio) is a versioned binary container for audio streams and an accompanying library and local web application.

The current application release is **v0.3**. The binary container is available in two versions:

- **VMA Version 1** — PCM WAV–only, two-stream (Vocal + Music) container with synchronized browser playback for valid PCM WAV streams.
- **VMA Version 2** — Format-agnostic opaque byte container. The application can create, open, inspect, and extract V2 streams byte-for-byte; browser playback is attempted only when the current browser can decode the actual source bytes.

## What VMA Does

1. Start with separate Vocal and Music / Instrumental source files.
2. Package both streams into one `.vma` container.
3. Valid PCM WAV pairs use VMA V1; other accepted inputs that do not qualify for V1 use VMA V2 without transcoding.
4. Open the VMA in the local web application.
5. Play any streams that the current browser can decode, synchronously when both are playable.
6. Control Vocal and Music / Instrumental independently.
7. Extract the original stored streams when needed.

The streams are preserved in the VMA container; they are not reconstructed during extraction.

## Important Limitation

VMA is a container format, not an AI source-separation system. It packages audio streams that are already separate.

If you only have one already-mixed MP3 or WAV containing Vocal and Music / Instrumental together, VMA cannot losslessly recover the original separate stems. That distinction is between containerization and source separation: VMA stores supplied streams; it does not infer missing streams from a mix.

## Supported V1 Input (application and API)

| Property | Supported value |
|---|---|
| Source file format | Ordinary RIFF PCM WAV (`RF64` is not supported) |
| Channels | Mono or stereo |
| PCM bit depth | 8, 16, 24, or 32-bit |
| Sample rate | Greater than 0 and up to 384 kHz |
| Streams per VMA | Exactly two |
| Stream types | Vocal and Music / Instrumental |

VMA v1 stores raw PCM WAV data chunks in a versioned, little-endian container. It does not use a custom audio codec or resample source streams during packaging.

## V2 application input

The local application accepts two non-empty uploads of any file type. Accepted inputs that do not qualify for the frozen V1 PCM WAV validator create a V2 container that stores the complete supplied source bytes without decoding, transcoding, or re-encoding them. If both uploaded filenames use the `.wav` extension but either file is not valid RIFF/WAVE data, the backend rejects the pair with HTTP 422 rather than silently packaging it as V2. Unknown or browser-unplayable accepted payloads remain inspectable and individually downloadable from V2.

## Run Locally

Requirements: Python 3.12+ (tested with Python 3.13).

On Windows with Python 3.13, double-click **Start VMA.cmd** in the repository folder. The launcher creates an ignored `.venv` if needed, installs the hash-locked dependencies on first run, and opens `http://127.0.0.1:8000` in your browser. Keep its terminal window open while using VMA; press Ctrl+C there to stop it. It listens only on this computer. Local operation uses the normal 500 MiB per-file limit and 8 GiB process temp budget unless you explicitly set their environment variables. No hosting account or Docker is needed.

For manual startup or other operating systems:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
$env:VMA_ENVIRONMENT = 'development'
python -m uvicorn backend.app.main:app --reload --no-proxy-headers
```

On Linux or macOS, use `python -m venv .venv && . .venv/bin/activate` in place of the PowerShell activation step.

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a browser. The server enforces a 500 MiB limit for each uploaded file and removes partial application copies when validation or storage fails. Upload filenames, media types, and contents are treated as untrusted; application storage uses generated names, while bounded sanitized basenames are retained only as V2 metadata. Uploads are held in temporary application storage.

To run the same application in a container:

```powershell
docker build -t vma .
docker run --rm -p 8000:8000 -e VMA_ENVIRONMENT=development vma
```

## Browser Workflow

### Welcome demo

Choose **Try demo** to open the bundled VMA V1 sample without uploading a file.
The sample contains two short, mathematically generated PCM tones and uses the
same session inspection, playback, seeking, controls, and extraction routes as a
user-opened VMA. Every request receives a separate temporary demo session; the
bundled source asset is never modified. The Create and Open workflows remain
available for personal files.

### Create

- Select a Vocal source file.
- Select a Music / Instrumental source file.
- Optionally enter a song title and artist.
- Choose **Create VMA**.
- Download the generated `song.vma` if needed; the newly created VMA opens automatically in the application.

### Open

- Select an existing `.vma` file.
- Choose **Open VMA**.
- View its title, artist, duration, and stream metadata as read from the container.

### Playback

The browser fetches each active stream and attempts native Web Audio `AudioContext.decodeAudioData()` decoding of the actual bytes. File extensions, MIME types, and V2 FORMAT_ID values are hints only; they do not guarantee playback.

- When both streams decode, **Play**, **Pause**, **Stop**, and the playback-position control operate on one shared Web Audio timeline.
- When exactly one stream decodes, the player remains available for that stream and the interface identifies the degraded state; the other original stream remains downloadable.
- When neither stream decodes, the player is hidden and V2 inspection/download controls remain available.

Seeking is committed when the position control change is completed; dragging does not continuously recreate the synchronized Web Audio sources.

### Start offsets

The V1 library and V1 creation path accept optional `vocal_start_sample` and `music_start_sample` values. They are native-rate frame offsets on the shared playback timeline and default to `0`. Negative values are rejected by the existing validation and returned through the endpoint's normal error handling. The application does not currently expose caller-supplied timing overrides when it creates a V2 container.

### Independent stream controls

- Master volume
- Vocal volume
- Music volume
- Vocal mute
- Music mute

The Vocal and Music / Instrumental streams share the same playback timeline while retaining independent gain and mute controls.

### Extraction

For V1, **Extract Vocal**, **Extract Music**, and **Extract Both** return WAV streams reconstructed from the stored PCM data.

For V2, each stream card provides its own download link. That route returns the complete original source bytes with the stored filename/metadata; it does not decode, transcode, or re-encode the payload. Extraction retrieves stored streams and never performs AI vocal separation.

## HTTP API

FastAPI provides interactive documentation at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) and an OpenAPI schema at [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json).

### Programmatic VMA endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Process liveness; does not test storage readiness. |
| GET | `/api/ready` | Readiness check for initialized, accessible application storage. |
| POST | `/api/vma/create` | Packages multipart `vocal` and `music` uploads into `song.vma`. With no `version`, valid PCM WAV pairs use V1 and other accepted inputs use V2; `version=1` is strict PCM WAV and `version=2` stores opaque source bytes. Optional `title` and `artist` fields are accepted; `vocal_start_sample` and `music_start_sample` are accepted and apply to V1 creation only. |
| POST | `/api/vma/validate` | Validates a multipart VMA `file` and returns validation/stream metadata. |
| POST | `/api/vma/info` | Returns metadata and stream properties for a multipart VMA `file`. |
| POST | `/api/vma/extract/vocal` | V1-only: returns the stored Vocal stream from a multipart VMA `file` as WAV. |
| POST | `/api/vma/extract/music` | V1-only: returns the stored Music / Instrumental stream from a multipart VMA `file` as WAV. |
| POST | `/api/vma/extract/all` | V1-only: returns both stored streams from a multipart VMA `file` as a ZIP archive. |

The browser workflow uses session-scoped routes internally: `POST /api/demo`, `POST /api/create`, `POST /api/open`, `GET /api/vma/{session_id}`, `GET /api/vma/{session_id}/stream/{kind}`, `GET /api/vma/{session_id}/extract/{kind}`, `GET /api/vma/{session_id}/extract-all`, `GET /api/vma/{session_id}/extract-stream/{stream_id}`, and `DELETE /api/vma/{session_id}`. `POST /api/demo` accepts no upload or path and opens the fixed bundled sample in a fresh temporary session. `POST /api/create` automatically selects V1 for two valid PCM WAV uploads and V2 for other accepted inputs. A pair whose filenames are both `.wav` but whose bytes are not valid RIFF/WAVE is rejected with HTTP 422. The V1-only stream and bulk-extraction routes reject V2, while the V2 per-stream route remains available regardless of playback support.

### Anonymous browser session security

Browser sessions remain account-free. On the first successful Create, Open, or Try Demo request, the server creates a cryptographically random browser ownership credential in an `HttpOnly`, `SameSite=Strict`, `/api` cookie. Only a SHA-256 digest is stored beside each temporary session. The UUID in a session URL is an identifier, not authorization: every inspect, playback, extraction, download, and deletion request must also prove ownership. Missing, invalid, expired, deleted, and foreign sessions all return the same generic not-found response.

The browser credential can own multiple independent personal and demo sessions, so opening a new tab or creating a second VMA does not invalidate earlier sessions. A page refresh retains access while the browser session cookie and server-side temporary data still exist. Sessions expire after two hours of inactivity; **Delete session** revokes one selected session without deleting the browser's other sessions. Demo sessions use the same ownership checks but remain separate copies, never a shared writable session.

State-changing browser routes validate the request origin (and Fetch Metadata when supplied) to defend the cookie against CSRF. Production mode requires an explicit HTTPS origin on these requests. The ownership cookie is always `Secure` in production and is non-Secure only for genuine loopback HTTP development. The application does not enable CORS or cross-origin credential sharing. Passing tests does not by itself make the development server production-ready.

### Resource and abuse limits

The default per-file limit remains 500 MiB. A small preview deployment can lower it with `VMA_MAX_UPLOAD_BYTES` (bytes), but cannot raise it above 500 MiB. Before multipart parsing, the application rejects a declared or streamed request body above twice the configured file limit plus 2 MiB for two-source Create requests, or the file limit plus 2 MiB for single-file Open, Validate, Info, and stateless Extract requests. The additional 2 MiB is a multipart-envelope allowance for boundaries, safe filenames, and form fields; it is not additional audio capacity. Try Demo accepts at most a 64 KiB request body. Oversized bodies receive a consistent HTTP 413 response, while the streamed per-file check remains as defense in depth.

Default single-process controls are:

- 3 concurrent expensive requests process-wide and 2 active operations per session.
- 8 GiB of application-owned temporary-storage admission capacity.
- 128 live sessions process-wide and 16 live sessions per anonymous browser credential. New sessions are rejected at the boundary; existing sessions are never evicted to make room.
- A 60-second client rate window: Demo 12, Create 10, Open 20, Inspect 120, Extract/Stream 60, and Validate/Info 30 requests. Limits return HTTP 429 with `Retry-After`. The connection peer is used unless it belongs to an explicitly configured trusted proxy network; untrusted forwarding headers are stripped.

Operators can set `VMA_MULTIPART_OVERHEAD_BYTES`, `VMA_DEMO_REQUEST_BYTES`, `VMA_MAX_PROCESS_TEMP_BYTES`, `VMA_MAX_ACTIVE_EXPENSIVE_REQUESTS`, `VMA_MAX_ACTIVE_SESSION_OPERATIONS`, `VMA_MAX_PROCESS_SESSIONS`, `VMA_MAX_BROWSER_SESSIONS`, `VMA_RATE_WINDOW_SECONDS`, and the category variables `VMA_RATE_<CATEGORY>_PER_WINDOW`. Values are positive integer byte/count values and are read at process startup. These controls are deliberately process-local. Multiple workers need a shared limiter, shared session/storage accounting, and distributed deletion/expiry coordination.

The container image runs as an unprivileged `vma` user and uses `/tmp/vma`. A runtime may additionally mount it as a bounded tmpfs, for example `--tmpfs /tmp/vma:rw,noexec,nosuid,size=8g`. An ingress should still enforce corresponding request-body and connection/rate limits before traffic reaches Python's multipart parser.

### Production deployment configuration

The supported production model is **one VMA application process behind one HTTPS-terminating reverse proxy**. The proxy must overwrite (not append untrusted values to) `X-Forwarded-Proto`, `X-Forwarded-Host`, and `X-Forwarded-For`. Uvicorn must run with `--no-proxy-headers`; VMA performs its own forwarding-header validation. Do not expose the application port directly when it is configured to trust a proxy network.

Set these values before starting the process:

| Setting | Production requirement |
|---|---|
| `VMA_ENVIRONMENT` | Set to `production`; this enables fail-closed origin rules, HSTS, and unconditional Secure ownership cookies. |
| `VMA_TRUSTED_HOSTS` | Required comma-separated public hostnames, for example `audio.example.com`. A bare `*` is rejected. A leading wildcard such as `*.example.com` is supported only when intentionally configured. |
| `VMA_ALLOWED_ORIGINS` | Required comma-separated exact HTTPS origins, for example `https://audio.example.com`. Paths, credentials, query strings, fragments, and HTTP origins are rejected. |
| `VMA_HEALTHCHECK_HOST` | Required exact hostname used by the container readiness probe. It must match `VMA_TRUSTED_HOSTS`; use a concrete hostname such as `audio.example.com` even when trusted hosts also contain a wildcard. |
| `VMA_TRUSTED_PROXIES` | Optional comma-separated IP addresses or CIDR networks for actual proxy peers. Leave empty for direct TLS. Never use a broad network merely to make forwarding work. |
| `VMA_TEMP_ROOT` | Existing, writable directory dedicated to VMA temporary state. The container fixes this to `/tmp/vma`. |

The application rejects untrusted hosts before routing, ignores forwarding metadata from untrusted peers, and emits CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, a restrictive Permissions Policy, and a response/request-correlation ID. HSTS is emitted in production. The current CSP must retain `script-src 'unsafe-inline'` because the HTML contains a small inline pre-paint theme initializer; removing that exception requires moving or hashing that initializer and browser-regression testing it.

`VMA_ENVIRONMENT` has no implicit default: direct Uvicorn launches fail clearly unless the operator explicitly selects `development`, `test`, or `production`. The container selects `production` by default and therefore also refuses to start until trusted hosts, HTTPS origins, and an exact trusted health-check hostname are supplied. Production returns 404 for `/docs` and `/redoc`; local development retains both interactive documentation pages. `/openapi.json` remains available for programmatic schema clients.

Production checklist:

- Terminate TLS at the trusted proxy (or configure direct TLS), redirect HTTP to HTTPS, and set the values above. Verify an ownership cookie has `Secure`, `HttpOnly`, `SameSite=Strict`, and `Path=/api`.
- Configure the proxy to replace forwarding headers, enforce accepted hosts, and apply the same request-body ceilings as VMA: 1,002 MiB for two-file Create requests, 502 MiB for single-upload requests, and 64 KiB for Demo.
- Apply proxy-level header/body read timeouts, connection limits, and slow-client defenses. The application deliberately has no arbitrary processing timeout because valid large-file operations can be long-running. The container sets Uvicorn's idle keep-alive timeout to five seconds; that is not a request-duration defense.
- Run exactly one application worker/replica. Ownership keys, sessions, rate windows, active leases, quota accounting, and temporary files are process-local. Multiple workers require a shared-state/storage design and distributed coordination, not merely sticky routing.
- Mount `/tmp/vma` (or `VMA_TEMP_ROOT` plus the operating-system temp location) on bounded storage sized for the configured 8 GiB admission budget and multipart spool overhead. Starlette's multipart parser may spool outside the application session tree using the operating-system temp directory.
- Monitor free space/inodes, 413/429/507/5xx rates, readiness, process restarts, and cleanup failures. `/api/health` is liveness; `/api/ready` verifies initialized storage directories, disk accessibility, and a small temporary write. The container probe sends the first configured trusted hostname.
- Expect all sessions to disappear on process/container restart. Inactive sessions expire after two hours and periodic cleanup is best-effort; Delete session revokes access immediately, while physical removal waits for active responses to finish.
- Keep logs access-controlled. Request logs contain a correlation ID, method, coarse route category, status, and duration; they intentionally omit cookies, ownership tokens, uploaded bytes, and full session URLs.

Example: create a VMA through the programmatic API.

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/vma/create -F "vocal=@vocal.wav" -F "music=@music.wav" -o song.vma
```

## Testing

Install the development dependencies, then run the complete automated suite:

```powershell
python -m pip install -r requirements-dev.lock
python -m pytest -q
```

`requirements.txt` and `requirements-dev.txt` declare the reviewed direct
dependency ranges. Reproducible installs use `requirements.lock` and
`requirements-dev.lock`; both pin the complete Python 3.13 dependency graph,
require wheels, and enforce SHA-256 hashes. The Docker image installs only the
runtime lock.

To update the locks, resolve the direct declarations for CPython 3.13 on
Windows x86-64, Linux manylinux2014 x86-64/aarch64, and Alpine musllinux
x86-64/aarch64. Review release notes and advisories, then capture each selected
wheel and its SHA-256 from pip's JSON `--report` output or the downloaded wheel
bytes. For musllinux, include both `musllinux_1_2` and `musllinux_1_1` target
tags, since some pinned packages publish only the latter. Include all platform
hashes for binary packages, retain the platform markers for `colorama` and
`uvloop`, then verify clean installs with `python -m pip install -r
requirements-dev.lock` and platform-targeted `pip download --no-deps -r
requirements.lock --only-binary=:all: --platform ... --python-version 3.13`.
Finally verify an actual image build on each platform before release. Never
remove `--require-hashes` or silently refresh the lock during an image build.

The Phase 4D hash-locked Python 3.13 verification completed with **448 tests
passing, 0 failed, 4 skipped, and 1 deprecation warning**. The four skips are
the opt-in real-codec cases described below; they were not counted as passes.

The suite covers:

- All eight synthetic audio fixture groups.
- Equal and different stream durations.
- Sample-rate mismatch and mono/stereo channel mismatch.
- VMA V1 start-sample offset behavior.
- Focused malformed-input mutation coverage for the WAV parser.
- Corruption and truncation validation.
- Exact PCM lossless round trips.
- VMA V2 header, descriptor, TLV, extraction, and dispatch tests.
- FORMAT_ID registry range classification, allocation governance, and append-only rules.
- RIFF/WAV format recognition (signature-only; no PCM decoding).
- FastAPI integration and frontend contract checks.
- Opt-in real MP3, AAC/M4A, Vorbis/OGG, and Opus/OGG source generation, independent FFprobe/full-decode validation, and V2 byte-exact API extraction.

### Optional real-codec integration check

The real-codec test is intentionally opt-in. It never downloads tools or fixtures and generates only short synthetic tones in pytest temporary storage. Set `VMA_REAL_CODEC_FFMPEG` to a full local `ffmpeg.exe` with a colocated `ffprobe.exe`; the tool must support MP3, AAC, Vorbis, and Opus encoding/decoding plus MP3, MP4/M4A, and OGG containers.

```powershell
$env:VMA_REAL_CODEC_FFMPEG = 'C:\path\to\ffmpeg.exe'
python -m pytest -q tests/test_vma_real_codec_fixtures.py
python -m pytest -q
```

Without that variable, the four real-codec cases skip rather than installing or downloading media tooling. These checks validate source-file generation and V2 storage/extraction, not universal browser codec support.

Check JavaScript syntax separately with:

```powershell
node --check frontend/js/app.js
```

An optional local type check is available when Node.js/npx can resolve Pyright. Pyright is not a pinned project dependency and is not currently part of the CI workflow, so an uncached `npx` invocation may require network access:

```powershell
npx.cmd pyright backend
```

## Library API

Install the `vma` library from the repository root, or add `backend` to `PYTHONPATH`:

```powershell
python -m pip install .
```

The library has no third-party runtime dependencies. Use `python -m pip install ".[app]"` to add the web application dependencies.

```python
from vma import create_vma, read_vma, extract_vocal, extract_music, extract_all, validate_vma

create_vma(
    "vocal.wav", "music.wav", "song.vma",
    {"title": "Song", "artist": "Artist"},
    vocal_start_sample=0,
    music_start_sample=0,
)
info = read_vma("song.vma")
extract_vocal("song.vma", "vocal.wav")
```

## Library Architecture

The `backend/vma/` package is structured in isolated layers:

| Layer | Module | Responsibility |
|---|---|---|
| **V1 container** | `vma/` | Frozen. PCM WAV–only writer, reader, extractor, validator. |
| **V2 container** | `vma/v2/` | Frozen. Format-agnostic byte writer, reader, extractor, dispatcher. |
| **Format registry** | `vma/formats/` | FORMAT_ID registry, format recognition API, RIFF/WAV recognizer. |
| **Dispatcher** | `vma/dispatch.py` | `read_vma_any()` — routes V1/V2 by version field. |

V1 and V2 are entirely separate parsing stacks. V2 does not depend on V1 models. The format registry does not modify V1 or V2 bytes, and recognition remains identity-only. The web application may attempt browser-native decoding above those container layers, but the VMA library itself does not provide a media decoder or make playback a storage requirement.

## Technical Documentation

- [VMA v1 format specification](docs/VMA_FORMAT.md) — V1 binary layout, fields, synchronization model, codec identifier, and validation requirements.
- [VMA v2 format specification](docs/VMA_FORMAT_V2.md) — V2 binary layout, opaque byte-store contract, FORMAT_ID namespace, TLV FORMAT_INFO, version dispatch, and validation rules.
- [FORMAT_ID registry](docs/VMA_FORMAT_ID_REGISTRY.md) — Approved FORMAT_ID allocations, range policy, status lifecycle, and governance rules.
- [Architecture overview](docs/ARCHITECTURE.md) — Frontend, FastAPI, VMA library, temporary storage, extraction, and synchronized Web Audio playback flow.
- [Roadmap](docs/ROADMAP.md) — current-flow analysis, performance findings, and the phased public-reach plan.

## License

MIT — see [LICENSE](LICENSE).
