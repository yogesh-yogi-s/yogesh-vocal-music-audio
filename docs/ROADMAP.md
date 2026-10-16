# VMA Roadmap — Performance and Public Reach

This document records the current application flow and planned product work. It is a
planning artifact: it does not change the frozen V1 or V2 binary contracts governed by
[VMA_FORMAT.md](VMA_FORMAT.md), [VMA_FORMAT_V2.md](VMA_FORMAT_V2.md), and the
[FORMAT_ID registry](VMA_FORMAT_ID_REGISTRY.md). Completed items describe the current
repository state; later phases remain proposals.

## 1. Current flow

```
Browser (vanilla JS, frontend/)
  └─ POST /api/create | POST /api/open          → FastAPI (backend/app/main.py)
       └─ UUID session directory in process-owned temporary storage
            └─ backend/vma library
                 ├─ v1/       PCM WAV only, exactly two streams, frozen
                 ├─ v2/       opaque byte container, frozen; reachable via API/UI
                 ├─ formats/  registry, recognition, and narrow metadata probes (no decode)
                 └─ dispatch  read_vma_any() routes by version field
  ← V1: GET /api/vma/{id}/stream/{kind}          → reconstructed WAV
  ← V2: GET /api/vma/{id}/extract-stream/{id}    → exact original bytes
  ← Web Audio: fetch full source bytes → decodeAudioData when supported → gain graph
```

The application automatically creates V1 for two valid PCM WAV inputs. Other accepted
non-empty uploads create V2 and retain the supplied bytes. Native browser decoding is an
optional application capability, not a VMA storage requirement: a stream remains
inspectable and downloadable even if it cannot be decoded by the current browser.

### What is already strong (keep it)

- Layered library with frozen V1/V2 stacks and explicit version dispatch.
- Append-only FORMAT_ID registry with allocation ranges and governance rules.
- Format specifications that separate storage, recognition, probing, and decoding.
- Native Web Audio playback that uses actual decode success, supports synchronized
  two-stream playback when both decode, and reports degraded/no-playback states clearly.
- A local 307-test suite when its opt-in FFmpeg integration environment is configured,
  including byte-exact V2 extraction checks for generated compressed-codec fixtures.

### Structural gaps

| Area | Gap |
|---|---|
| Session storage | State is local temporary storage and is removed on restart; sessions are neither shareable nor durable. |
| Playback memory | Playback fully fetches and decodes selected streams in the browser, which can be expensive for large inputs. |
| Delivery | Docker and CI exist, but there is no hosted deployment or multi-process/object-storage session design. |
| Top of funnel | VMA requires two already-separated stems. Most end users do not have stems. |

## 2. Performance findings (ranked)

| # | Finding | Candidate next step | Impact |
|---|---|---|---|
| 1 | Blocking container/ZIP work runs inside some `async def` handlers while session `def` handlers use the threadpool. | Measure and move suitable blocking work to `anyio.to_thread.run_sync` or a worker queue. | High |
| 2 | V1 raw PCM and native browser decoding can consume substantial memory. V2 playback also fully fetches/decode-attempts supported sources. | Investigate streaming/caching; any delivery preview must never replace the container payload. | High |
| 3 | V1 playback reconstructs WAV on `stream/{kind}` requests, while V2 per-stream downloads are direct copies; neither path has HTTP caching or Range support. | Add per-session caching and evaluate `ETag`, `Cache-Control`, and Range semantics. | High |
| 4 | `describeWav` reads an entire selected file to inspect a small header. | Read a bounded `file.slice(0, 65536)` header region. | High (cheap) |
| 5 | Large uploads have no progress indicator. | Add XHR upload progress; consider resumable uploads later. | Medium |
| 6 | Local session state is single-process and ephemeral. | Consider object storage with opaque IDs and signed access only when public deployment needs it. | High for public |

## 3. Reach findings

- **Legal**: the repository is MIT licensed. Users still need to evaluate codec and
  media-license obligations for their own content and tools.
- **Installability**: the package is installable from this repository, but is not
  published to a package index.
- **Landing**: the app binds loopback and has no demo, share links, or social metadata;
  public reach is currently zero.
- **Funnel**: the container is the front door. Users generally want synchronized
  vocal/instrumental playback, practice, export, or sharing rather than a `.vma` file.
- **Identity**: VMA is a container, not a source-separation system. Any future separation
  service must remain an upstream operation that supplies stems to the existing writer.

## 4. Verdict

- **As a format and library:** retain and harden the frozen contracts.
- **As a consumer product:** make the outcome the front door while keeping the container
  as a durable developer deliverable and storage contract.

## 5. Completed foundation

- MIT `LICENSE`.
- VMA v0.3 application identity, `pyproject.toml`, runtime/dev requirement files, and CI
  for Python tests plus JavaScript syntax.
- Dockerfile for a reproducible local container run.
- Version-aware V2 API/UI integration and byte-exact `extract-stream/{stream_id}`.
- Browser-native decode attempts for V1 and V2 streams without server-side transcoding or
  a custom decoder. Playability remains browser- and codec-dependent.
- Opt-in synthetic MP3, AAC/M4A, Vorbis/OGG, and Opus/OGG integration coverage when a
  suitable local FFmpeg/FFprobe installation is supplied through `VMA_REAL_CODEC_FFMPEG`.

## 6. Remaining phased plan

### Phase 1 — Reachable

- One-click deploy and a pre-loaded demo container.
- Open Graph/SEO metadata, shareable read-only session links, and a PWA shell.
- **Outcome:** a URL that can be posted, with measurable first-session activation.

### Phase 2 — Fast

- Range/caching for stream and extraction routes; cache reconstructed V1 WAVs where
  measurements justify it.
- Threadpool/queue treatment for blocking container and ZIP work.
- Bounded frontend header reads, upload progress, and then chunked/resumable uploads.
- **Outcome:** usable on a phone and a slow connection without changing stored bytes.

### Phase 3 — Open the funnel (highest leverage)

- Optional separation service (for example Demucs or an ONNX model) that turns one mixed
  upload into two stems before packaging through the existing writer.
- Keep the boundary explicit: separation is upstream; VMA still stores supplied bytes.
- **Outcome:** users without pre-existing stems can start.

### Phase 4 — Next level reach

- Publish the `vma` library with conformance vectors and a developer SDK.
- Practice-player features (per-stem tempo/pitch/loop, karaoke, language learning) and
  distribution through musician and developer communities.
- **Outcome:** developers extend it and musicians use it regularly.

## 7. Success measures

| Phase | Measure |
|---|---|
| Completed foundation | CI green; `pip install .` succeeds; V2 streams extract with matching source SHA-256. |
| 1 | Time-to-first-playback for a new visitor under 30 seconds on the demo path. |
| 2 | Median session load under five seconds on a mobile network; no event-loop stalls. |
| 3 | Share of sessions started without pre-existing stems. |
| 4 | External integrations referencing the published library. |
