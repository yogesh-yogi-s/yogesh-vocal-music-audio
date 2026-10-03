# VMA v2 binary format

## 1. Scope and design principles

VMA v2 is a versioned binary container for opaque source-file byte streams. A stream payload is the exact byte sequence supplied to the writer. A conforming extractor writes that sequence verbatim; it does not decode, transcode, separate, normalize, decompress, or otherwise transform the source file.

VMA is a container, not an audio codec or source-separation system. Application-level decoding, mixing, playback, and labels such as Vocal and Music / Instrumental are outside this binary contract.

All multi-byte integers are little-endian. All byte offsets are absolute from the beginning of the file. All reserved fields and flags defined as zero in this specification must be zero.

## 2. V1 and V2 boundary

V1 remains frozen. It stores PCM data chunks and uses V1 stream semantics. V2 stores supplied source-file bytes directly and supports multiple generic stream roles.

The shared magic is ASCII `VMAF`. Readers dispatch on the unsigned 16-bit version field:

| Version | Reader action |
|---:|---|
| `1` | Use the V1 parser and V1 semantics exactly as specified in [VMA_FORMAT.md](VMA_FORMAT.md). |
| `2` | Use this specification. |
| Other | Reject as an unsupported version. Do not partially parse, decode, or promise extraction. |

A V1 reader must reject a V2 file as an unsupported version. A V2 reader must support V1 dispatch in addition to V2 parsing.

## 3. File layout

| Region | Offset | Size |
|---|---:|---:|
| Fixed header | `0` | `56` bytes |
| Container metadata | `metadata_offset` | `metadata_size` bytes |
| Descriptor table | `descriptor_table_offset` | `descriptor_table_size` bytes |
| Stream payloads | descriptor-defined | descriptor-defined |

Regions may be separated by unreferenced padding. Metadata, descriptor table, and every payload range must be entirely within the physical file and must not overlap one another. Stream payload ranges must not overlap.

### 3.1 Fixed header (56 bytes)

`<4s HH I I Q Q Q Q I I>`

| Field | Size | Required value / meaning |
|---|---:|---|
| Magic | 4 | `VMAF` |
| Version | 2 | `2` |
| Header size | 2 | `56` |
| Stream count | 4 | Number of descriptors in the descriptor table |
| Header flags | 4 | `0` |
| Metadata offset | 8 | Absolute metadata offset; `56` when metadata is absent or present |
| Metadata size | 8 | `0` for no metadata, otherwise byte length |
| Descriptor table offset | 8 | `metadata_offset + metadata_size` |
| Descriptor table size | 8 | Byte length of all serialized descriptors |
| Reserved 1 | 4 | `0` |
| Reserved 2 | 4 | `0` |

The header establishes all metadata and descriptor-table boundaries. V2 has no header extension area: a `header_size` other than `56` is invalid.

### 3.2 Container metadata

Container metadata is optional. When `metadata_size` is non-zero, it must be a UTF-8 JSON object containing the integer member `schema_version` with value `1`. Unknown metadata members are permitted and have application-level meaning only. Readers must not require any unknown member to extract streams.

The metadata schema is independent of the binary version. Changing required metadata semantics requires a new metadata `schema_version`; it does not change the V2 binary layout.

## 4. V2 stream descriptor

Descriptors are serialized consecutively in the descriptor table. Each descriptor is a 48-byte fixed part immediately followed by exactly `format_info_size` bytes of FORMAT_INFO.

Fixed descriptor: `<I H H H H q Q Q Q I>`

| Field | Size | Meaning |
|---|---:|---|
| Stream ID | 4 | Unique, non-zero unsigned identifier |
| Role | 2 | Generic stream role; see section 6 |
| Stream flags | 2 | Must be `0` in V2 |
| Format ID | 2 | Format namespace value; see section 5 |
| Reserved | 2 | `0` |
| Start time | 8 | Signed presentation start in nanoseconds; V2 writers use non-negative values |
| Duration | 8 | Presentation duration in nanoseconds; `0` means unknown/not supplied |
| Payload offset | 8 | Absolute payload byte offset |
| Payload size | 8 | Exact stored source-byte count |
| FORMAT_INFO size | 4 | Byte length of the immediately following TLV block |

