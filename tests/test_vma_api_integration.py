import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from conftest import discover_audio_fixture_cases
from vma_test_support import pcm_payload


CASES = discover_audio_fixture_cases()


def _vma_upload(content: bytes):
    return {"file": ("song.vma", content, "application/vnd.vma")}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_api_lossless_round_trip_all_fixture_groups(tmp_path, case):
    """Exercise every requested VMA API operation with only synthetic fixtures."""
    vocal_bytes = case.vocal_path.read_bytes()
    music_bytes = case.music_path.read_bytes()
    with TestClient(app) as client:
        created = client.post(
            "/api/vma/create",
            data={"title": case.name, "artist": "Synthetic tests"},
            files={
                "vocal": ("synthetic_vocal.wav", vocal_bytes, "audio/wav"),
                "music": ("synthetic_music.wav", music_bytes, "audio/wav"),
            },
        )
        assert created.status_code == 200, created.text
        assert created.headers["content-type"].startswith("application/vnd.vma")
        assert created.headers["x-vma-version"] == "1"
        assert created.headers["x-vma-stream-count"] == "2"
        vma_bytes = created.content

        validated = client.post("/api/vma/validate", files=_vma_upload(vma_bytes))
        assert validated.status_code == 200, validated.text
        assert validated.json()["valid"] is True

        info = client.post("/api/vma/info", files=_vma_upload(vma_bytes))
        assert info.status_code == 200, info.text
        info_payload = info.json()
        assert info_payload["metadata"]["title"] == case.name
        assert info_payload["stream_count"] == 2
        assert [stream["type"] for stream in info_payload["streams"]] == ["vocal", "music"]

        extracted = {}
        for kind, original in (("vocal", case.vocal_path), ("music", case.music_path)):
            response = client.post(f"/api/vma/extract/{kind}", files=_vma_upload(vma_bytes))
            assert response.status_code == 200, response.text
            target = tmp_path / f"{case.name}-{kind}.wav"
            target.write_bytes(response.content)
            extracted[kind] = target
            assert pcm_payload(target) == pcm_payload(original)

        all_response = client.post("/api/vma/extract/all", files=_vma_upload(vma_bytes))
        assert all_response.status_code == 200, all_response.text
        with zipfile.ZipFile(io.BytesIO(all_response.content)) as archive:
            assert sorted(archive.namelist()) == ["music.wav", "vocal.wav"]
            for kind, original in (("vocal", case.vocal_path), ("music", case.music_path)):
                target = tmp_path / f"{case.name}-zip-{kind}.wav"
                target.write_bytes(archive.read(f"{kind}.wav"))
                assert pcm_payload(target) == pcm_payload(original)


def test_api_rejects_missing_invalid_and_corrupt_uploads():
    case = CASES[0]
    valid_music = case.music_path.read_bytes()
    with TestClient(app) as client:
        missing = client.post("/api/vma/create", files={"vocal": ("v.wav", case.vocal_path.read_bytes(), "audio/wav")})
        assert missing.status_code == 422 and "music" in str(missing.json()["detail"])

        invalid_wav = client.post(
            "/api/vma/create",
            files={"vocal": ("invalid.wav", b"not a WAV", "audio/wav"), "music": ("m.wav", valid_music, "audio/wav")},
        )
        assert invalid_wav.status_code == 422
        assert "WAV" in invalid_wav.json()["detail"]

        malformed = client.post("/api/vma/validate", files=_vma_upload(b"VMAF"))
        assert malformed.status_code == 422
        assert "small" in malformed.json()["detail"]

        corrupt = bytearray(
            client.post(
                "/api/vma/create",
                files={"vocal": ("v.wav", case.vocal_path.read_bytes(), "audio/wav"), "music": ("m.wav", valid_music, "audio/wav")},
            ).content
        )
        corrupt[:4] = b"BAD!"
        invalid = client.post("/api/vma/info", files=_vma_upload(bytes(corrupt)))
        assert invalid.status_code == 422
        assert "magic" in invalid.json()["detail"]


def test_api_openapi_and_swagger_are_available():
    with TestClient(app) as client:
        openapi = client.get("/openapi.json")
        docs = client.get("/docs")
    assert openapi.status_code == 200
    assert "/api/vma/create" in openapi.json()["paths"]
    assert docs.status_code == 200
