from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_seeking_reschedules_supported_v1_and_v2_streams_deterministically():
    """Exercise seek scheduling with Web Audio mocks; this does not test audible playback."""
    script_path = ROOT / "frontend" / "js" / "app.js"
    runner = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(process.argv[1], 'utf8') + '\nglobalThis.__vmaSeekTest = { openSession, start, pause, state };';

const listeners = new Map();
function element(id) {
  const classes = new Set();
  return {
    id, textContent: '', innerHTML: '', disabled: false, value: '1', max: '0', href: '', dataset: {}, files: [],
    classList: {
      add(name) { classes.add(name); }, remove(name) { classes.delete(name); },
      toggle(name, force) { const present = force === undefined ? !classes.has(name) : force; if (present) classes.add(name); else classes.delete(name); return present; },
      contains(name) { return classes.has(name); },
    },
    addEventListener(type, handler) { listeners.set(`${id}:${type}`, handler); },
    setAttribute() {}, querySelector() { return { disabled: false, textContent: '', dataset: { label: '' } }; },
  };
}
const nodes = new Map();
const document = {
  getElementById(id) { if (!nodes.has(id)) nodes.set(id, element(id)); return nodes.get(id); },
  querySelectorAll() { return []; },
  createElement() { return { _text: '', set textContent(value) { this._text = String(value); }, get innerHTML() { return this._text; } }; },
};
const v1 = { session_id: 'v1-seek', version: 1, duration_seconds: 10, metadata: {}, streams: [
  { stream_type: 'vocal', codec: 'PCM', audio: { sample_rate: 44100, channels: 1, bit_depth: 16 }, start_seconds: 0, duration_seconds: 10 },
  { stream_type: 'music', codec: 'PCM', audio: { sample_rate: 44100, channels: 1, bit_depth: 16 }, start_seconds: 0, duration_seconds: 8 },
] };
const v2Dual = { session_id: 'v2-dual-seek', version: 2, duration_seconds: 0, metadata: {}, streams: [
  { stream_id: 1, label: 'Vocal', role_name: 'AUDIO_PRIMARY', format_id: 0, payload_size: 1, start_seconds: 0, download_filename: 'vocal.mp3' },
  { stream_id: 2, label: 'Music', role_name: 'AUDIO_SUPPLEMENTAL', format_id: 0, payload_size: 1, start_seconds: 0, download_filename: 'music.ogg' },
] };
const v2One = { session_id: 'v2-one-seek', version: 2, duration_seconds: 0, metadata: {}, streams: [
  { stream_id: 1, label: 'Vocal', role_name: 'AUDIO_PRIMARY', format_id: 0, payload_size: 1, start_seconds: 0, download_filename: 'vocal.mp3' },
  { stream_id: 2, label: 'Music', role_name: 'AUDIO_SUPPLEMENTAL', format_id: 0, payload_size: 1, start_seconds: 0, download_filename: 'music.bin' },
] };

globalThis.document = document;
globalThis.window = { setTimeout() {} };
globalThis.URL = { createObjectURL() {}, revokeObjectURL() {} };
let timerCallback = null;
globalThis.setInterval = (callback) => { timerCallback = callback; return 1; };
globalThis.clearInterval = () => { timerCallback = null; };
const scheduled = [];
globalThis.AudioContext = class {
  constructor() { this.currentTime = 100; this.destination = {}; }
  createGain() { return { gain: { value: 0 }, connect() {} }; }
  createBufferSource() {
    const record = { buffer: null, when: null, offset: null, stopped: false };
    const sourceNode = {
      connect() {},
      start(when, offset) { record.buffer = sourceNode.buffer; record.when = when; record.offset = offset; scheduled.push(record); },
      stop() { record.stopped = true; },
      buffer: null,
    };
    return sourceNode;
  }
  decodeAudioData(bytes) { const marker = new Uint8Array(bytes)[0]; return marker ? Promise.resolve({ duration: marker }) : Promise.reject(new Error('unsupported')); }
  resume() { return Promise.resolve(); }
};
globalThis.fetch = async (url) => {
  if (url.includes('/stream/vocal') || url.includes('/extract-stream/1')) return { ok: true, arrayBuffer: async () => new Uint8Array([10]).buffer };
  if (url.includes('/stream/music') || url.includes('/v2-dual-seek/extract-stream/2')) return { ok: true, arrayBuffer: async () => new Uint8Array([8]).buffer };
  if (url.includes('/v2-one-seek/extract-stream/2')) return { ok: true, arrayBuffer: async () => new Uint8Array([0]).buffer };
  return { ok: true, json: async () => url.endsWith('/v1-seek') ? v1 : url.endsWith('/v2-dual-seek') ? v2Dual : v2One };
};

