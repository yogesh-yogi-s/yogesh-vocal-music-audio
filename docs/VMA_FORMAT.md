# VMA v0.1 binary format

VMA is a little-endian, lossless audio container. Version 1 stores two raw PCM streams: one Vocal and one Music stream. It is a container, not an audio codec.

## File layout

| Offset | Size | Content |
|---|---:|---|
| 0 | 32 | Fixed header |
| 32 | `metadata_size` | UTF-8 JSON metadata |
| variable | `stream_count × 64` | Stream table |
| `header_size` | variable | Audio payloads at their absolute table offsets |

All integers are unsigned little-endian unless stated otherwise. Writers must set every reserved field to zero; v0.1 readers reject non-zero reserved fields.

### Fixed header (32 bytes)

`<4s HH IIII Q>`

| Field | Size | Value |
|---|---:|---|
| Magic | 4 | ASCII `VMAF` |
| Version | 2 | `1` |
| Reserved | 2 | `0` |
| Header size | 4 | `32 + metadata_size + stream_count × 64` |
| Stream count | 4 | `2` in v0.1 |
| Metadata size | 4 | byte length of JSON metadata |
| Stream entry size | 4 | `64` |
| Flags/reserved | 8 | `0` |

Metadata is a UTF-8 encoded JSON object. v0.1 writers use `title`, `artist`, `vocal_filename`, `music_filename`, and `created_utc`; unknown JSON keys are permitted. Metadata is limited to 64 KiB.

### Stream entry (64 bytes)

`<I HH I HH q Q Q Q 16s>`

| Field | Size | Meaning |
|---|---:|---|
| Stream ID | 4 | Unique non-zero identifier; v0.1 writes 1 then 2 |
| Stream type | 2 | 1 = VOCAL, 2 = MUSIC |
| Codec | 2 | 1 = `PCM_WAV_LE` |
| Sample rate | 4 | Frames per second |
| Channels | 2 | 1 mono or 2 stereo |
| Bit depth | 2 | 8, 16, 24, or 32 |
| Start sample | 8 | Signed native-rate frame offset on the shared playback timeline; non-negative in v0.1 |
| Sample count | 8 | PCM frame count |
| Data offset | 8 | Absolute byte offset from the beginning of the VMA file |
| Data size | 8 | Payload byte length |
| Reserved | 16 | All zero |

`PCM_WAV_LE` payloads are the exact bytes from the WAV `data` chunk: 8-bit samples use standard unsigned PCM, and 16/24/32-bit samples use little-endian signed PCM. The payload excludes RIFF/WAV headers. An extracted WAV is rebuilt with a canonical 44-byte PCM RIFF header, so metadata chunks in the source WAV are intentionally not preserved.

## Synchronization

The playback start time for a stream is `start_sample / sample_rate`. A stream duration is `sample_count / sample_rate`. A mixer schedules each stream against the same clock at its start time. This permits different native sample rates without resampling the stored source data. v0.1 creation writes zero start samples, but readers must accept non-negative offsets.

## Required validation

Readers must reject invalid magic/version, non-zero reserved fields, inconsistent header sizing, stream count other than two, entry size other than 64, metadata larger than 64 KiB or invalid JSON, unsupported enums/audio formats, zero frame count, negative start samples, data-size/frame-size mismatch, data before `header_size`, ranges beyond the physical file, duplicate IDs/types, and overlapping data ranges. The implementation also limits VMA files to 2 GiB and sample rates to 384 kHz.
