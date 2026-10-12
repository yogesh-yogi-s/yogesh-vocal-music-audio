# VMA Roadmap — Performance and Public Reach

This document records the analysis of the current VMA application flow and the
planned path to improve performance and public reach. It is a planning artifact;
it does not change the frozen V1 or V2 binary contracts, which remain governed by
[VMA_FORMAT.md](VMA_FORMAT.md), [VMA_FORMAT_V2.md](VMA_FORMAT_V2.md), and the
[FORMAT_ID registry](VMA_FORMAT_ID_REGISTRY.md).

## 1. Current flow

```
Browser (vanilla JS, frontend/)
  └─ POST /api/create | POST /api/open          → FastAPI (backend/app/main.py)
       └─ UUID job directory in a process-lifetime temp dir
            └─ backend/vma library (no I/O dependencies)
                 ├─ v1/       PCM WAV only, exactly two streams, frozen
                 ├─ v2/       opaque byte container, frozen, LIBRARY-ONLY
                 ├─ formats/  recognition only (no decode)
                 └─ dispatch  read_vma_any() routes by version field
  ← GET  /api/vma/{id}/stream/{kind}             → re-extracts WAV to disk every call
  ← Web Audio: 2 × (fetch full WAV → arrayBuffer → decodeAudioData) → gain graph
```

### What is already strong (keep it)

- Layered library with frozen V1/V2 stacks and explicit version dispatch.
- Append-only FORMAT_ID registry with allocation ranges and governance rules.
- Format specifications that separate storage, recognition, and decode concerns.
- A large automated suite (281 tests) covering fixtures, corruption, and API flows.

### Structural gaps

| Area | Gap |
|---|---|
| Version identity | The application release is v0.3, but the FastAPI title and UI said v0.1. |
| Packaging | No `pyproject.toml`; the `vma` library is only importable by path. |
| Licensing | No LICENSE, so the format and code cannot be legally reused. |
| Deployment | No container image, CI, or deploy configuration. State lives in a process temp dir that is deleted on restart. |
| Top of funnel | VMA requires two already-separated stems. Most end users do not have stems. |

## 2. Performance findings (ranked)

| # | Finding | Fix | Impact |
|---|---|---|---|
| 1 | Blocking container/zip work runs inside `async def` handlers while session `def` handlers use the threadpool. | Move blocking work to `anyio.to_thread.run_sync` or a worker queue. | High |
| 2 | V1 stores raw PCM uncompressed (~74 MB per 3:30 stereo stem), then the browser decodes to Float32 (~148 MB in tab). | Streamed playback path (Range + MediaElementSource) and an optional lossy *delivery* preview that is never stored in the container. | High |
| 3 | Playback re-extracts the WAV on every `stream/{kind}` request; no caching or Range. | Cache extracted WAVs per session; add `ETag`/`Cache-Control`/`Range`. | High |
| 4 | `describeWav` reads an entire selected file into memory to read a 44-byte header. | Read `file.slice(0, 65536)` only. | High (cheap) |
| 5 | No upload progress for large files. | XHR `upload.onprogress`; later chunked/resumable uploads. | Medium |
| 6 | Session state is local temp storage, single worker, no Range. | Object storage (S3/R2) with opaque IDs and signed access. | High for public |

## 3. Reach findings

- **Legal**: no LICENSE blocks reuse and ecosystem adoption.
- **Installability**: no published package, so no third-party integration.
- **Landing**: the app binds loopback and has no demo, share links, or social metadata — public reach is currently zero.
- **Funnel**: the container is the front door. Users want the outcome (synchronized
  vocal/instrumental playback, practice, export, sharing), not a `.vma` file.
- **Identity**: VMA is a container, not a source-separation system. That boundary is
  correct and should be preserved by adding separation as a documented *upstream*
  service, not by weakening the format contract.

## 4. Verdict

- **As a format and library: correct.** Keep and harden it.
- **As a consumer product: inverted.** Keep the format as the moat, but make the
  outcome the front door and treat the container as an implementation detail plus a
  developer deliverable.

## 5. Phased plan

### Phase 0 — Legible and legal (this change)

- MIT LICENSE.
- Fix v0.1 → v0.3 application version drift.
- `pyproject.toml` so `vma` is installable; split runtime and dev requirements.
- CI running the full test suite on supported Pythons plus `node --check`.
- Dockerfile for a reproducible single-command run.
- **Outcome:** the project is adoptable, installable, and reproducible.

### Phase 1 — Reachable

- One-click deploy and a pre-loaded demo container so a visitor hears synchronized
  vocal/instrumental control without uploading anything.
- Open Graph / SEO metadata, shareable read-only session links, PWA shell.
- **Outcome:** a URL that can be posted, with measurable first-session activation.

### Phase 2 — Fast

- Range + caching for stream and extraction routes; cache extracted WAVs.
- Threadpool/queue for blocking container and zip work.
- Sliced header reads in the frontend; upload progress and chunked uploads.
- **Outcome:** usable on a phone and on a slow connection.

### Phase 3 — Open the funnel (highest leverage)

- Optional separation service (for example Demucs or an ONNX model) that turns one
  mixed upload into two stems, then packages them through the existing writer.
- Keep the boundary explicit: separation is upstream; the container still only
  stores supplied bytes.
- **Outcome:** the majority of users who lack stems can start.

### Phase 4 — Next level reach

- Publish the `vma` library with conformance vectors; developer SDK.
- Practice-player niche features (per-stem tempo/pitch/loop, karaoke, language
  learning) and distribution through musician and developer communities.
- **Outcome:** developers extend it; musicians live in it.

## 6. Success measures

| Phase | Measure |
|---|---|
| 0 | CI green; `pip install .` succeeds; container image builds. |
| 1 | Time-to-first-playback for a new visitor under 30 s (demo path). |
| 2 | Median session load under 5 s on a mobile network; no event-loop stalls. |
| 3 | Share of sessions started without pre-existing stems. |
| 4 | External integrations referencing the published library. |
