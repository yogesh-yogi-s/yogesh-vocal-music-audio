# Architecture

VMA has three deliberately separate concerns: container storage, application inspection/extraction, and optional browser playback. The format library never needs a media decoder to store or extract a stream.

## Application flow

The browser uploads two source files to FastAPI. Each request is written to a UUID-named directory below process-owned temporary storage, then routed through `backend.app.vma_service` and the independent `backend.vma` library. With no requested version, two valid PCM WAV uploads create V1; other accepted inputs create V2 and store the supplied files as opaque source bytes. If both upload names use `.wav` but either payload is not valid RIFF/WAVE data, the backend rejects the pair with HTTP 422 rather than falling back to V2. A forced V1 request rejects inputs that do not satisfy the V1 PCM WAV rules.

Opened containers receive an opaque session UUID. Session directories expire after two hours, are periodically cleaned, and are removed when the application stops. There is no database, account system, cloud storage, or durable session state.

## Container layers

- **V1 (`backend/vma/`)** is frozen and contains the PCM WAV parser, V1 binary reader/writer/validator, WAV reconstruction extractor, and V1 frame-offset support.
- **V2 (`backend/vma/v2/`)** is frozen and stores original stream payload bytes with generic descriptors. It reads, validates, and extracts bytes directly without media inspection or decoding.
- **Version dispatch (`backend/vma/dispatch.py`)** selects the V1 or V2 reader from the shared magic and version field.
- **Format utilities (`backend/vma/formats/`)** provide the append-only FORMAT_ID registry plus limited identity/probe helpers. They do not establish decoder capability.

API routes delegate binary parsing, creation, validation, and extraction to these layers rather than packing container fields themselves. V1 `create_vma()` accepts non-negative `vocal_start_sample` and `music_start_sample` frame offsets. The current application does not offer caller-defined V2 timing overrides.

## Inspection, extraction, and playback

V1 session routes expose reconstructed WAV streams and V1 bulk extraction. V2 session routes expose per-stream downloads through `extract-stream/{stream_id}`; those downloads are the exact original payload bytes. V2 inspection and extraction do not depend on a stream being playable.

For either active version, the frontend fetches the relevant stream bytes and attempts native `AudioContext.decodeAudioData()` decoding. It uses decoded buffers only in memory; it never replaces container payloads. When both streams decode, the frontend schedules them on one `AudioContext` timeline with individual gain nodes and a master gain node. When one stream decodes, it exposes a clearly degraded single-stream player; when neither does, it keeps inspection and download controls available and hides the player. Browser support depends on the real bytes, codec, and browser implementation—not on an extension, MIME type, or FORMAT_ID alone.

Seeking is committed on the position control's `change` event, avoiding continuous source recreation while dragging. An activation token invalidates late asynchronous fetch/decode work when the active container changes; stopping/switching cleans up active source nodes and timer state.
