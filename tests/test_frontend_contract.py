from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_homepage_exposes_complete_vma_user_journey():
    html = (ROOT / "frontend" / "index.html").read_text("utf-8")
    for identifier in (
        "create-form", "vocal-input", "music-input", "open-form", "vma-input", "vma-details",
        "play", "pause", "stop", "seek", "master-volume", "vocal-volume", "music-volume",
        "vocal-mute", "music-mute", "extract-vocal", "extract-music", "extract-all",
        "v2-playback-notice", "theme-toggle", "nav-toggle", "site-nav", "quick-demo",
        "inspect-empty", "playback-empty", "extract-empty", "waveform-vocal", "waveform-music",
        "create-result", "create-result-filename", "download-vma", "delete-session",
    ):
        assert f'id="{identifier}"' in html


def test_redesigned_workspace_has_real_routes_theme_and_project_links():
    html = (ROOT / "frontend" / "index.html").read_text("utf-8")
    script = (ROOT / "frontend" / "js" / "app.js").read_text("utf-8")
    stylesheet = (ROOT / "frontend" / "css" / "style.css").read_text("utf-8")

    for route in ("home", "create", "open", "inspect", "playback", "extract", "format", "help"):
        assert f'href="#/{route}"' in html
        assert f'data-view="{route}"' in html
        assert f"'{route}':" not in script  # route keys are unquoted identifiers
    assert html.count("<details") >= 5
    assert "https://github.com/yogesh-yogi-s/yogesh-vocal-music-audio" in html
    assert "Star on GitHub" in html
    assert "localStorage.getItem('vma-theme')" in html
    assert "prefers-color-scheme: light" in html
    assert "window.localStorage.setItem('vma-theme', theme)" in script
    assert "document.documentElement" in script
    assert "aria-pressed" in script
    assert ':root[data-theme="light"]' in stylesheet
    assert "prefers-reduced-motion: reduce" in stylesheet
    assert "@media(max-width:980px)" in stylesheet
    assert "--orange:#ff7a1a" in stylesheet
    assert "--teal:#48b9ae" in stylesheet
    assert "#/playback" in html
    assert "initializeRouter" in script
    assert "navigateView('playback')" in script
    assert "linear-gradient" in stylesheet  # restrained player edge treatment only
    assert "purple" not in stylesheet.lower()


def test_owned_session_deletion_waits_for_success_before_clearing_the_frontend():
    script = (ROOT / "frontend" / "js" / "app.js").read_text("utf-8")
    handler = script.split("async function deleteCurrentSession()", 1)[1].split(
        "$('delete-session').addEventListener", 1
    )[0]

    assert "fetch(`/api/vma/${session}`, { method: 'DELETE' })" in handler
    assert "if (!response.ok) throw new Error" in handler
    assert handler.index("if (!response.ok)") < handler.index("beginVmaTransition()")
    assert "if (state.session !== session) return" in handler
    assert "navigateView('home')" in handler


def test_theme_and_mobile_navigation_toggle_without_touching_player_state():
    script_path = ROOT / "frontend" / "js" / "app.js"
    runner = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(process.argv[1], 'utf8') + '\nglobalThis.__uiTest = { state };';

function element() {
  const classes = new Set(); const listeners = {}; const attributes = {};
  const children = { '.theme-label': { textContent: '' }, '.theme-icon': { textContent: '' } };
  const submit = { disabled: false, textContent: '', dataset: { label: '' } };
  return {
    textContent: '', innerHTML: '', disabled: false, value: '1', max: '0', href: '', dataset: {}, files: [],
    classList: {
      add(name) { classes.add(name); }, remove(name) { classes.delete(name); },
      toggle(name, force) { const present = force === undefined ? !classes.has(name) : force; if (present) classes.add(name); else classes.delete(name); return present; },
      contains(name) { return classes.has(name); },
    },
    addEventListener(name, callback) { listeners[name] = callback; },
    setAttribute(name, value) { attributes[name] = String(value); },
    getAttribute(name) { return attributes[name]; },
    querySelector(selector) { return children[selector] || submit; },
    click() { if (listeners.click) listeners.click({ currentTarget: this }); },
  };
}

