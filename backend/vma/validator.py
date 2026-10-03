from pathlib import Path

from .models import VMAFile
from .reader import read_vma


def validate_vma(vma_path: str | Path) -> VMAFile:
    """Validate a VMA file and return its parsed representation on success."""
    return read_vma(vma_path)
