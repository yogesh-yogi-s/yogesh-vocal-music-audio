from __future__ import annotations

from pathlib import Path

from .format import wav_header
from .models import StreamType, VMAFile
from .reader import read_vma


def extract_vocal(vma_path: str | Path, output_path: str | Path) -> Path:
    return _extract(read_vma(vma_path), StreamType.VOCAL, Path(output_path))


def extract_music(vma_path: str | Path, output_path: str | Path) -> Path:
    return _extract(read_vma(vma_path), StreamType.MUSIC, Path(output_path))


def extract_all(vma_path: str | Path, output_directory: str | Path) -> tuple[Path, Path]:
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    container = read_vma(vma_path)
    return (
        _extract(container, StreamType.VOCAL, directory / "vocal.wav"),
        _extract(container, StreamType.MUSIC, directory / "music.wav"),
    )


def _extract(container: VMAFile, stream_type: StreamType, output_path: Path) -> Path:
    stream = container.stream_for(stream_type)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with container.path.open("rb") as source, output_path.open("wb") as output:
        output.write(wav_header(
            sample_rate=stream.audio.sample_rate, channels=stream.audio.channels,
            bit_depth=stream.audio.bit_depth, data_size=stream.data_size,
        ))
        source.seek(stream.data_offset)
        remaining = stream.data_size
        while remaining:
            block = source.read(min(1024 * 1024, remaining))
            if not block:
                raise RuntimeError("validated VMA payload ended unexpectedly")
            output.write(block)
            remaining -= len(block)
    return output_path