`descriptor_table_size` must equal the sum of `48 + format_info_size` for exactly `stream_count` descriptors. Stream IDs, not descriptor positions, identify streams.

## 5. FORMAT_ID namespace

| Range | Allocation |
|---|---|
| `0x0000` | Unknown / no declared format |
| `0x0001–0x0FFF` | Standardized external formats |
| `0x1000–0x1FFF` | VMA-defined formats/codecs |
| `0x2000–0xEFFF` | Reserved |
| `0xF000–0xFFFE` | Private / experimental |
| `0xFFFF` | Reserved future escape |

An unknown, reserved, or private FORMAT_ID does not invalidate an otherwise valid V2 container. Readers must expose its descriptor and allow exact payload extraction. They must not claim decoding or playback support for it. Writers may use `0x0000` when no registry identifier is known.

## 6. Generic stream roles

| Value | Role | Meaning |
|---:|---|---|
| `0x0000` | `UNKNOWN` | No declared role |
| `0x0001` | `AUDIO_PRIMARY` | Primary audio stream for an application-defined presentation |
| `0x0002` | `AUDIO_SUPPLEMENTAL` | Supplemental audio stream |
| `0x0003` | `METADATA_SIDECAR` | Non-audio sidecar payload |
| `0x0004–0xFFFF` | Reserved | Future roles |

Vocal and Music / Instrumental are application-level labels, not V2 role values. A reader must retain and extract a stream with an unknown role but must not infer playback behavior from that role.

## 7. Stream flags

V2 defines no transformations. Stream flags must be zero. In particular, V2 does not define container-level `COMPRESSED` or `ENCRYPTED` flags.

An externally compressed source file, such as an MP3, is stored as its supplied bytes; this is not a V2 transformation. A non-zero stream-flags field invalidates a V2 file. Future transformations require a future binary version with explicit transform and key rules.

## 8. FORMAT_INFO TLV block

FORMAT_INFO is a bounded sequence of TLVs:

`[type:u8][length:u16 LE][value:length bytes]`

`format_info_size` is the sole boundary. A reader starts immediately after the fixed descriptor and must consume exactly that many bytes. No terminator, alignment, or padding is permitted inside the block.

### 8.1 Defined base types

| Base type | Name | Value encoding |
|---:|---|---|
| `0x01` | `SOURCE_FILENAME` | Non-empty UTF-8 basename; no path semantics |
| `0x02` | `MEDIA_TYPE` | Non-empty ASCII media type |
| `0x03` | `FILE_EXTENSION` | Non-empty ASCII extension without a leading dot |
| `0x04–0x7F` | Reserved | No V2 meaning |

Types `0x00–0x7F` are non-critical. A type with bit `0x80` set is critical and its base type is `type & 0x7F`. Writers must not emit a critical TLV unless its base type is defined by the V2 specification or a future versioned extension.

Unknown well-formed non-critical TLVs must be ignored for semantic interpretation. Unknown well-formed critical TLVs mean the stream is semantically unsupported for decoding/playback, but the descriptor remains readable and its payload remains exactly extractable. A critical TLV never blocks opaque extraction.

An incomplete TLV header, a declared length exceeding remaining FORMAT_INFO bytes, invalid required text encoding, or failure to consume FORMAT_INFO exactly invalidates the V2 file.

## 9. Payload and exact extraction

For each stream, the payload is exactly `payload_size` bytes beginning at `payload_offset`. A conforming writer copies input bytes without alteration. A conforming extractor writes that range without alteration.

