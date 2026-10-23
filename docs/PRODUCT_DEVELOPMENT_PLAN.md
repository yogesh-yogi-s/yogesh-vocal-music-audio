# VMA Product Development Plan

**Status:** Product direction agreed, 23 October 2026. This document changes no application behavior or binary-format contract.

## Agreed product decisions

- **Primary product:** a private Windows creator tool. Keep hosted web as a single-process demo; heavy multi-gigabyte processing stays local. Hosted accounts and multi-replica processing are outside the initial release.
- **V3 default:** extraction restores the exact original source-file bytes, verified by a cryptographic hash. A re-encoded mode must be opt-in and clearly say that original file bytes are not preserved. Sample-exact lossless re-encoding is not acoustically lossy; label a mode **lossy** only when audio samples change.
- **First professional audience:** producers exchanging stems. Multi-stem workflows, start offsets, and lossless container export come before archival and QC tools.
- **Initial release target:** 64-bit Windows 10/11; mono/stereo audio up to 192 kHz; tracks up to 2 hours and source files up to 2 GiB each; baseline hardware of 8 GB RAM and a dual-core x64 CPU. These are validation targets, not current support claims.

## 1. Product goal and current baseline

VMA bundles pre-existing separate vocal and music streams for synchronized playback and extraction. It does not separate a mixed song into stems. The Windows desktop app is the primary product for private, large-file workflows; the hosted web app remains a single-process demo environment.

| Area | What works today | Current boundary |
|---|---|---|
| V1 container | Two PCM WAV sources; sample-aligned timing; extraction reconstructs canonical WAV | Raw PCM is large; original WAV metadata chunks and header bytes are not retained; V1 file limit is 2 GiB |
| V2 container | Stores input payloads byte-for-byte; unknown formats remain inspectable and extractable | No required payload hash; no compression; format ID alone cannot supply a decoder |
| Playback | Two tracks share one Web Audio clock, with independent gain/mute and seeking; one playable track can still run | The app fetches and decodes each entire playable stream into memory; actual codec support depends on bundled Chromium/browser |
| Creation and UI | Two source files, validation, demo, open, inspect, extract | The UI is limited to vocal + music even though the V2 format can describe more streams; large operations need better progress, cancellation, and recovery |
| Storage | Local desktop processing; bounded, temporary process sessions | Sessions expire and are removed on restart; no durable project library or job history |
| Distribution | Windows x64 ZIP bundles Python and Chromium; no user FFmpeg install required | The current ZIP is unsigned and needs a clean-machine, offline release test and signing before broad distribution |
| Hosted web | Runs on a single-process FastAPI deployment | Hosting resource caps can be far lower than the product's 500 MiB per-file ceiling; no multi-replica session design |

The existing [roadmap](ROADMAP.md) contains older deployment and test-count statements. Refresh it when one roadmap is selected as the maintained release tracker.

### Release-matrix gap to close

| Target | Current gap | Required validation |
|---|---|---|
| Windows 10/11 x64, 8 GB RAM, dual-core x64 | The packaged app has not yet completed a clean-machine test across this matrix | Offline create, open, play, seek, extract, and shutdown on representative supported machines |
| Mono/stereo, up to 192 kHz | Storage support and playback support are different; decoder behavior depends on the actual codec | Publish separate create/extract and playback matrices, including unsupported-codec extract-only behavior |
| Up to 2 hours **and** up to 2 GiB per source | Current app upload limit is 500 MiB per file; V1 limits the **whole container** to 2 GiB | Add a bounded-memory local-file path and a version capable of larger total containers; test the limits independently |
| Multiple 2 GiB stems | Default process temp budget is 8 GiB and current work may duplicate files | Measure required free disk and staging amplification; stream or reuse local files safely before claiming support |

The duration and byte ceilings are independent: a 2-hour, stereo, 192 kHz, 24-bit uncompressed track is about **8.29 GB**, so it exceeds the proposed 2 GiB per-file ceiling. The release must state this clearly and reject unsupported combinations before long work begins. Do not raise an upload limit alone and assume the larger matrix is supported.

