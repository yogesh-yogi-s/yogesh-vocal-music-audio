"""Validation facade for structurally validated VMA v2 containers."""

from __future__ import annotations

from pathlib import Path

from .models import V2File
from .reader import read_vma_v2


def validate_vma_v2(vma_path: str | Path) -> V2File:
    """Validate a V2 container and return its parsed representation on success."""
    return read_vma_v2(vma_path)
