# VMA Windows Desktop — Backend Schema

## Storage model

There is no SQL database. The existing FastAPI process uses ephemeral, process-owned temporary directories for uploaded files, generated VMA files, and sessions. Session ownership uses the existing secure token/cookie mechanism. Shutdown removes application session storage.

## API surface reused by the desktop UI

| Route | Purpose |
|---|---|
| `GET /api/health`, `GET /api/ready` | Liveness and startup readiness |
| `POST /api/demo` | Open bundled synthetic demo |
| `POST /api/create` | Create V1 or V2 from vocal and music uploads |
| `POST /api/open` | Validate/open an existing VMA into a session |
| `GET /api/vma/{session_id}` | Read active session metadata |
| `GET /api/vma/{session_id}/stream/{kind}` | V1 playable WAV stream |
| `GET /api/vma/{session_id}/extract/{kind}` | V1 canonical WAV download |
| `GET /api/vma/{session_id}/extract-all` | V1 ZIP download |
| `GET /api/vma/{session_id}/extract-stream/{stream_id}` | V2 original payload download |
| `DELETE /api/vma/{session_id}` | Release a session |

The existing stateless `/api/vma/create`, `/validate`, `/info`, and `/extract/*` routes remain available. See `backend/app/main.py` for request/response details; this desktop layer does not fork the contract.

## V1 container

The existing `backend/vma` reader, writer, and extractor own the versioned header, stream entries, timing fields, PCM metadata, byte boundaries, and canonical WAV reconstruction. V1 creation requires two valid PCM WAV inputs.

## V2 container

The existing V2 reader, writer, and validator own the fixed header, metadata JSON, stream descriptors, role, `FORMAT_ID`, nanosecond timing, payload offsets and lengths, and FORMAT_INFO TLVs. `FORMAT_ID` is metadata, not a decoder selector. The original payload bytes must remain unchanged through extraction.

## Desktop-only process contract

The backend child prints `VMA_PORT=<decimal>` once after binding a loopback socket. The parent accepts only a valid port and waits for `/api/ready`. The child accepts a single `shutdown` line on stdin to request graceful ASGI shutdown. These signals are process-local and are not public HTTP endpoints.