## 2. Disadvantages to address, ranked by user impact

| Priority | Disadvantage | User impact | Proposed direction |
|---|---|---|---|
| P0 | Large PCM V1 files and duplicate temporary copies | Disk fills quickly; moving or archiving projects is slow | Measure real workloads, then specify an opt-in compressed **new version** with lossless restoration |
| P0 | Whole-file fetch and decode for playback | Long/high-resolution tracks can stall or exhaust RAM | Prototype bounded-memory playback and seeking, with sync tests before adopting an engine |
| P0 | Unclear codec playability and operation progress | A valid V2 file may extract but not play; a long create can look frozen | Preflight actual decode capability, show supported/degraded states, progress, cancel, and actionable errors |
| P1 | Temporary sessions only | Restart loses the working session | Add a local recent-project library that reopens user-selected files with explicit consent; keep file ownership and cleanup clear |
| P1 | V2 lacks mandatory integrity proof | Storage corruption may be found only when a decoder/extractor fails | Add optional sidecar hash verification now; design built-in per-stream hashes for a new version |
| P1 | Two-track UI and basic timing metadata | Real sessions often have more stems, offsets, and mix references | Multi-stem project model with precise start offsets and named roles |
| P2 | Limited metadata and quality-control tools | Handoffs require separate tools to check technical/audio properties | Add non-destructive analysis after the stem-exchange workflow works |
| P1 | Unsigned Windows distribution | Installation friction and uncertain provenance | Clean-machine test, reproducible release evidence, signed installer/update path |
| Deferred | Single-process hosted architecture | Sessions cannot safely span replicas or restarts | Keep web as a demo; revisit shared storage only if product direction changes |

These are development opportunities, not claims that current V1/V2 files are defective. Keep existing readers and extractors stable.

## 3. Quality and compatibility rules

1. **V1 is frozen.** Extraction must continue producing its canonical PCM WAV with the same samples and timing. Do not claim original WAV header or ancillary metadata byte identity.
2. **V2 is frozen.** Extraction must continue returning each stored source payload byte-for-byte. No implicit conversion, normalizing, trimming, remixing, or lossy encoding.
3. Distinguish **sample-exact audio** from **byte-exact source-file restoration** in UI, documentation, and tests. V3 defaults to byte-exact restoration. A lossless codec can preserve samples while changing file headers or non-audio chunks; describe that as **re-encoded, original bytes not preserved**, not as lossy. Reserve **lossy** for changed audio samples.
4. Preserve the existing file when processing fails or is cancelled. Validate size and boundaries before allocation, and limit expansion ratio, CPU time, memory, and temporary disk for any future compressed format.
5. Unknown codecs remain extractable. A `FORMAT_ID`, extension, or MIME label never proves playback support. A standalone app needs a working decoder for each playable codec; bundling an identifier is insufficient.
6. No quality-loss claim is made from listening alone. Verify decoded PCM sample equality where applicable and source SHA-256 equality where byte-exact restoration is promised.

## 4. Reduce container size without quality loss

The current V1 payload is raw PCM. For example, two 60-second stereo, 48 kHz, 16-bit PCM streams contain about **23.04 MB of sample bytes** before headers. Container overhead is small relative to those bytes. By contrast, a V2 containing already compressed MP3 or FLAC generally has little additional lossless compression headroom. No fixed size reduction can be guaranteed for every input.

| Candidate | What it can save | What must remain true | Recommendation |
|---|---|---|---|
| Compress raw PCM with a lossless audio codec, such as FLAC | Often useful for integer PCM; content dependent | V3 must also preserve every original WAV header/metadata byte for byte-exact restoration; unsupported PCM types fall back safely | Prototype only if full source restoration is proven |
| General reversible compression of the **entire** source file | Can preserve every WAV/MP3/other input byte on decompression | Verify source SHA-256 after extraction; store raw when compression adds size or cost | Strongest first candidate for a V3 byte-preserving mode |
| Chunked lossless storage with an index | Faster random access and bounded-memory extraction/seek | Independently bounded chunks, strict offset validation, stable sample/time mapping | Evaluate with either V3 method; essential for long tracks |
| User converts WAV to FLAC before creating V2 | Smaller input may produce a smaller V2 | V2 then preserves the **new FLAC file**, not the original WAV bytes; user must choose this explicitly | Document as an optional workflow, never automatic |
| Lossy re-encoding or normalization | Potentially much smaller | Changes the signal and violates this plan's no-quality-loss requirement | Out of scope for a lossless creation mode |

