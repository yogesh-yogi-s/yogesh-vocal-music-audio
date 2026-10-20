# VMA Windows Desktop — Product Requirements

## Goal

Deliver a downloadable Windows x64 application that runs VMA entirely on the user's computer. The user downloads and extracts one distribution folder, launches `VMA.exe`, and can create, open, inspect, play, and extract VMA containers without installing Python, Node, FFmpeg, or a separate browser.

## Source of truth

The existing `backend/vma`, `backend/app`, and `frontend` implementations are the product logic. The desktop project packages and hosts those implementations; it does not define a new VMA format or independently rewrite the parser, writer, extractor, or player.

## User journeys

1. Launch the app and see the existing Home view and bundled synthetic demo.
2. Select two source files and create a VMA. Two valid PCM WAV files create V1; other accepted pairs create V2 under the existing rules. Download the resulting container.
3. Open a `.vma`, inspect its version, metadata, stream information, and validation result.
4. Play each stream the embedded Chromium engine can decode, with synchronized play, pause, resume, stop, seek, volume, and mute.
5. Extract V1 canonical WAV streams or V2 byte-identical stored payloads.
6. Close the window and stop the local backend without leaving an exposed network service.

## Requirements

- Offline after distribution download; no account or cloud upload.
- Preserve the 500 MiB per-file upload ceiling and configurable 8 GiB process temp budget.
- Bind the backend only to loopback on a dynamically assigned port. Do not expose it on the LAN.
- Preserve safe validation, resource controls, ownership checks, and structured errors.
- Show a clear startup error if the backend cannot initialize.
- Downloaded files use the existing application flow. The user chooses where the browser engine saves them.
- Keep the existing responsive dark/light UI, accessible labels, and status messages.
- Distribute an x64 Windows folder or ZIP with an executable and all required runtime files.

## Explicit limits

- VMA does not separate vocals from mixed audio.
- Packaging does not add codecs. A valid stream must be decodable by the embedded Chromium engine to play; extraction does not require decoding.
- An unsigned first build may trigger Windows reputation prompts. Code signing is a later release requirement.

## Acceptance

- A clean Windows x64 test machine without Python or Node can launch the extracted app offline.
- Local readiness succeeds; Create/Open/Playback/Extract flows work with synthetic V1 and V2 fixtures.
- V1 canonical WAV reconstruction and V2 exact byte extraction match the existing tests.
- Closing the app stops its backend process; opening a second instance does not corrupt the first.
