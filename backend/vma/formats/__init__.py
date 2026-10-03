"""Data-only FORMAT_ID registry foundation for VMA applications."""

from .models import FormatEntry, FormatIdRange, FormatLookup, RegistryStatus
from .identify import identify_format
from .registry import FORMAT_REGISTRY, FormatRegistry, RegistryError, classify_format_id
from .wave_probe import WaveProbeResult, probe_riff_wave

__all__ = [
    "FORMAT_REGISTRY",
    "FormatEntry",
    "FormatIdRange",
    "FormatLookup",
    "FormatRegistry",
    "RegistryError",
    "RegistryStatus",
    "WaveProbeResult",
    "classify_format_id",
    "identify_format",
    "probe_riff_wave",
]
