"""VMA container library.

VMA v0.1 (V1) is a frozen PCM-WAV two-stream container.  VMA v0.2 (V2) is a
frozen opaque source-byte container.  ``read_vma_any`` dispatches on the shared
magic and version field; the V1 and V2 readers, writers, and extractors remain
frozen and are re-exported here for application and third-party use.
"""

from .dispatch import peek_vma_version, read_vma_any
from .extractor import extract_all, extract_music, extract_vocal
from .reader import read_vma
from .validator import validate_vma
from .writer import create_vma
from .v2.extractor import extract_all_v2, extract_stream_v2
from .v2.format_info import FormatInfoTLV
from .v2.models import V2File, V2Header, V2Stream, V2StreamDescriptor
from .v2.reader import read_vma_v2
from .v2.writer import V2StreamInput, create_vma_v2, write_vma_v2

__all__ = [
    # V1 (frozen)
    "create_vma",
    "read_vma",
    "extract_vocal",
    "extract_music",
    "extract_all",
    "validate_vma",
    # Version dispatch
    "read_vma_any",
    "peek_vma_version",
    # V2 (frozen)
    "create_vma_v2",
    "write_vma_v2",
    "read_vma_v2",
    "extract_stream_v2",
    "extract_all_v2",
    "V2StreamInput",
    "FormatInfoTLV",
    "V2File",
    "V2Header",
    "V2Stream",
    "V2StreamDescriptor",
]