eval(source);
const seek = document.getElementById('seek');
const inputSeek = (value) => { seek.value = String(value); listeners.get('seek:input')({ target: seek }); };
const changeSeek = async (value) => { seek.value = String(value); listeners.get('seek:change')({ target: seek }); await Promise.resolve(); await Promise.resolve(); };

(async () => {
  await globalThis.__vmaSeekTest.openSession('v1-seek');
  assert.equal(globalThis.__vmaSeekTest.state.duration, 10);
  await globalThis.__vmaSeekTest.start();
  assert.equal(scheduled.length, 2);
  assert.deepEqual(scheduled.map(({ offset }) => offset), [0, 0]);

  inputSeek(4);
  assert.equal(globalThis.__vmaSeekTest.state.scrubbing, true);
  assert.equal(document.getElementById('time').textContent, '0:04 / 0:10');
  globalThis.__vmaSeekTest.state.context.currentTime = 102;
  timerCallback();
  assert.equal(seek.value, '4');
  await changeSeek(4);
  assert.equal(globalThis.__vmaSeekTest.state.scrubbing, false);
  assert.equal(globalThis.__vmaSeekTest.state.position, 4);
  assert.equal(scheduled.length, 4);
  assert.deepEqual(scheduled.slice(-2).map(({ offset }) => offset), [4, 4]);
  assert.equal(scheduled.at(-1).when, scheduled.at(-2).when);
  assert.equal(scheduled[0].stopped, true);
  assert.equal(scheduled[1].stopped, true);

  globalThis.__vmaSeekTest.state.context.currentTime = 103;
  globalThis.__vmaSeekTest.pause();
  const beforePausedSeek = scheduled.length;
  inputSeek(2); await changeSeek(2);
  assert.equal(globalThis.__vmaSeekTest.state.playing, false);
  assert.equal(globalThis.__vmaSeekTest.state.position, 2);
  assert.equal(scheduled.length, beforePausedSeek);

  await globalThis.__vmaSeekTest.start();
  const beforeNearEnd = scheduled.length;
  await changeSeek(9.9);
  assert.equal(scheduled.length, beforeNearEnd + 1);
  assert.equal(scheduled.at(-1).offset, 9.9);
  const beforeBeginning = scheduled.length;
  await changeSeek(0);
  assert.equal(scheduled.length, beforeBeginning + 2);
  assert.deepEqual(scheduled.slice(-2).map(({ offset }) => offset), [0, 0]);

  await globalThis.__vmaSeekTest.openSession('v2-dual-seek');
  await globalThis.__vmaSeekTest.start();
  const beforeV2DualSeek = scheduled.length;
  await changeSeek(5);
  assert.equal(scheduled.length, beforeV2DualSeek + 2);
  assert.deepEqual(scheduled.slice(-2).map(({ offset }) => offset), [5, 5]);
  assert.equal(scheduled.at(-1).when, scheduled.at(-2).when);

  globalThis.__vmaSeekTest.pause();
  const beforeV2PausedSeek = scheduled.length;
  inputSeek(2); await changeSeek(2);
  assert.equal(globalThis.__vmaSeekTest.state.playing, false);
  assert.equal(scheduled.length, beforeV2PausedSeek);

  await globalThis.__vmaSeekTest.start();
  assert.equal(scheduled.length, beforeV2PausedSeek + 2);
  const resumedVocal = scheduled[beforeV2PausedSeek];
  const resumedInstrumental = scheduled[beforeV2PausedSeek + 1];
  assert.ok(Math.abs(resumedVocal.offset - 2) < 1e-9);
  assert.ok(Math.abs(resumedInstrumental.offset - 2) < 1e-9);

  await globalThis.__vmaSeekTest.openSession('v2-one-seek');
  assert.match(document.getElementById('open-status').textContent, /Only Vocal is playable/);
  assert.equal(Object.values(globalThis.__vmaSeekTest.state.playbackStreams).filter(({ buffer }) => buffer).length, 1);
  await globalThis.__vmaSeekTest.start();
  const beforeDegradedSeek = scheduled.length;
  await changeSeek(6);
  assert.equal(scheduled.length, beforeDegradedSeek + 1);
  assert.equal(scheduled.at(-1).offset, 6);

  await changeSeek(10);
  assert.equal(globalThis.__vmaSeekTest.state.position, 10);
  assert.equal(globalThis.__vmaSeekTest.state.playing, false);
  assert.equal(Object.keys(globalThis.__vmaSeekTest.state.sources).length, 0);
  assert.equal(scheduled.every(({ stopped }) => stopped), true);
})().catch((error) => { console.error(error.stack); process.exit(1); });
'''
    result = subprocess.run(
        ["node", "-e", runner, str(script_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
