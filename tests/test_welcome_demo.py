import hashlib
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.main import app
from backend.vma import read_vma
from backend.vma.models import StreamType


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "backend" / "app" / "assets" / "welcome-demo.vma"
EXPECTED_SHA256 = "a8b94eacbd48e294aff21ea181eadd72b56c497a35d5be3d295ebbc306fc7879"


def _personal_files():
    return {
        "vocal": ("personal-vocal.dat", b"PERSONAL_VOCAL", "application/octet-stream"),
        "music": ("personal-music.dat", b"PERSONAL_MUSIC", "application/octet-stream"),
    }


def test_bundled_demo_is_deterministic_valid_v1_with_distinct_stems():
    assert DEMO.is_file()
    data = DEMO.read_bytes()
    assert hashlib.sha256(data).hexdigest() == EXPECTED_SHA256

    container = read_vma(DEMO)
    assert container.version == 1
    assert container.metadata["title"] == "VMA Welcome Demo"
    assert container.metadata["artist"] == "Synthetic VMA tones"
    assert [stream.stream_type for stream in container.streams] == [
        StreamType.VOCAL,
        StreamType.MUSIC,
    ]
    assert [stream.audio.duration_seconds for stream in container.streams] == [2.0, 2.0]

    vocal, music = container.streams
    vocal_bytes = data[vocal.data_offset : vocal.data_offset + vocal.data_size]
    music_bytes = data[music.data_offset : music.data_offset + music.data_size]
    assert vocal_bytes != music_bytes
    assert any(vocal_bytes)
    assert any(music_bytes)


def test_demo_entry_uses_normal_session_inspection_playback_and_extraction_paths():
    with TestClient(app) as client:
        opened = client.post("/api/demo")
        assert opened.status_code == 200, opened.text
        payload = opened.json()
        assert payload["demo"] is True
        assert payload["version"] == 1
        assert payload["metadata"]["title"] == "VMA Welcome Demo"
        assert len(payload["streams"]) == 2

        session = payload["session_id"]
        inspected = client.get(f"/api/vma/{session}")
        vocal = client.get(f"/api/vma/{session}/stream/vocal")
        music = client.get(f"/api/vma/{session}/stream/music")
        extracted = client.get(f"/api/vma/{session}/extract/vocal")

        assert inspected.status_code == 200
        assert inspected.json()["metadata"]["title"] == "VMA Welcome Demo"
        assert vocal.status_code == 200 and vocal.headers["content-type"].startswith("audio/wav")
        assert music.status_code == 200 and music.headers["content-type"].startswith("audio/wav")
        assert extracted.status_code == 200
        assert vocal.content != music.content


def test_demo_ignores_arbitrary_paths_and_does_not_mutate_a_personal_session():
    with TestClient(app) as client:
        personal = client.post("/api/create", files=_personal_files())
        assert personal.status_code == 200, personal.text
        personal_session = personal.headers["x-vma-session"]
        personal_path = app.state.storage / personal_session / "song.vma"
        personal_bytes = personal_path.read_bytes()

        demo = client.post("/api/demo", params={"path": str(personal_path)})
        assert demo.status_code == 200, demo.text
        assert demo.json()["metadata"]["title"] == "VMA Welcome Demo"
        assert demo.json()["session_id"] != personal_session

        assert personal_path.read_bytes() == personal_bytes
        inspected = client.get(f"/api/vma/{personal_session}")
        extracted = client.get(f"/api/vma/{personal_session}/extract-stream/1")
        assert inspected.status_code == 200
        assert inspected.json()["metadata"]["title"] == ""
        assert extracted.content == b"PERSONAL_VOCAL"


def test_failed_demo_is_safe_and_preserves_other_sessions(monkeypatch, tmp_path):
    with TestClient(app) as client:
        personal = client.post("/api/create", files=_personal_files())
        personal_session = personal.headers["x-vma-session"]
        existing_directories = {path.name for path in app.state.storage.iterdir()}

        missing = tmp_path / "missing-demo.vma"
        monkeypatch.setattr(app_main, "DEMO_VMA_PATH", missing)
        failed = client.post("/api/demo")

        assert failed.status_code == 503
        assert failed.json()["detail"] == "Welcome demo is temporarily unavailable"
        assert str(missing) not in failed.text
        assert {path.name for path in app.state.storage.iterdir()} == existing_directories
        assert client.get(f"/api/vma/{personal_session}").status_code == 200
        assert client.get(f"/api/vma/{personal_session}/extract-stream/1").content == b"PERSONAL_VOCAL"


