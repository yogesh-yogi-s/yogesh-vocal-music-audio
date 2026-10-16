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

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.app.main:app --reload
```

On Linux or macOS, use `python -m venv .venv && . .venv/bin/activate` in place of the PowerShell activation step.

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a browser. Uploads are limited to 500 MB per file and are held in temporary application storage.

To run the same application in a container:

```powershell
docker build -t vma .
docker run --rm -p 8000:8000 vma
```

## Browser Workflow

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
| GET | `/api/health` | Returns the local service health status. |
| POST | `/api/vma/create` | Packages multipart `vocal` and `music` uploads into `song.vma`. With no `version`, valid PCM WAV pairs use V1 and other accepted inputs use V2; `version=1` is strict PCM WAV and `version=2` stores opaque source bytes. Optional `title` and `artist` fields are accepted; `vocal_start_sample` and `music_start_sample` are accepted and apply to V1 creation only. |
| POST | `/api/vma/validate` | Validates a multipart VMA `file` and returns validation/stream metadata. |
| POST | `/api/vma/info` | Returns metadata and stream properties for a multipart VMA `file`. |
| POST | `/api/vma/extract/vocal` | V1-only: returns the stored Vocal stream from a multipart VMA `file` as WAV. |
| POST | `/api/vma/extract/music` | V1-only: returns the stored Music / Instrumental stream from a multipart VMA `file` as WAV. |
| POST | `/api/vma/extract/all` | V1-only: returns both stored streams from a multipart VMA `file` as a ZIP archive. |

The browser workflow uses session-scoped routes internally: `POST /api/create`, `POST /api/open`, `GET /api/vma/{session_id}`, `GET /api/vma/{session_id}/stream/{kind}`, `GET /api/vma/{session_id}/extract/{kind}`, `GET /api/vma/{session_id}/extract-all`, and `GET /api/vma/{session_id}/extract-stream/{stream_id}`. `POST /api/create` automatically selects V1 for two valid PCM WAV uploads and V2 for other accepted inputs. A pair whose filenames are both `.wav` but whose bytes are not valid RIFF/WAVE is rejected with HTTP 422. The V1-only stream and bulk-extraction routes reject V2, while the V2 per-stream route remains available regardless of playback support.

Example: create a VMA through the programmatic API.

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/vma/create -F "vocal=@vocal.wav" -F "music=@music.wav" -o song.vma
```

## Testing

Install the development dependencies, then run the complete automated suite:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Current verified state with a configured full local FFmpeg: **307 tests passing, 0 failed, 0 skipped, 0 errors**.

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
