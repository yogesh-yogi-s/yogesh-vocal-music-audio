from fastapi.testclient import TestClient

from backend.app.main import app
from conftest import write_pcm_wav


def test_api_create_open_and_extract(tmp_path):
    vocal = tmp_path / "vocal.wav"
    music = tmp_path / "music.wav"
    write_pcm_wav(vocal, channels=1, sample_rate=44_100, bit_depth=16, frames=20)
    write_pcm_wav(music, channels=2, sample_rate=48_000, bit_depth=24, frames=30)
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200 and "Vocal Music Audio" in page.text
        assert client.get("/css/style.css").status_code == 200
        assert client.get("/js/app.js").status_code == 200
        created = client.post(
            "/api/create", data={"title": "Demo", "artist": "Artist"},
            files={"vocal": ("vocal.wav", vocal.read_bytes(), "audio/wav"), "music": ("music.wav", music.read_bytes(), "audio/wav")},
        )
        assert created.status_code == 200
        opened = client.post("/api/open", files={"file": ("song.vma", created.content, "application/vnd.vma")})
        assert opened.status_code == 200
        payload = opened.json()
        assert payload["metadata"]["title"] == "Demo"
        session = payload["session_id"]
        assert client.get(f"/api/vma/{session}/stream/vocal").status_code == 200
        assert client.get(f"/api/vma/{session}/extract/music").status_code == 200
        assert client.get(f"/api/vma/{session}/extract-all").headers["content-type"].startswith("application/zip")
