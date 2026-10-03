from pathlib import Path

from vma.audio import parse_pcm_wav


def pcm_payload(path: Path) -> tuple[object, bytes]:
    parsed = parse_pcm_wav(path)
    with path.open("rb") as source:
        source.seek(parsed.data_offset)
        return parsed.audio, source.read(parsed.data_size)


def assert_stream_matches_wav(stream, source_path: Path) -> None:
    audio, payload = pcm_payload(source_path)
    assert stream.audio.sample_rate == audio.sample_rate
    assert stream.audio.channels == audio.channels
    assert stream.audio.bit_depth == audio.bit_depth
    assert stream.audio.sample_count == audio.sample_count
    assert stream.data_size == len(payload)
