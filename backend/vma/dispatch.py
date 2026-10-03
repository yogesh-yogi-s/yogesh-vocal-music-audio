"""Version dispatch for VMA containers without changing V1 reader behavior."""

from __future__ import annotations

import struct
from pathlib import Path

from .format import MAGIC
from .models import VMAError, VMAFile
from .reader import read_vma
from .v2.models import V2File
from .v2.reader import read_vma_v2


_DISPATCH_PREFIX_SIZE = 6  # shared magic (4) plus little-endian version (u16)
_VERSION_STRUCT = struct.Struct("<H")


def read_vma_any(vma_path: str | Path) -> VMAFile | V2File:
    """Peek at a VMA version and route it to the corresponding frozen reader."""
    path = Path(vma_path)
    with path.open("rb") as source:
        prefix = source.read(_DISPATCH_PREFIX_SIZE)
    if len(prefix) != _DISPATCH_PREFIX_SIZE:
        raise VMAError("VMA is too small to contain magic and version")
    if prefix[:4] != MAGIC:
        raise VMAError("invalid VMA magic bytes")

    version = _VERSION_STRUCT.unpack(prefix[4:])[0]
    if version == 1:
        return read_vma(path)
    if version == 2:
        return read_vma_v2(path)
    raise VMAError(f"unsupported VMA version {version}")
