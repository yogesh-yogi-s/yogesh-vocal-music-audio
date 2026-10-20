# VMA Windows Desktop — App Flow

```text
User launches VMA.exe
  -> Electron enforces one app instance
  -> Electron starts bundled VMA backend
  -> Backend binds 127.0.0.1 on an OS-assigned port
  -> Backend prints startup port; Electron waits for /api/ready
  -> Electron opens existing VMA frontend in a sandboxed window
  -> Home / Create / Open / Inspect / Playback / Extract
  -> User closes window
  -> Electron requests graceful backend shutdown and exits
```

## Create

Two files -> existing frontend form -> `POST /api/create` -> backend size and format validation -> V1 for two valid PCM WAV inputs, otherwise V2 under current rules -> generated `.vma` returned for download and opened in the current session. Errors restore the Create button and display a safe status message.

## Open and inspect

`.vma` -> `POST /api/open` -> validated session metadata -> Inspect view. Browser-decodable streams load into Web Audio; unsupported streams remain inspectable and downloadable. A malformed container returns a safe error and no playable state.

## Playback

Both decoded tracks use the existing shared AudioContext timeline. Volume and mute are independent. Seeking previews position while dragging and commits the actual source restart on change. File switching removes old sources and state.

## Extract

V1 streams -> canonical WAV reconstruction. V2 streams -> exact stored bytes. Download happens in the embedded window. No media conversion or codec installation is involved.

## Failure paths

- Backend startup failure or readiness timeout -> Electron error dialog and clean shutdown.
- Upload or temporary-storage limit -> existing HTTP error and frontend status, without corrupting prior files.
- Undecodable stream -> existing partial-playback state; extraction remains available.
- Closing during work -> graceful backend stop, then process termination fallback.
