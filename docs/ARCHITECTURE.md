# Architecture

The browser sends uploads to FastAPI. API routes place each request into a UUID-named temporary directory, call the independent `backend.vma` package, and return VMA/WAV/ZIP downloads. The process holds no database state; an opened VMA is addressed only by its opaque session UUID and is deleted when the app stops.

The VMA package owns WAV parsing, VMA binary writing, reading/validation, and extraction. API routes never pack or unpack binary container fields themselves.

For playback, the API reconstructs each stored PCM stream as WAV. The frontend decodes both WAVs into Web Audio API buffers, attaches independent gain nodes plus a master gain node, and schedules sources from one `AudioContext` timeline. Seeking recreates both sources from the same timeline position, including each stream's format-level start offset.