**Decision gate for V3:** build a licensed, varied benchmark corpus (speech, vocals, sparse/dense music, silence, noisy/mastered material; 16/24-bit integer PCM, float PCM, compressed sources, short and long tracks). Include 2-hour tracks and 2 GiB source files on the agreed 8 GB RAM/dual-core Windows baseline. Record per-source and aggregate compressed size, encode/decode time, peak RAM, temp disk, and random-seek latency. Choose the default only after proving useful size reduction **and** acceptable resource costs; retain an uncompressed fallback. Every default-mode extraction must match the original source SHA-256, including WAV header and metadata bytes. V3 needs its own specification, migration policy, conformance fixtures, reader/writer tests, and backward-compatible application dispatch. It must never silently reinterpret V1 or V2 bytes.

## 5. Delivery path

| Stage | Work in order | Exit evidence |
|---|---|---|
| A. Baseline and usability | Freeze representative V1/V2 fixtures and source hashes. Measure create/open/play/extract time, size, peak RAM, temp disk, and sync drift on the Windows release baseline. Add clear operation progress/cancel and actual playability messages. Complete offline clean-Windows test of the existing ZIP. | Repeatable benchmark report; no V1/V2 extraction regression; clean-machine launch, create, play, extract, shutdown evidence |
| B. Local large-file path | Prototype bounded-memory local-file creation and playback, indexed seeking, and staging that respects available disk. Compare with current Web Audio buffers under file switching, pause/resume, offsets, and one-stream fallback. | Tested 2-hour/2 GiB boundary cases on the baseline machine; measured memory/disk bounds; sample-aligned seek; no stale audio after switch |
| C. Byte-exact V3 | Write V3 proposal, threat model, and independent test vectors; prototype whole-file reversible compression and PCM-specific compression with full source reconstruction. Select by benchmark. Add integrity checks, safe fallback, and larger-total-container support. | Every default-mode stream extracts to the original SHA-256; malformed/compressed-bomb rejection; old V1/V2 fixtures unchanged |
| D. Producer stem exchange | Multiple named stems, precise start-offset editor, local project reopen, batch create/extract, and lossless container export. Keep archival/QC additions for a later stage. | Producer can package, reopen, align, and export all stems with original-byte verification and no hidden conversion |
| E. Windows product release | Sign Windows distribution; provide versioned releases, upgrade/rollback guidance, accessibility review, support diagnostics, privacy wording, and release notes. Keep hosted web as a single-process demo. | Windows 10/11 x64 clean-machine matrix, signed artifact verification, security/dependency gate, documented support and recovery procedure |

Do not assign a calendar date or advertise a compression percentage until the corpus, target hardware, and release budget are agreed. Stage B may reveal that a native decoder/player is needed for the desktop app; preserve the existing extraction path while evaluating that choice.

### Measures to track at each stage

- **Correctness:** V1 canonical sample/timing equality; V2 exact source SHA-256; V3 default exact original source SHA-256; malformed-container rejection.
- **Audio:** measured start/seek drift, pause/resume continuity, no stale sources, no unintended clipping or channel changes.
- **Resources:** output/input size ratio by codec and content, peak RAM, temp disk, encode/decode time, first-play time, seek time, and cancellation cleanup.
- **Release:** successful runs on clean Windows 10/11 x64 at the 8 GB RAM/dual-core baseline, including stated duration/file-size boundaries; offline operation, signature verification, dependency/security scan, and accessible keyboard/UI paths.

## 6. Separate workstream: music-industry production readiness

Producers exchanging stems are the first professional audience. Deliver multi-stem packaging, start offsets, and byte-exact export first; archival/QC and broader industry interchange follow. Treat standards below as interoperability targets requiring conformance testing, not as current support claims.

