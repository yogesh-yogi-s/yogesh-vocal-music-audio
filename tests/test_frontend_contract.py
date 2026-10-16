from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_homepage_exposes_complete_vma_user_journey():
    html = (ROOT / "frontend" / "index.html").read_text("utf-8")
    for identifier in (
        "create-form", "vocal-input", "music-input", "open-form", "vma-input", "vma-details",
        "play", "pause", "stop", "seek", "master-volume", "vocal-volume", "music-volume",
        "vocal-mute", "music-mute", "extract-vocal", "extract-music", "extract-all", "how-heading",
        "v2-playback-notice",
    ):
        assert f'id="{identifier}"' in html


def test_frontend_exposes_native_v2_playback_with_download_fallback():
    html = (ROOT / "frontend" / "index.html").read_text("utf-8")
    # V2 keeps its direct byte-exact download links even when native decode succeeds.
    assert 'id="player-panel"' in html
    assert 'id="extract-panel"' in html
    script = (ROOT / "frontend" / "js" / "app.js").read_text("utf-8")
    assert "v2StreamCard" in script
    assert "extract-stream" in script
    assert "classList.toggle('hidden', isV2)" in script
    assert "v2-playback-notice" in script
    assert "decodeAudioData" in script
    assert "Not playable in this browser; original download remains available." in script
    assert "!state.playbackReady" in script


def test_frontend_shared_session_activation_replaces_v1_v2_status_and_controls():
    """Exercise the session path used after Create and verify both version transitions."""
    script_path = ROOT / "frontend" / "js" / "app.js"
    assert "if (session) await openSession(session);" in script_path.read_text("utf-8")
    runner = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(process.argv[1], 'utf8') + '\nglobalThis.__vmaTest = { openSession, start, pause, state };';

function element() {
  const classes = new Set();
  return {
    textContent: '', innerHTML: '', disabled: false, value: '1', max: '0', href: '', dataset: {}, files: [],
    classList: {
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      toggle(name, force) { const present = force === undefined ? !classes.has(name) : force; if (present) classes.add(name); else classes.delete(name); return present; },
      contains(name) { return classes.has(name); },
    },
    addEventListener() {}, setAttribute() {},
    querySelector() { return { disabled: false, textContent: '', dataset: { label: '' } }; },
  };
}

const nodes = new Map();
const document = {
  getElementById(id) { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); },
  querySelectorAll() { return []; },
  createElement() { return { _text: '', set textContent(value) { this._text = String(value); }, get innerHTML() { return this._text; } }; },
};
const v1 = { session_id: 'v1', version: 1, duration_seconds: 1, metadata: {}, streams: [
  { stream_type: 'vocal', codec: 'PCM', audio: { sample_rate: 44100, channels: 1, bit_depth: 16 }, start_seconds: 0, duration_seconds: 1 },
  { stream_type: 'music', codec: 'PCM', audio: { sample_rate: 44100, channels: 1, bit_depth: 16 }, start_seconds: 0, duration_seconds: 1 },
] };
const v2 = { session_id: 'v2', version: 2, duration_seconds: 0, metadata: {}, streams: [
  { stream_id: 1, label: 'Vocal', role_name: 'AUDIO_PRIMARY', format_id: 0, payload_size: 1, start_seconds: 0, download_filename: 'vocal.mp3' },
  { stream_id: 2, label: 'Music', role_name: 'AUDIO_SUPPLEMENTAL', format_id: 0, payload_size: 1, start_seconds: 0, download_filename: 'music.ogg' },
] };
const v2OnePlayable = { session_id: 'v2-one', version: 2, duration_seconds: 0, metadata: {}, streams: [
  { stream_id: 1, label: 'Vocal', role_name: 'AUDIO_PRIMARY', format_id: 0, payload_size: 1, start_seconds: 0, download_filename: 'vocal.m4a' },
  { stream_id: 2, label: 'Music', role_name: 'AUDIO_SUPPLEMENTAL', format_id: 0, payload_size: 1, start_seconds: 0, download_filename: 'music.bin' },
] };
const v2NonePlayable = { session_id: 'v2-none', version: 2, duration_seconds: 0, metadata: {}, streams: [
  { stream_id: 1, label: 'Vocal', role_name: 'AUDIO_PRIMARY', format_id: 0, payload_size: 1, start_seconds: 0, download_filename: 'vocal.dat' },
] };
globalThis.document = document;
globalThis.window = { setTimeout() {} };
globalThis.URL = { createObjectURL() {}, revokeObjectURL() {} };
globalThis.setInterval = () => 1;
globalThis.clearInterval = () => {};
const sourceStarts = [];
globalThis.AudioContext = class {
  constructor() { this.currentTime = 0; this.destination = {}; }
  createGain() { return { gain: { value: 0 }, connect() {} }; }
  createBufferSource() { return { connect() {}, start(when, offset) { sourceStarts.push({ when, offset }); }, stop() {} }; }
  decodeAudioData(bytes) { const marker = new Uint8Array(bytes)[0]; if (marker === 0) return Promise.reject(new Error('unsupported')); return Promise.resolve({ duration: marker }); }
  resume() {}
};
globalThis.fetch = async (url) => {
  if (url.includes('/stream/') || url.includes('/extract-stream/')) {
    const unsupported = url.includes('/v2-one/extract-stream/2') || url.includes('/v2-none/');
    const marker = url.includes('/extract-stream/2') ? 2 : 1;
    return { ok: true, arrayBuffer: async () => new Uint8Array([unsupported ? 0 : marker]).buffer };
  }
  const payload = url.endsWith('/v1') ? v1 : url.endsWith('/v2-one') ? v2OnePlayable : url.endsWith('/v2-none') ? v2NonePlayable : v2;
  return { ok: true, json: async () => payload };
};