def test_demo_ui_reuses_normal_player_and_keeps_personal_workflows_visible():
    html = (ROOT / "frontend" / "index.html").read_text("utf-8")
    script = (ROOT / "frontend" / "js" / "app.js").read_text("utf-8")

    assert 'id="try-demo"' in html
    assert 'id="demo-notice"' in html
    assert html.count('data-action="use-own-files"') >= 2
    assert 'id="create-form"' in html
    assert 'id="open-form"' in html
    assert "fetch('/api/demo', { method: 'POST' })" in script
    assert "await activateVma(payload, activation)" in script

    handler = script.split("async function handleDemoOpen(", 1)[1].split(
        "$('try-demo').addEventListener", 1
    )[0]
    assert handler.index("if (!response.ok)") < handler.index(
        "const activation = beginVmaTransition()"
    )


def test_demo_and_personal_ui_mode_transitions_are_isolated_and_reversible():
    script_path = ROOT / "frontend" / "js" / "app.js"
    runner = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(process.argv[1], 'utf8') + '\nglobalThis.__demoTest = { handleDemoOpen, handleUseOwnFiles, handleCreateSubmit, handleOpenSubmit, start, state };';

function element() {
  const classes = new Set(['hidden']);
  const listeners = {};
  const submit = { disabled: false, textContent: '', dataset: { label: '' } };
  return {
    textContent: '', innerHTML: '', disabled: false, value: '1', max: '0', href: '', dataset: {}, files: [],
    classList: {
      add(name) { classes.add(name); }, remove(name) { classes.delete(name); },
      toggle(name, force) { const present = force === undefined ? !classes.has(name) : force; if (present) classes.add(name); else classes.delete(name); return present; },
      contains(name) { return classes.has(name); },
    },
    addEventListener(name, callback) { listeners[name] = callback; },
    setAttribute() {}, scrollIntoView() {},
    querySelector() { return submit; },
  };
}

const nodes = new Map();
const ownFileLinks = [element(), element()];
const document = {
  getElementById(id) { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); },
  querySelectorAll(selector) { return selector === '[data-action="use-own-files"]' ? ownFileLinks : []; },
  createElement() { return { _text: '', set textContent(value) { this._text = String(value); }, get innerHTML() { return this._text; } }; },
};
const payload = (session, demo = false) => ({
  session_id: session, demo, version: 1, duration_seconds: 2,
  metadata: { title: demo ? 'VMA Welcome Demo' : session, artist: demo ? 'Synthetic VMA tones' : 'Personal' },
  streams: [
    { stream_type: 'vocal', codec: 'PCM', audio: { sample_rate: 22050, channels: 1, bit_depth: 16 }, start_seconds: 0, duration_seconds: 2 },
    { stream_type: 'music', codec: 'PCM', audio: { sample_rate: 22050, channels: 1, bit_depth: 16 }, start_seconds: 0, duration_seconds: 2 },
  ],
});

globalThis.document = document;
globalThis.window = { setTimeout() {} };
globalThis.FormData = class { constructor(form) { this.form = form; } };
globalThis.URL = { createObjectURL() { return 'blob:test'; }, revokeObjectURL() {} };
globalThis.setInterval = () => 1; globalThis.clearInterval = () => {};
const sourceStarts = [];
globalThis.AudioContext = class {
  constructor() { this.currentTime = 0; this.destination = {}; }
  createGain() { return { gain: { value: 0 }, connect() {} }; }
  createBufferSource() { return { connect() {}, start(when, offset) { sourceStarts.push({ when, offset }); }, stop() {} }; }
  decodeAudioData() { return Promise.resolve({ duration: 2 }); }
  resume() { return Promise.resolve(); }
};

