"""VMA v2 foundational models and binary wire helpers.

This package is intentionally isolated from the frozen VMA v1 implementation.
"""

from .models import V2File, V2Header, V2Stream, V2StreamDescriptor

__all__ = ["V2File", "V2Header", "V2Stream", "V2StreamDescriptor"]
