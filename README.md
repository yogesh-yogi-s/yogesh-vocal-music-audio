# VMA

VMA (Vocal Music Audio) is a versioned binary container for audio streams and an accompanying library and local web application.

The current application release is **v0.3**. The binary container is available in two versions:

- **VMA Version 1** — PCM WAV–only, two-stream (Vocal + Music) container. The application and API are fully V1-based.
- **VMA Version 2** — Format-agnostic opaque byte container. Stores any supplied source file byte-for-byte. V2 is a library-layer capability; no application or API V2 workflow exists yet.

## What VMA Does

1. Start with separate Vocal WAV and Music / Instrumental WAV files.
2. Package both streams into one `.vma` container.
3. Open the VMA in the local web application.
4. Play the streams synchronously as a complete mix.
5. Control Vocal and Music / Instrumental independently.
6. Extract the original stored streams when needed.

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

## Run Locally

Requirements: Python 3.13+ (tested with Python 3.13).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a browser. Uploads are limited to 500 MB per file and are held in temporary application storage.

## Browser Workflow

### Create

- Select a Vocal WAV.
- Select a Music / Instrumental WAV.
- Optionally enter a song title and artist.
- Choose **Create VMA**.
- Download the generated `song.vma` if needed; the newly created VMA opens automatically in the application.

### Open

- Select an existing `.vma` file.
- Choose **Open VMA**.
- View its title, artist, duration, and stream metadata as read from the container.

### Playback

Use **Play**, **Pause**, **Stop**, and the playback-position control to navigate the synchronized streams. Seeking is committed when the position control change is completed; dragging does not continuously recreate the synchronized Web Audio sources.

### Start offsets

The library and both create endpoint families accept optional `vocal_start_sample` and `music_start_sample` values. They are native-rate frame offsets on the shared playback timeline and default to `0`. Negative values are rejected by the existing validation and returned through the endpoint's normal error handling.

### Independent stream controls

- Master volume
- Vocal volume
- Music volume
- Vocal mute
- Music mute

The Vocal and Music / Instrumental streams share the same playback timeline while retaining independent gain and mute controls.

### Extraction

- **Extract Vocal** downloads the stored Vocal stream as WAV.
- **Extract Music** downloads the stored Music / Instrumental stream as WAV.
- **Extract Both** downloads a ZIP containing `vocal.wav` and `music.wav`.

Extraction retrieves the stored streams; it does not perform AI vocal separation.

## HTTP API

FastAPI provides interactive documentation at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) and an OpenAPI schema at [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json).

### Programmatic VMA endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Returns the local service health status. |
| POST | `/api/vma/create` | Packages multipart `vocal` and `music` PCM WAV uploads into `song.vma`. Optional `title`, `artist`, `vocal_start_sample`, and `music_start_sample` fields are accepted. |
| POST | `/api/vma/validate` | Validates a multipart VMA `file` and returns validation/stream metadata. |
| POST | `/api/vma/info` | Returns metadata and stream properties for a multipart VMA `file`. |
| POST | `/api/vma/extract/vocal` | Returns the stored Vocal stream from a multipart VMA `file` as WAV. |
| POST | `/api/vma/extract/music` | Returns the stored Music / Instrumental stream from a multipart VMA `file` as WAV. |
| POST | `/api/vma/extract/all` | Returns both stored streams from a multipart VMA `file` as a ZIP archive. |

The browser workflow also uses session-scoped routes internally: `POST /api/create`, `POST /api/open`, `GET /api/vma/{session_id}`, `GET /api/vma/{session_id}/stream/{kind}`, `GET /api/vma/{session_id}/extract/{kind}`, and `GET /api/vma/{session_id}/extract-all`. `POST /api/create` accepts the same optional start-sample fields.

Example: create a VMA through the programmatic API.

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/vma/create -F "vocal=@vocal.wav" -F "music=@music.wav" -o song.vma
```

## Testing

Run the complete automated suite:

```powershell
python -m pytest -q
```

Current verified state: **265 tests passing, 0 failed, 0 skipped, 0 errors**.

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
- FastAPI integration.
- Frontend contract checks.

Check JavaScript syntax separately with:

```powershell
node --check frontend/js/app.js
```

## Library API

When importing from the repository root, add `backend` to `PYTHONPATH` or install the package in your application environment.

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

V1 and V2 are entirely separate parsing stacks. V2 does not depend on V1 models. The format registry does not modify V1 or V2 bytes. Recognition is identity-only; decoding and playback are not part of any layer above.

## Technical Documentation

- [VMA v1 format specification](docs/VMA_FORMAT.md) — V1 binary layout, fields, synchronization model, codec identifier, and validation requirements.
- [VMA v2 format specification](docs/VMA_FORMAT_V2.md) — V2 binary layout, opaque byte-store contract, FORMAT_ID namespace, TLV FORMAT_INFO, version dispatch, and validation rules.
- [FORMAT_ID registry](docs/VMA_FORMAT_ID_REGISTRY.md) — Approved FORMAT_ID allocations, range policy, status lifecycle, and governance rules.
- [Architecture overview](docs/ARCHITECTURE.md) — Frontend, FastAPI, VMA library, temporary storage, extraction, and synchronized Web Audio playback flow.