| Order | Capability to implement | Acceptance condition for professional use |
|---|---|---|
| 1 | **Precise session timing:** sample positions, start offsets, common sample clock, tempo/time-signature markers where useful, and explicit behavior for differing rates/lengths | Reopen and export align sample-accurately against an independently generated reference; never change an original payload without explicit choice |
| 1 | **Multi-stem exchange:** multiple named mono/stereo stems, clear roles, batch create/extract, and byte-exact V3 export | Producer can re-open a package and independently verify every original stem hash; 192 kHz and release-size boundaries are tested |
| 2 | **Broader channel/format support:** multichannel layouts, 24-bit and eligible float workflows beyond the initial mono/stereo target | Round-trip fixtures cover each advertised layout/bit depth; unsupported layouts show a safe extract-only state |
| 2 | **Archival integrity and provenance:** verification on open/export, source/version history, immutable export report | Every exported source verifies against its recorded hash; corruption is identified without altering the source |
| 2 | **Interchange formats:** Broadcast Wave metadata and large-file WAV/BW64 where justified; DAW-friendly stem export and import mapping | Validate against independent tools and fixtures, including time references and metadata; preserve unknown source chunks when byte-exact export is promised |
| 3 | **Non-destructive audio QC:** integrated loudness, loudness range, true peak, clipping, silence, polarity/phase, DC offset, and channel-balance reports | Measurements use documented algorithms, reference fixtures, and tolerances; reports never modify stored audio |
| 2 | **Rights and delivery metadata:** recording/project IDs, credits, ownership, license and usage notes, artwork references, release/export profiles | Controlled schema validation and export report; identifiers such as ISRC are entered/verified by authorized rights holders, not invented by the app |
| 3 | **Collaborative and enterprise workflows:** roles, audit log, approved revisions, secure project exchange, retention policy, backup/restore | Threat model, access-control tests, recovery drill, and clear ownership of cloud content before enabling hosted collaboration |
| 3 | **Interoperability ecosystem:** documented format/SDK, independent reader, DAW integration or interchange adapters | Two independent implementations can parse and extract the published conformance corpus |

**Industry release gate:** publish a declared supported-format matrix and interoperability test results; use representative professional sessions under load; verify sample alignment, hash-preserving extraction, metadata round trips, QC tolerances, backup/restore, licensing/provenance, and signed reproducible releases. Professional readiness is achieved only for the formats and workflows that pass these gates, not by adding UI labels alone.

### Standards and implementation references

- [FLAC format, RFC 9639](https://datatracker.ietf.org/doc/html/rfc9639) — candidate lossless integer-PCM codec; applicability and container behavior require evaluation.
- [EBU Tech 3285, Broadcast Wave Format](https://tech.ebu.ch/docs/tech/tech3285.pdf) — BWF interoperability target.
- [ITU-R BS.2088-2](https://www.itu.int/rec/R-REC-BS.2088) — large-file broadcast WAV/BW64 reference.
- [EBU R 128](https://tech.ebu.ch/publications/r128) and [ITU-R BS.1770-5](https://www.itu.int/rec/R-REC-BS.1770-5-202311-I/en) — loudness and true-peak measurement references.
- [IFPI ISRC guidance](https://isrc.ifpi.org/why-use-isrc/using-isrc) — recording identifier stewardship.

## 7. Remaining implementation decisions

The product direction and first release matrix are fixed above. Stage A can begin without changing file semantics. Resolve these narrower design questions with benchmark evidence:

1. Which local-file ingestion strategy avoids repeated 2 GiB copies while preserving safe ownership, cancellation, and cleanup?
2. Which V3 reversible compressor, chunk size, and index design meet byte-exact extraction, useful size reduction, seek speed, and the 8 GB RAM/dual-core budget?
3. What measured start/seek drift tolerance and free-disk requirement should be published for producer sessions with multiple stems?
4. Which exact Windows 10/11 builds and codecs pass independent create/extract and playback tests? Publish capability separately for each operation.