const nodes = new Map(); const navLinks = [element(), element()];
const root = { dataset: { theme: 'dark' } };
const document = {
  documentElement: root,
  getElementById(id) { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); },
  querySelectorAll(selector) { return selector === '#site-nav a' ? navLinks : []; },
  createElement() { return { _text: '', set textContent(value) { this._text = String(value); }, get innerHTML() { return this._text; } }; },
};
const saved = {};
globalThis.document = document;
globalThis.window = { setTimeout() {}, localStorage: { setItem(key, value) { saved[key] = value; } } };
globalThis.URL = { createObjectURL() {}, revokeObjectURL() {} };
globalThis.setInterval = () => 1; globalThis.clearInterval = () => {};
globalThis.AudioContext = class {};

eval(source);
const theme = document.getElementById('theme-toggle');
const navToggle = document.getElementById('nav-toggle');
const siteNav = document.getElementById('site-nav');
globalThis.__uiTest.state.session = 'personal-session';
globalThis.__uiTest.state.playing = true;

theme.click();
assert.equal(root.dataset.theme, 'light');
assert.equal(theme.getAttribute('aria-pressed'), 'true');
assert.equal(theme.getAttribute('aria-label'), 'Switch to dark theme');
assert.equal(saved['vma-theme'], 'light');
assert.equal(globalThis.__uiTest.state.session, 'personal-session');
assert.equal(globalThis.__uiTest.state.playing, true);

theme.click();
assert.equal(root.dataset.theme, 'dark');
assert.equal(theme.getAttribute('aria-pressed'), 'false');
assert.equal(saved['vma-theme'], 'dark');

