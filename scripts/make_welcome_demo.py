"""Generate the bundled, redistributable VMA welcome demo.

The two stems are deterministic square-wave tones created entirely in this
script. No recording or third-party media is used.
"""

from __future__ import annotations

import hashlib
import struct
import sys
import tempfile
import wave
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.vma import writer as vma_writer  # noqa: E402


OUTPUT = ROOT / "backend" / "app" / "assets" / "welcome-demo.vma"
SAMPLE_RATE = 22_050
FRAME_COUNT = SAMPLE_RATE * 2


class _FixedDateTime:
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 1, 1, tzinfo=tz or UTC)


def _square_tone(frequency: int, amplitude: int, *, pulsed: bool) -> bytes:
    samples = bytearray()
    pulse_frames = SAMPLE_RATE // 4
    for frame in range(FRAME_COUNT):
        active = not pulsed or (frame // pulse_frames) % 2 == 0
        positive = (frame * frequency * 2 // SAMPLE_RATE) % 2 == 0
        sample = amplitude if positive else -amplitude
        samples.extend(struct.pack("<h", sample if active else 0))
    return bytes(samples)


def _write_wav(path: Path, samples: bytes) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(samples)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vma-welcome-demo-") as directory:
        work = Path(directory)
        vocal = work / "demo-vocal.wav"
        music = work / "demo-music.wav"
        _write_wav(vocal, _square_tone(440, 8_000, pulsed=True))
        _write_wav(music, _square_tone(220, 5_000, pulsed=False))

        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        original_datetime = vma_writer.datetime
        try:
            vma_writer.datetime = _FixedDateTime
            vma_writer.create_vma(
                vocal,
                music,
                OUTPUT,
                {"title": "VMA Welcome Demo", "artist": "Synthetic VMA tones"},
            )
        finally:
            vma_writer.datetime = original_datetime

    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    print(f"Generated {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size} bytes, sha256={digest})")


if __name__ == "__main__":
    main()
