from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_homepage_exposes_complete_vma_user_journey():
    html = (ROOT / "frontend" / "index.html").read_text("utf-8")
    for identifier in (
        "create-form", "vocal-input", "music-input", "open-form", "vma-input", "vma-details",
        "play", "pause", "stop", "seek", "master-volume", "vocal-volume", "music-volume",
        "vocal-mute", "music-mute", "extract-vocal", "extract-music", "extract-all",
    ):
        assert f'id="{identifier}"' in html


def test_frontend_script_handles_api_errors_work_states_and_shared_playback_clock():
    script = (ROOT / "frontend" / "js" / "app.js").read_text("utf-8")
    for behavior in ("responseError", "setWorking", "openSession", "activateVma", "state.context.currentTime", "loadBuffers"):
        assert behavior in script
    assert "Select both a Vocal WAV and a Music WAV" in script
    assert "Select a VMA file before opening it" in script
    assert "X-VMA-Session" in script
    assert "source.start(when, offset)" in script
