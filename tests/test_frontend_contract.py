from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_homepage_exposes_complete_vma_user_journey():
    html = (ROOT / "frontend" / "index.html").read_text("utf-8")
    for identifier in (
        "create-form", "vocal-input", "music-input", "open-form", "vma-input", "vma-details",
        "play", "pause", "stop", "seek", "master-volume", "vocal-volume", "music-volume",
        "vocal-mute", "music-mute", "extract-vocal", "extract-music", "extract-all", "how-heading",
    ):
        assert f'id="{identifier}"' in html


def test_frontend_exposes_v2_open_inspect_and_download_without_playback():
    html = (ROOT / "frontend" / "index.html").read_text("utf-8")
    # The V1-only player and bulk extraction panels are addressable so V2 hides them.
    assert 'id="player-panel"' in html
    assert 'id="extract-panel"' in html
    script = (ROOT / "frontend" / "js" / "app.js").read_text("utf-8")
    assert "payload.version === 2" in script
    assert "if (isV2) return" in script
    assert "v2StreamCard" in script
    assert "extract-stream" in script
    assert "classList.toggle('hidden', isV2)" in script
    assert "state.meta.version === 2" in script  # structural guard: V2 cannot start playback


def test_frontend_script_handles_api_errors_work_states_and_shared_playback_clock():
    script = (ROOT / "frontend" / "js" / "app.js").read_text("utf-8")
    for behavior in ("responseError", "setWorking", "openSession", "activateVma", "state.context.currentTime", "loadBuffers"):
        assert behavior in script
    assert "Select both a Vocal WAV and a Music WAV" in script
    assert "Select a VMA file before opening it" in script
    assert "X-VMA-Session" in script
    assert "source.start(when, offset)" in script
    assert "$('seek').addEventListener('change'" in script
    assert "$('seek').addEventListener('input'" not in script
