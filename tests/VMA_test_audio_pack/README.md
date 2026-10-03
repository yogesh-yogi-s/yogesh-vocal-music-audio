# VMA Synthetic Audio Test Pack

These WAV files are fully synthetic test fixtures. They are not recordings of real people,
songs, or copyrighted music.

## Test cases

1. `01_equal_10s` — vocal 10s, music 10s
2. `02_music_longer` — vocal 10s, music 15s
3. `03_vocal_longer` — vocal 15s, music 10s
4. `04_large_difference` — vocal 5s, music 20s
5. `05_short` — vocal 2s, music 5s
6. `06_sample_rate_mismatch` — vocal 44.1 kHz, music 48 kHz
7. `07_channel_mismatch` — vocal mono, music stereo
8. `08_offset_example` — vocal contains 2 seconds of leading silence

## Extraction test

For every case, create a VMA and extract both streams. For lossless packaging,
the extracted PCM samples should match the original WAV samples exactly.

For `06_sample_rate_mismatch`, preserve each stream's original sample rate rather
than silently resampling.

For `08_offset_example`, the 2-second silence is physically present in the vocal
WAV. Also test VMA-level `start_sample`/offset metadata separately.