let failNextDemo = false;
globalThis.fetch = async (url) => {
  if (url === '/api/demo') {
    if (failNextDemo) { failNextDemo = false; return { ok: false, status: 503, text: async () => JSON.stringify({ detail: 'Welcome demo is temporarily unavailable' }) }; }
    return { ok: true, json: async () => payload('demo-session', true) };
  }
  if (url === '/api/create') return { ok: true, blob: async () => new Blob(['vma']), headers: { get: () => 'created-personal' } };
  if (url === '/api/open') return { ok: true, json: async () => payload('opened-personal') };
  if (url === '/api/vma/created-personal') return { ok: true, json: async () => payload('created-personal') };
  if (url.includes('/stream/')) return { ok: true, arrayBuffer: async () => new Uint8Array([1]).buffer };
  throw new Error(`Unexpected URL: ${url}`);
};

eval(source);
const createForm = document.getElementById('create-form');
const openForm = document.getElementById('open-form');
document.getElementById('vocal-input').files = [{ name: 'vocal.wav' }];
document.getElementById('music-input').files = [{ name: 'music.wav' }];
document.getElementById('vma-input').files = [{ name: 'personal.vma' }];

(async () => {
  await globalThis.__demoTest.handleDemoOpen();
  assert.equal(globalThis.__demoTest.state.demo, true);
  assert.equal(document.getElementById('player-panel').classList.contains('hidden'), false);
  assert.equal(document.getElementById('demo-notice').classList.contains('hidden'), false);

  globalThis.__demoTest.handleUseOwnFiles();
  assert.equal(globalThis.__demoTest.state.demo, false);
  assert.equal(globalThis.__demoTest.state.session, null);
  assert.equal(document.getElementById('vma-details').classList.contains('hidden'), true);
  assert.equal(document.getElementById('player-panel').classList.contains('hidden'), true);
  assert.equal(document.getElementById('demo-notice').classList.contains('hidden'), true);
  assert.equal(document.getElementById('demo-status').textContent, '');

  await globalThis.__demoTest.handleDemoOpen();
  await globalThis.__demoTest.handleCreateSubmit({ preventDefault() {}, currentTarget: createForm, target: createForm });
  assert.equal(globalThis.__demoTest.state.demo, false);
  assert.equal(globalThis.__demoTest.state.session, 'created-personal');
  assert.equal(document.getElementById('player-panel').classList.contains('hidden'), false);
  assert.equal(document.getElementById('demo-notice').classList.contains('hidden'), true);
  assert.equal(document.getElementById('demo-status').textContent, '');

  await globalThis.__demoTest.handleDemoOpen();
  await globalThis.__demoTest.handleOpenSubmit({ preventDefault() {}, currentTarget: openForm, target: openForm });
  assert.equal(globalThis.__demoTest.state.demo, false);
  assert.equal(globalThis.__demoTest.state.session, 'opened-personal');
  assert.equal(document.getElementById('player-panel').classList.contains('hidden'), false);
  assert.equal(document.getElementById('demo-notice').classList.contains('hidden'), true);

  await globalThis.__demoTest.handleDemoOpen();
  assert.equal(globalThis.__demoTest.state.demo, true);
  assert.equal(document.getElementById('player-panel').classList.contains('hidden'), false);
  assert.equal(document.getElementById('demo-notice').classList.contains('hidden'), false);

  await globalThis.__demoTest.handleOpenSubmit({ preventDefault() {}, currentTarget: openForm, target: openForm });
  const personalSession = globalThis.__demoTest.state.session;
  await globalThis.__demoTest.start();
  assert.equal(sourceStarts.length >= 2, true);
  failNextDemo = true;
  await globalThis.__demoTest.handleDemoOpen();
  assert.equal(globalThis.__demoTest.state.demo, false);
  assert.equal(globalThis.__demoTest.state.session, personalSession);
  assert.equal(document.getElementById('player-panel').classList.contains('hidden'), false);
  assert.equal(document.getElementById('demo-notice').classList.contains('hidden'), true);
  assert.equal(document.getElementById('demo-status').textContent, 'Welcome demo is temporarily unavailable');
})().catch((error) => { console.error(error.stack); process.exit(1); });
'''
    result = subprocess.run(
        ["node", "-e", runner, str(script_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