navToggle.click();
assert.equal(siteNav.dataset.open, 'true');
assert.equal(navToggle.getAttribute('aria-expanded'), 'true');
navLinks[0].click();
assert.equal(siteNav.dataset.open, 'false');
assert.equal(navToggle.getAttribute('aria-expanded'), 'false');
'''
    result = subprocess.run(
        ["node", "-e", runner, str(script_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_hash_routing_switches_dedicated_views_without_resetting_session():
    script_path = ROOT / "frontend" / "js" / "app.js"
    runner = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(process.argv[1], 'utf8') + '\nglobalThis.__routeTest = { state, showView };';
function element(dataset = {}) {
  const classes = new Set(); const attributes = {};
  return {
    dataset, textContent: '', innerHTML: '', value: '1', max: '0', files: [], disabled: false,
    classList: { add(v){classes.add(v)}, remove(v){classes.delete(v)}, contains(v){return classes.has(v)},
      toggle(v, force){const on=force===undefined?!classes.has(v):force; if(on)classes.add(v);else classes.delete(v);return on} },
    addEventListener(){}, setAttribute(k,v){attributes[k]=String(v)}, removeAttribute(k){delete attributes[k]},
    getAttribute(k){return attributes[k]}, querySelector(){return {dataset:{label:''}}}, focus(){}
  };
}
const views = ['home','create','open','inspect','playback','extract','format','help'].map(route => element({view:route}));
const links = ['home','create','open','inspect','playback','extract','format','help'].map(route => element({route}));
const nodes = new Map(); const root = {dataset:{theme:'dark'}};
const document = {
  documentElement: root,
  getElementById(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)},
  querySelectorAll(selector){if(selector==='[data-view]')return views;if(selector==='[data-route]')return links;return []},
  createElement(){return {_text:'',set textContent(v){this._text=String(v)},get innerHTML(){return this._text}}}
};
const windowListeners = {};
globalThis.document=document;
globalThis.window={location:{hash:'#/home'},localStorage:{setItem(){}},setTimeout(){},addEventListener(name,fn){windowListeners[name]=fn}};
globalThis.URL={createObjectURL(){},revokeObjectURL(){}};
globalThis.setInterval=()=>1;globalThis.clearInterval=()=>{};globalThis.AudioContext=class{};
eval(source);
globalThis.__routeTest.state.session='kept-session';globalThis.__routeTest.state.playing=true;
window.location.hash='#/playback';windowListeners.hashchange();
assert.equal(views.find(v=>v.dataset.view==='playback').classList.contains('hidden'),false);
assert.equal(views.find(v=>v.dataset.view==='home').classList.contains('hidden'),true);
assert.equal(links.find(v=>v.dataset.route==='playback').getAttribute('aria-current'),'page');
assert.equal(globalThis.__routeTest.state.session,'kept-session');
assert.equal(globalThis.__routeTest.state.playing,true);
'''
    result = subprocess.run(["node", "-e", runner, str(script_path)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_live_waveforms_use_independent_web_audio_analysers_without_duplicate_signal_paths():
    script = (ROOT / "frontend" / "js" / "app.js").read_text("utf-8")
    assert "state.context.createAnalyser()" in script
    assert "analyser.connect(gain)" in script
    assert "source.connect(state.analysers[kind] || state.gains[kind])" in script
    assert "getByteTimeDomainData(values)" in script
    assert "drawLiveWaveform('vocal')" in script
    assert "drawLiveWaveform('music')" in script
    assert "state.sources[kind] && !state.muted[kind]" in script
    assert "+$('master-volume').value > 0" in script
    assert "window.requestAnimationFrame(frame)" in script
    assert "window.cancelAnimationFrame" in script
    assert "reducedMotionPreferred()" in script
    assert "stopVisualization(true)" in script


def test_create_success_stays_on_create_and_exposes_explicit_next_steps():
    html = (ROOT / "frontend" / "index.html").read_text("utf-8")
    script = (ROOT / "frontend" / "js" / "app.js").read_text("utf-8")
    create_handler = script.split("async function handleCreateSubmit(", 1)[1].split(
        "$('create-form').addEventListener", 1
    )[0]
    open_handler = script.split("async function handleOpenSubmit(", 1)[1].split(
        "$('open-form').addEventListener", 1
    )[0]
    demo_handler = script.split("async function handleDemoOpen(", 1)[1].split(
        "$('try-demo').addEventListener", 1
    )[0]

    assert 'id="create-result"' in html
    assert 'id="create-result-filename"' in html
    assert 'href="#/inspect" data-route="inspect"' in html
    assert 'href="#/playback" data-route="playback"' in html
    assert "clearCreateResult()" in create_handler
    assert "$('create-result').classList.remove('hidden')" in create_handler
    assert "navigateView(" not in create_handler
    assert "navigateView('inspect')" in open_handler
    assert "navigateView('playback')" in demo_handler


def test_frontend_exposes_native_v2_playback_with_download_fallback():
    html = (ROOT / "frontend" / "index.html").read_text("utf-8")
    # V2 keeps its direct byte-exact download links even when native decode succeeds.
    assert 'id="player-panel"' in html
    assert 'id="extract-panel"' in html
    script = (ROOT / "frontend" / "js" / "app.js").read_text("utf-8")
    assert "v2StreamCard" in script
    assert "extract-stream" in script
    assert "v2ExtractCard" in script
    assert "$('v2-extract-list').classList.toggle('hidden', !isV2)" in script
    assert "v2-playback-notice" in script
    assert "decodeAudioData" in script
    assert "Not playable in this browser; original download remains available." in script
    assert "!state.playbackReady" in script


def test_frontend_shared_session_activation_replaces_v1_v2_status_and_controls():
    """Exercise the session path used after Create and verify both version transitions."""
    script_path = ROOT / "frontend" / "js" / "app.js"
    assert "if (session) await openSession(session, activation);" in script_path.read_text("utf-8")
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
    assert "$('seek').addEventListener('input', previewSeek)" in script
    assert "$('seek').addEventListener('change', commitSeek)" in script

def test_frontend_direct_open_invalidates_failed_stale_and_rapid_transitions():
    """Exercise direct-open races with controlled promises; this does not test audible playback."""
    script_path = ROOT / "frontend" / "js" / "app.js"
    runner = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(process.argv[1], 'utf8') + '\nglobalThis.__vmaTest = { handleOpenSubmit, openSession, start, state };';

function deferred() { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function element() {
  const classes = new Set(); const submit = { disabled: false, textContent: '', dataset: { label: 'Open VMA' } };
  return {
    textContent: '', innerHTML: '', disabled: false, value: '1', max: '0', href: '', dataset: {}, files: [],
    classList: {
      add(name) { classes.add(name); }, remove(name) { classes.delete(name); },
      toggle(name, force) { const present = force === undefined ? !classes.has(name) : force; if (present) classes.add(name); else classes.delete(name); return present; },
      contains(name) { return classes.has(name); },
    },
    addEventListener() {}, setAttribute() {}, querySelector() { return submit; },
  };
}
const nodes = new Map();
const document = {
  getElementById(id) { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); },
  querySelectorAll() { return []; },
  createElement() { return { _text: '', set textContent(value) { this._text = String(value); }, get innerHTML() { return this._text; } }; },
};
const payload = (session, version = 1) => version === 1 ? {
  session_id: session, version: 1, duration_seconds: 1, metadata: { title: session }, streams: [
    { stream_type: 'vocal', codec: 'PCM', audio: { sample_rate: 44100, channels: 1, bit_depth: 16 }, start_seconds: 0, duration_seconds: 1 },
    { stream_type: 'music', codec: 'PCM', audio: { sample_rate: 44100, channels: 1, bit_depth: 16 }, start_seconds: 0, duration_seconds: 1 },
  ],
} : {
  session_id: session, version: 2, duration_seconds: 0, metadata: { title: session }, streams: [
    { stream_id: 1, label: 'Vocal', role_name: 'AUDIO_PRIMARY', format_id: 0, payload_size: 1, start_seconds: 0, download_filename: 'vocal.mp3' },
    { stream_id: 2, label: 'Music', role_name: 'AUDIO_SUPPLEMENTAL', format_id: 0, payload_size: 1, start_seconds: 0, download_filename: 'music.ogg' },
  ],
};

globalThis.document = document;
globalThis.window = { setTimeout() {} };
globalThis.FormData = class { constructor(form) { this.form = form; } };
globalThis.URL = { createObjectURL() { return 'blob:test'; }, revokeObjectURL() {} };
globalThis.setInterval = () => 1; globalThis.clearInterval = () => {};
let stoppedSources = 0; let pendingDecode = null; let pendingDecodeStarted = null;
globalThis.AudioContext = class {
  constructor() { this.currentTime = 0; this.destination = {}; }
  createGain() { return { gain: { value: 0 }, connect() {} }; }
  createBufferSource() { return { connect() {}, start() {}, stop() { stoppedSources += 1; } }; }
  decodeAudioData(bytes) {
    const marker = new Uint8Array(bytes)[0];
    if (marker === 9) { if (pendingDecodeStarted) pendingDecodeStarted.resolve(); return pendingDecode.promise; }
    return Promise.resolve({ duration: marker || 1 });
  }
  resume() { return Promise.resolve(); }
};

const openRequests = [];
globalThis.fetch = async (url) => {
  if (url === '/api/open') return openRequests.shift().promise;
  if (url.includes('/stream/') || url.includes('/extract-stream/')) {
    const marker = url.includes('/pending/') ? 9 : 1;
    return { ok: true, arrayBuffer: async () => new Uint8Array([marker]).buffer };
  }
  const session = url.split('/').pop();
  return { ok: true, json: async () => payload(session, session.startsWith('v2') ? 2 : 1) };
};

eval(source);
const openForm = document.getElementById('open-form');
const vmaInput = document.getElementById('vma-input');
const submitOpen = () => globalThis.__vmaTest.handleOpenSubmit({ preventDefault() {}, currentTarget: openForm, target: openForm });
const okResponse = (body) => ({ ok: true, json: async () => body });

(async () => {
  await globalThis.__vmaTest.openSession('ready');
  await globalThis.__vmaTest.start();
  assert.equal(globalThis.__vmaTest.state.playbackReady, true);
  vmaInput.files = [{ name: 'corrupt.vma' }];
  const failed = deferred(); openRequests.push(failed);
  const failedOpen = submitOpen();
  assert.equal(globalThis.__vmaTest.state.meta, null);
  assert.equal(globalThis.__vmaTest.state.playbackReady, false);
  assert.equal(document.getElementById('vma-details').classList.contains('hidden'), true);
  assert.equal(document.getElementById('player-panel').classList.contains('hidden'), true);
  assert.ok(stoppedSources >= 2);
  failed.resolve({ ok: false, status: 422, text: async () => JSON.stringify({ detail: 'Corrupt VMA file.' }) });
  await failedOpen;
  assert.equal(document.getElementById('open-status').textContent, 'Corrupt VMA file.');
  assert.equal(globalThis.__vmaTest.state.playbackReady, false);

  vmaInput.files = [{ name: 'ready-again.vma' }];
  const recovery = deferred(); openRequests.push(recovery);
  const recoveryOpen = submitOpen();
  recovery.resolve(okResponse(payload('ready-again', 1))); await recoveryOpen;
  assert.equal(globalThis.__vmaTest.state.session, 'ready-again');
  assert.equal(globalThis.__vmaTest.state.playbackReady, true);
  await globalThis.__vmaTest.start();
  assert.equal(globalThis.__vmaTest.state.playing, true);

  vmaInput.files = [];
  await submitOpen();
  assert.equal(globalThis.__vmaTest.state.meta, null);
  assert.equal(globalThis.__vmaTest.state.playbackReady, false);
  assert.equal(document.getElementById('open-status').textContent, 'Select a VMA file before opening it.');

  pendingDecode = deferred(); pendingDecodeStarted = deferred();
  const oldDecode = globalThis.__vmaTest.openSession('pending');
  await pendingDecodeStarted.promise;
  vmaInput.files = [{ name: 'v2-current.vma' }];
  const current = deferred(); openRequests.push(current);
  const currentOpen = submitOpen();
  current.resolve(okResponse(payload('v2-current', 2)));
  await currentOpen;
  const currentStatus = document.getElementById('open-status').textContent;
  pendingDecode.resolve({ duration: 99 });
  await oldDecode;
  assert.equal(globalThis.__vmaTest.state.session, 'v2-current');
  assert.equal(globalThis.__vmaTest.state.duration, 1);
  assert.equal(document.getElementById('open-status').textContent, currentStatus);
  assert.equal(document.getElementById('v2-playback-notice').classList.contains('hidden'), false);

  const staleResume = deferred();
  globalThis.__vmaTest.state.context.resume = () => staleResume.promise;
  const staleStart = globalThis.__vmaTest.start();
  const first = deferred(); const second = deferred(); openRequests.push(first, second);
  vmaInput.files = [{ name: 'first.vma' }]; const firstOpen = submitOpen();
  vmaInput.files = [{ name: 'second.vma' }]; const secondOpen = submitOpen();
  first.resolve(okResponse(payload('first', 1))); await firstOpen;
  assert.equal(globalThis.__vmaTest.state.session, null);
  assert.equal(document.getElementById('open-status').textContent, 'Validating VMA…');
  assert.equal(openForm.querySelector().disabled, true);
  second.resolve(okResponse(payload('second', 1))); await secondOpen;
  const secondStatus = document.getElementById('open-status').textContent;
  staleResume.reject(new Error('late autoplay rejection')); await staleStart;
  assert.equal(globalThis.__vmaTest.state.session, 'second');
  assert.equal(document.getElementById('open-status').textContent, secondStatus);
  assert.equal(document.getElementById('player-panel').classList.contains('hidden'), false);
})().catch((error) => { console.error(error.stack); process.exit(1); });
'''
    result = subprocess.run(
        ["node", "-e", runner, str(script_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