Container metadata, descriptor metadata, source paths, timestamps, FORMAT_ID, and role must not alter extraction bytes. V2 does not require a checksum; structural validation establishes safe bounds but does not provide cryptographic or storage-integrity assurance.

## 10. Timing, ordering, and IDs

`start_time` and `duration` are generic presentation metadata in nanoseconds. They are not required to match a particular media format's internal timing and do not alter payload bytes. A `duration` of zero is unknown/not supplied.

Descriptor order is non-semantic. Writers must serialize descriptors by ascending `stream_id` for deterministic output. Readers must accept any order, require unique non-zero IDs, and resolve streams by ID. Payload offset order is non-semantic.

## 11. Reference implementation architecture

_This section records implementation architecture decisions. Nothing here changes the V2 binary format._

### 11.1 Version dispatcher

The reference implementation places unified version dispatch in `backend/vma/dispatch.py`. Responsibilities:

| Entry point | Responsibility |
|---|---|
| `read_vma()` | Frozen V1 reader. Unchanged from the V1 specification. |
| `read_vma_v2()` | V2-specific reader. Implements this specification. |
| `read_vma_any()` | Unified dispatcher. Reads the shared magic/version field, routes to `read_vma()` for version `1`, to `read_vma_v2()` for version `2`, and rejects all other version values as unsupported. |

The dispatcher reads only the leading 6 bytes (magic 4 + version u16 LE) before routing. It does not partially parse the remainder. V1 behavior is not altered; a V1 file passed to `read_vma_any()` is routed to the frozen V1 reader and produces identical results to calling `read_vma()` directly.

## 12. Validation and resource limits

A V2 reader must reject a file with invalid magic/version/header size, non-zero header or stream flags/reserved fields, inconsistent region boundaries, malformed metadata, malformed descriptors or TLVs, duplicate/zero IDs, out-of-file ranges, overlapping metadata/table/payload regions, or a descriptor-table byte count inconsistent with stream count.

Readers must enforce documented local resource limits before allocating memory, reading metadata/TLV blocks, or extracting payloads. Limits are implementation policy and must not reinterpret valid stored bytes. Writers must reject inputs they cannot represent safely.

### 12.1 Reference stream-count limit

The reference implementation enforces `MAX_STREAMS_V2 = 64`. A V2 reader must reject a file whose `stream_count` header field exceeds this limit before allocating descriptor-table memory or reading any descriptor. This is a resource-safety guard, not a binary-format semantic maximum. The V2 format itself imposes no upper bound on stream count beyond the constraints of a valid `stream_count` u32 field and file-size limits. Future implementations may choose a different documented resource limit; they must document it clearly and must not reinterpret stored bytes as invalid solely because of a limit difference.

## 13. Reader and writer conformance

A conforming V2 writer must:

- Write the fixed header and descriptor table exactly as specified.
- Store each source payload byte-for-byte.
- Emit zero flags and reserved fields.
- Serialize descriptors by ascending stream ID.
- Use known format/role/TLV values only when their semantics are true.

A conforming V2 reader must:

- Dispatch V1 and V2 by version.
- Validate all structural boundaries before extraction.
- Enforce its documented resource limits (see section 12.1) before allocating descriptor memory.
- Preserve opaque access to unknown FORMAT_IDs, roles, and non-critical TLVs.
- Permit opaque extraction for streams with unknown critical TLVs while declining semantic decoding/playback.
- Extract payload bytes verbatim.

## 14. Registry governance and future extension

The binary specification freezes FORMAT_ID ranges and unknown-value behavior. A separately maintained append-only registry allocates standardized external and VMA-defined FORMAT_ID values. Each allocation records its numeric value, stable name, defining reference, and status. Allocations are never reassigned.

No V2 reserved field, header flag, stream flag, role, or FORMAT_INFO base type may acquire new V2 semantics after publication. Binary-layout, transformation, or interpretation changes require a future version. Future readers may add knowledge of a registered value without changing a V2 file's opaque extraction behavior.