eval(source);
(async () => {
  await globalThis.__vmaTest.openSession('v1');
  assert.equal(document.getElementById('open-status').textContent, 'VMA opened and ready to play.');
  assert.equal(document.getElementById('player-panel').classList.contains('hidden'), false);
  assert.equal(document.getElementById('v2-playback-notice').classList.contains('hidden'), true);

  await globalThis.__vmaTest.openSession('v2');
  assert.equal(document.getElementById('open-status').textContent, 'VMA v2 opened. Both original streams are ready for browser playback.');
  assert.equal(document.getElementById('player-panel').classList.contains('hidden'), false);
  assert.equal(document.getElementById('v2-playback-notice').classList.contains('hidden'), false);
  assert.equal(globalThis.__vmaTest.state.duration, 2);
  assert.equal(document.getElementById('seek').max, 2);
  globalThis.__vmaTest.state.context.currentTime = 10;
  await globalThis.__vmaTest.start();
  assert.equal(sourceStarts.length, 2);
  assert.equal(sourceStarts[0].when, sourceStarts[1].when);
  globalThis.__vmaTest.pause();

  await globalThis.__vmaTest.openSession('v1');
  assert.equal(document.getElementById('open-status').textContent, 'VMA opened and ready to play.');
  assert.equal(document.getElementById('player-panel').classList.contains('hidden'), false);
  assert.equal(document.getElementById('v2-playback-notice').classList.contains('hidden'), true);

  await globalThis.__vmaTest.openSession('v2-one');
  assert.match(document.getElementById('open-status').textContent, /Only Vocal is playable/);
  assert.equal(document.getElementById('player-panel').classList.contains('hidden'), false);

  await globalThis.__vmaTest.openSession('v2-none');
  assert.match(document.getElementById('open-status').textContent, /Browser playback is unavailable/);
  assert.equal(document.getElementById('player-panel').classList.contains('hidden'), true);
})().catch((error) => { console.error(error.stack); process.exit(1); });
'''
    result = subprocess.run(
        ["node", "-e", runner, str(script_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_frontend_script_handles_api_errors_work_states_and_shared_playback_clock():
    script = (ROOT / "frontend" / "js" / "app.js").read_text("utf-8")
    for behavior in ("responseError", "setWorking", "openSession", "activateVma", "state.context.currentTime", "loadBuffers"):
        assert behavior in script
    assert "Select both a vocal and a music stream before creating VMA" in script
    assert "Select a VMA file before opening it" in script
    assert "X-VMA-Session" in script
    assert "const activation = state.activation;" in script
    assert "activation !== state.activation || !state.playbackReady" in script
    assert "source.start(when, offset)" in script
    assert "$('seek').addEventListener('change'" in script
    assert "$('seek').addEventListener('input'" not in script
