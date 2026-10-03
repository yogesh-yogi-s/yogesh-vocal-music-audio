# VMA — Vocal Music Audio

A local MVP for a lossless two-track `.vma` container. It packages a Vocal WAV and a Music WAV as separate, synchronized PCM streams, plays them with independent browser mix controls, and extracts them without AI separation or transcoding.

## Requirements

- Python 3.13+ (tested on Python 3.13)
- PCM RIFF/WAV input only: mono/stereo, 8/16/24/32-bit, up to 384 kHz

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Uploads are limited to 500 MB per file and exist only for the lifetime of the local server.

## Test

```powershell
python -m pytest -q
```

## Library API

When importing from the repository root, add `backend` to `PYTHONPATH` or install the package in your application environment.

```python
from vma import create_vma, read_vma, extract_vocal, extract_music, extract_all, validate_vma

create_vma("vocal.wav", "music.wav", "song.vma", {"title": "Song", "artist": "Artist"})
info = read_vma("song.vma")
extract_vocal("song.vma", "vocal.wav")
```

See [the binary specification](docs/VMA_FORMAT.md) and [architecture overview](docs/ARCHITECTURE.md).
