#!/usr/bin/env python3
"""Generate a local VMA v2 fixture for manual browser verification.

This is a developer tool, not application code.  It reuses the exact tested
constructors and metadata conventions already exercised by the test suite:

* ``conftest.write_pcm_wav`` (tests/conftest.py) for the valid PCM WAV payload.
* ``vma.v2.writer.create_vma_v2`` / ``V2StreamInput`` and
  ``vma.v2.format_info.FormatInfoTLV`` for the container.
* The same MP3-signature opaque payload as ``tests/test_vma_api_v2.py``.
* The application-level ``stream_labels`` metadata key consumed by
  ``backend/app/vma_service.py`` so the UI shows friendly labels.

Output goes to ``tmp/vma-ui-test/`` relative to the repository root and is not
part of the production source tree.  Nothing here changes the VMA binary
format.

Usage:
    python scripts/make_v2_ui_fixture.py
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Mirror tests/conftest.py so the tested helpers import the same way.
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from conftest import write_pcm_wav  # noqa: E402
from vma.v2.format_info import (  # noqa: E402
    FILE_EXTENSION,
    MEDIA_TYPE,
    SOURCE_FILENAME,
    FormatInfoTLV,
)
from vma.v2.writer import V2StreamInput, create_vma_v2  # noqa: E402

OUTPUT_DIR = ROOT / "tmp" / "vma-ui-test"

# Identical to the MP3-signature opaque payload in tests/test_vma_api_v2.py.
MP3_BYTES = (
    b"ID3\x03\x00\x00\x00\x00\x00\x21"
    + bytes(range(64))
    + b"\xff\xfb\x90\x00tail"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    vocal_wav = OUTPUT_DIR / "vocal.wav"
    write_pcm_wav(vocal_wav, channels=1, sample_rate=44_100, bit_depth=16, frames=64)

    song_mp3 = OUTPUT_DIR / "song.mp3"
    song_mp3.write_bytes(MP3_BYTES)

    container = create_vma_v2(
        [
            V2StreamInput(
                stream_id=1,
                source_path=vocal_wav,
                role=1,  # AUDIO_PRIMARY
                format_id=0x1000,  # RIFF_WAVE
                format_info=(
                    FormatInfoTLV(SOURCE_FILENAME, b"vocal.wav"),
                    FormatInfoTLV(MEDIA_TYPE, b"audio/wav"),
                    FormatInfoTLV(FILE_EXTENSION, b"wav"),
                ),
            ),
            V2StreamInput(
                stream_id=2,
                source_path=song_mp3,
                role=2,  # AUDIO_SUPPLEMENTAL
                format_id=0x0000,  # unknown/opaque
                format_info=(
                    FormatInfoTLV(SOURCE_FILENAME, b"song.mp3"),
                    FormatInfoTLV(MEDIA_TYPE, b"audio/mpeg"),
                    FormatInfoTLV(FILE_EXTENSION, b"mp3"),
                ),
            ),
        ],
        OUTPUT_DIR / "mixed.vma",
        metadata={
            "schema_version": 1,
            "title": "Mixed UI Fixture",
            "artist": "Synthetic tests",
            "stream_labels": {"1": "Vocal", "2": "Music"},
        },
    )

    print("Fixture written to:", OUTPUT_DIR)
    for path in (vocal_wav, song_mp3, container):
        print(f"  {path.name:<12} {path.stat().st_size:>8} bytes  sha256={_sha256(path)}")
    print("\nExpected SHA-256 in the UI:")
    print(f"  vocal.wav (stream 1): {_sha256(vocal_wav)}")
    print(f"  song.mp3  (stream 2): {_sha256(song_mp3)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
