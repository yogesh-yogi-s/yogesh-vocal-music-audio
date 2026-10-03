# VMA FORMAT_ID Registry

## Scope

This append-only registry records explicit VMA v2 `FORMAT_ID` allocations. It is an application/documentation artifact governed by the ranges and unknown-value rules in [VMA_FORMAT_V2.md](VMA_FORMAT_V2.md); it does not change the V2 binary layout.

The registry identifies formats only. It does not promise a decoder, encoder, player, MIME-sniffing behavior, or media validation. V2 containers continue to store and extract opaque source bytes exactly, including payloads whose IDs are unknown to this registry.

## Allocation ranges

| Range | Registry treatment |
|---|---|
| `0x0000` | Unknown/no declared format; never allocated. |
| `0x0001–0x0FFF` | Standardized external formats; allocation requires an external defining reference. |
| `0x1000–0x1FFF` | VMA-defined formats/codecs; allocation requires an approved VMA defining reference. |
| `0x2000–0xEFFF` | Reserved; never allocated in V2. |
| `0xF000–0xFFFE` | Private/experimental; not registered as stable allocations. |
| `0xFFFF` | Future escape; never allocated in V2. |

## Governance

- Allocations are explicit documentation changes; no identifier is generated automatically.
- The numeric ID and canonical name are each unique and never reassigned.
- Each entry records a canonical name, defining reference/source, status, and optional media type.
- Status is one of `provisional`, `approved`, or `deprecated`. Deprecation does not free an ID or name for reuse.
- An allocation must state only semantics that are true. Recognition, decoding, playback, and encoding support are separate capabilities.

## Current allocations

| FORMAT_ID | Canonical name | Status | Media type | Reference/source |
|---:|---|---|---|---|
| `0x1000` | `RIFF_WAVE` | `approved` | `audio/vnd.wave` | [Microsoft RIFF documentation](https://learn.microsoft.com/en-us/windows/win32/xaudio2/resource-interchange-file-format--riff-) (RIFF form type `WAVE`); [IANA WAVE and AVI Codec Registries](https://www.iana.org/assignments/wave-avi-codec-registry) |

`RIFF_WAVE` identifies the RIFF/WAVE container only. It does not imply PCM, a particular WAVE `wFormatTag`, decoder availability, playback availability, or encoding support.

## Lookup behavior

Any raw unsigned 16-bit ID is representable. A lookup for `0x0000`, a reserved value, a private value, the future escape value, or an unlisted allocation returns an unknown result rather than an error. Unknown values remain valid opaque V2 stream metadata and do not prevent extraction.
