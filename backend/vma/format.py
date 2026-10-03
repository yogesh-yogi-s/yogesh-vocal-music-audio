"""Binary layout constants and WAV helpers for VMA v0.1."""

from __future__ import annotations

import struct

MAGIC = b"VMAF"
VERSION = 1
HEADER_STRUCT = struct.Struct("<4sHHIIIIQ")
STREAM_STRUCT = struct.Struct("<IHHIHHqQQQ16s")
HEADER_SIZE = HEADER_STRUCT.size  # 32 bytes
STREAM_ENTRY_SIZE = STREAM_STRUCT.size  # 64 bytes
MAX_STREAMS = 16
MAX_METADATA_SIZE = 64 * 1024
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024
MAX_SAMPLE_RATE = 384_000
SUPPORTED_BIT_DEPTHS = {8, 16, 24, 32}
RIFF_HEADER = struct.Struct("<4sI4s")
CHUNK_HEADER = struct.Struct("<4sI")
WAV_FMT = struct.Struct("<HHIIHH")


def wav_header(*, sample_rate: int, channels: int, bit_depth: int, data_size: int) -> bytes:
    """Build a canonical 44-byte PCM RIFF/WAV header."""
    byte_rate = sample_rate * channels * (bit_depth // 8)
    block_align = channels * (bit_depth // 8)
    riff_size = 36 + data_size
    if riff_size > 0xFFFFFFFF:
        raise ValueError("WAV output exceeds RIFF 4 GiB size limit")
    return (
        RIFF_HEADER.pack(b"RIFF", riff_size, b"WAVE")
        + CHUNK_HEADER.pack(b"fmt ", 16)
        + WAV_FMT.pack(1, channels, sample_rate, byte_rate, block_align, bit_depth)
        + CHUNK_HEADER.pack(b"data", data_size)
    )
