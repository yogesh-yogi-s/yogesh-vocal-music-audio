"""Append-only, data-only registry for VMA v2 FORMAT_ID allocations."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import FormatEntry, FormatIdRange, FormatLookup, RegistryStatus


class RegistryError(ValueError):
    """Raised when an explicit FORMAT_ID allocation violates registry policy."""


def classify_format_id(format_id: int) -> FormatIdRange:
    """Classify any raw u16 FORMAT_ID without requiring it to be registered."""
    if not isinstance(format_id, int) or not 0 <= format_id <= 0xFFFF:
        raise RegistryError("FORMAT_ID must be an unsigned 16-bit integer")
    if format_id == 0x0000:
        return FormatIdRange.UNKNOWN
    if format_id <= 0x0FFF:
        return FormatIdRange.STANDARDIZED_EXTERNAL
    if format_id <= 0x1FFF:
        return FormatIdRange.VMA_DEFINED
    if format_id <= 0xEFFF:
        return FormatIdRange.RESERVED
    if format_id <= 0xFFFE:
        return FormatIdRange.PRIVATE_EXPERIMENTAL
    return FormatIdRange.FUTURE_ESCAPE


@dataclass(frozen=True)
class FormatRegistry:
    """An immutable registry; additions return a new registry in append order."""

    entries: tuple[FormatEntry, ...] = ()
    _by_id: dict[int, FormatEntry] = field(init=False, repr=False, compare=False)
    _by_name: dict[str, FormatEntry] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_id: dict[int, FormatEntry] = {}
        by_name: dict[str, FormatEntry] = {}
        for entry in self.entries:
            self._validate_entry(entry, by_id, by_name)
            by_id[entry.format_id] = entry
            by_name[entry.canonical_name] = entry
        object.__setattr__(self, "_by_id", by_id)
        object.__setattr__(self, "_by_name", by_name)

    @staticmethod
    def _validate_entry(
        entry: FormatEntry,
        by_id: dict[int, FormatEntry],
        by_name: dict[str, FormatEntry],
    ) -> None:
        if not isinstance(entry, FormatEntry):
            raise RegistryError("registry entries must be FormatEntry instances")
        allocation_range = classify_format_id(entry.format_id)
        if allocation_range not in {FormatIdRange.STANDARDIZED_EXTERNAL, FormatIdRange.VMA_DEFINED}:
            raise RegistryError("FORMAT_ID allocations are limited to standardized external or VMA-defined ranges")
        if not entry.canonical_name or not entry.reference:
            raise RegistryError("FORMAT_ID allocations require canonical_name and reference")
        if not isinstance(entry.status, RegistryStatus):
            raise RegistryError("FORMAT_ID allocations require a registry status")
        if entry.media_type == "":
            raise RegistryError("media_type must be omitted or non-empty")
        if entry.format_id in by_id:
            raise RegistryError("FORMAT_ID allocations are append-only and cannot be reassigned")
        if entry.canonical_name in by_name:
            raise RegistryError("FORMAT_ID canonical names must be unique")

    def append(self, entry: FormatEntry) -> FormatRegistry:
        """Return a registry with one explicit new allocation appended."""
        return FormatRegistry(self.entries + (entry,))

    def lookup(self, format_id: int) -> FormatLookup:
        """Return a known or opaque-unknown lookup result for a raw u16 ID."""
        return FormatLookup(format_id, classify_format_id(format_id), self._by_id.get(format_id))


# `RIFF_WAVE` identifies only the RIFF form whose form type is WAVE.  It does
# not assert PCM, a WAVE wFormatTag, or any decoder, playback, or encoder.
FORMAT_REGISTRY = FormatRegistry((
    FormatEntry(
        format_id=0x1000,
        canonical_name="RIFF_WAVE",
        reference=(
            "Microsoft RIFF documentation (RIFF form type WAVE); "
            "IANA WAVE and AVI Codec Registries"
        ),
        status=RegistryStatus.APPROVED,
        media_type="audio/vnd.wave",
    ),
))
