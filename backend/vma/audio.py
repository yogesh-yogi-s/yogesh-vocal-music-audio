"""Strict parser for ordinary RIFF PCM WAV source files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .format import CHUNK_HEADER, MAX_SAMPLE_RATE, RIFF_HEADER, SUPPORTED_BIT_DEPTHS, WAV_FMT
from .models import AudioFormat, VMAError

WAVE_FORMAT_EXTENSIBLE = 0xFFFE
PCM_SUBFORMAT_GUID = b"\x01\x00\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"


@dataclass(frozen=True)
class ParsedWav:
    audio: AudioFormat
    data_offset: int
    data_size: int


def _validate_pcm_descriptor(*, sample_rate: int, channels: int, bit_depth: int, sample_count: int, data_size: int) -> AudioFormat:
    if not (1 <= sample_rate <= MAX_SAMPLE_RATE) or channels not in {1, 2} or bit_depth not in SUPPORTED_BIT_DEPTHS:
        raise VMAError("VMA stream audio format is unsupported")
    if sample_count == 0:
        raise VMAError("VMA stream synchronization fields are invalid")
    bytes_per_frame = channels * (bit_depth // 8)
    if data_size != sample_count * bytes_per_frame:
        raise VMAError("VMA stream data size does not match frame count")
    return AudioFormat(sample_rate, channels, bit_depth, sample_count)


def parse_pcm_wav(path: str | Path) -> ParsedWav:
    path = Path(path)
    file_size = path.stat().st_size
    if file_size < RIFF_HEADER.size:
        raise VMAError("WAV is too small to contain a RIFF header")
    with path.open("rb") as source:
        riff, declared_size, wave = RIFF_HEADER.unpack(_read_exact(source, RIFF_HEADER.size, "RIFF header"))
        if riff != b"RIFF" or wave != b"WAVE":
            raise VMAError("only ordinary RIFF/WAVE files are supported (RF64 is not supported in v0.1)")
        if declared_size + 8 > file_size:
            raise VMAError("WAV RIFF size exceeds file boundary")
        fmt: tuple[int, int, int, int, int, int] | None = None
        data_offset: int | None = None
        data_size: int | None = None
        while source.tell() + CHUNK_HEADER.size <= file_size:
            chunk_id, chunk_size = CHUNK_HEADER.unpack(_read_exact(source, CHUNK_HEADER.size, "WAV chunk header"))
            chunk_start = source.tell()
            chunk_end = chunk_start + chunk_size
            if chunk_end > file_size:
                raise VMAError("WAV chunk exceeds file boundary")
            if chunk_id == b"fmt ":
                if chunk_size < WAV_FMT.size:
                    raise VMAError("WAV fmt chunk is too small")
                fmt_data = _read_exact(source, chunk_size, "WAV fmt chunk")
                fmt = WAV_FMT.unpack(fmt_data[:WAV_FMT.size])
                if fmt[0] == WAVE_FORMAT_EXTENSIBLE:
                    if chunk_size < 40 or int.from_bytes(fmt_data[16:18], "little") < 22:
                        raise VMAError("WAV extensible fmt chunk is incomplete")
                    if fmt_data[24:40] != PCM_SUBFORMAT_GUID:
                        raise VMAError("only PCM WAV input is supported")
                    fmt = (1, *fmt[1:])
            elif chunk_id == b"data":
                if data_offset is not None:
                    raise VMAError("WAV contains more than one data chunk")
                data_offset, data_size = chunk_start, chunk_size
            source.seek(chunk_end + (chunk_size % 2))
        if fmt is None or data_offset is None or data_size is None:
            raise VMAError("WAV must contain one fmt chunk and one data chunk")
        format_code, channels, sample_rate, byte_rate, block_align, bit_depth = fmt
        if format_code != 1:
            raise VMAError("only uncompressed PCM WAV input is supported")
        if channels not in {1, 2}:
            raise VMAError("VMA v0.1 supports mono or stereo WAV input only")
        if bit_depth not in SUPPORTED_BIT_DEPTHS:
            raise VMAError("supported PCM bit depths are 8, 16, 24, and 32")
        expected_align = channels * (bit_depth // 8)
        if block_align != expected_align or byte_rate != sample_rate * expected_align:
            raise VMAError("WAV format fields are inconsistent")
        if sample_rate <= 0 or sample_rate > 384_000:
            raise VMAError("WAV sample rate is outside VMA v0.1 limits")
        if data_size % block_align:
            raise VMAError("WAV data size is not aligned to complete PCM frames")
        return ParsedWav(AudioFormat(sample_rate, channels, bit_depth, data_size // block_align), data_offset, data_size)


def _read_exact(source, size: int, name: str) -> bytes:
    value = source.read(size)
    if len(value) != size:
        raise VMAError(f"unexpected end of file while reading {name}")
    return value
