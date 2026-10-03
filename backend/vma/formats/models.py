"""Models for the VMA FORMAT_ID registry; no decoding semantics live here."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FormatIdRange(str, Enum):
    UNKNOWN = "unknown"
    STANDARDIZED_EXTERNAL = "standardized_external"
    VMA_DEFINED = "vma_defined"
    RESERVED = "reserved"
    PRIVATE_EXPERIMENTAL = "private_experimental"
    FUTURE_ESCAPE = "future_escape"


class RegistryStatus(str, Enum):
    PROVISIONAL = "provisional"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


@dataclass(frozen=True)
class FormatEntry:
    """One explicit, stable allocation from an allowed registry range."""

    format_id: int
    canonical_name: str
    reference: str
    status: RegistryStatus
    media_type: str | None = None


@dataclass(frozen=True)
class FormatLookup:
    """Lookup result that retains a raw ID even when no allocation is known."""

    format_id: int
    range: FormatIdRange
    entry: FormatEntry | None

    @property
    def known(self) -> bool:
        return self.entry is not None
