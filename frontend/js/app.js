const state = { session: null, meta: null, demo: false, context: null, master: null, gains: {}, analysers: {}, buffers: {}, sources: {}, position: 0, startedAt: 0, playing: false, scrubbing: false, muted: { vocal: false, music: false }, timer: null, visualizationFrame: null, activation: 0, duration: 0, playbackStreams: {}, playbackStates: {}, playbackReady: false, playbackLoading: false };
const $ = (id) => document.getElementById(id);
const fmtTime = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;

function initializeTheme() {
  const root = document.documentElement; const button = $('theme-toggle');
  if (!root || !button) return;
  const syncButton = () => {
    const light = root.dataset.theme === 'light';
    button.setAttribute('aria-pressed', String(light));
    button.setAttribute('aria-label', `Switch to ${light ? 'dark' : 'light'} theme`);
    const label = button.querySelector('.theme-label'); if (label) label.textContent = light ? 'Light' : 'Dark';
    const icon = button.querySelector('.theme-icon'); if (icon) icon.textContent = light ? '☀' : '☾';
  };
  syncButton();
  button.addEventListener('click', () => {
    const theme = root.dataset.theme === 'light' ? 'dark' : 'light';
    root.dataset.theme = theme;
    try { window.localStorage.setItem('vma-theme', theme); } catch {}
    syncButton();
  });
}
initializeTheme();

function initializeNavigation() {
  const button = $('nav-toggle'); const navigation = $('site-nav');
  if (!button || !navigation) return;
  const close = () => { navigation.dataset.open = 'false'; button.setAttribute('aria-expanded', 'false'); };
  button.addEventListener('click', () => {
    const open = navigation.dataset.open !== 'true';
    navigation.dataset.open = String(open); button.setAttribute('aria-expanded', String(open));
  });
  document.querySelectorAll('#site-nav a').forEach((link) => link.addEventListener('click', close));
}
initializeNavigation();

const viewMeta = {
  home: ['VMA workspace', 'Home'],
  create: ['New container', 'Create VMA'],
  open: ['Existing container', 'Open VMA'],
  inspect: ['Container intelligence', 'Inspect & Validate'],
  playback: ['Synchronized audio', 'Playback'],
  extract: ['Recover stored content', 'Extract'],
  format: ['Documentation', 'Format Guide'],
  help: ['Support', 'Help / FAQ'],
};
function routeFromHash() {
  if (!window.location) return 'home';
  const route = String(window.location.hash || '').replace(/^#\/?/, '').split('/')[0];
  return Object.hasOwn(viewMeta, route) ? route : 'home';
}
function showView(route, focus = false) {
  if (!Object.hasOwn(viewMeta, route)) route = 'home';
  document.querySelectorAll('[data-view]').forEach((view) => view.classList.toggle('hidden', view.dataset.view !== route));
  document.querySelectorAll('[data-route]').forEach((link) => {
    if (link.dataset.route === route) link.setAttribute('aria-current', 'page');
    else if (link.removeAttribute) link.removeAttribute('aria-current');
  });
  const [kicker, title] = viewMeta[route];
  if ($('view-kicker')) $('view-kicker').textContent = kicker;
  if ($('view-title')) $('view-title').textContent = title;
  const nav = $('site-nav'); const toggle = $('nav-toggle');
  if (nav) nav.dataset.open = 'false';
  if (toggle) toggle.setAttribute('aria-expanded', 'false');
  if (route === 'playback' && state.playing) startVisualization();
  else if (route !== 'playback') stopVisualization(true);
  if (focus && $('view-content')?.focus) $('view-content').focus({ preventScroll: true });
}
function navigateView(route) {
  if (!window.location) return;
  const hash = `#/${route}`;
  if (window.location.hash === hash) showView(route, true);
  else window.location.hash = hash;
}
function initializeRouter() {
  if (!window.location || !window.addEventListener) return;
  window.addEventListener('hashchange', () => showView(routeFromHash(), true));
  showView(routeFromHash());
}
initializeRouter();

function status(id, message, error = false) { const node = $(id); node.textContent = message; node.classList.toggle('error', error); node.dataset.state = error ? 'error' : message ? 'success' : ''; }
function setWorking(form, working, label) { const button = form.querySelector('button[type="submit"]'); button.disabled = working; button.textContent = working ? label : button.dataset.label; form.setAttribute('aria-busy', String(working)); }
function activeVmaStatus() {
  const playable = Object.values(state.playbackStreams).filter(({ buffer }) => buffer);
  const names = playable.map(({ label }) => label).join(' and ');
  if (playable.length === 2) return state.meta.version === 2 ? 'VMA v2 opened. Both original streams are ready for browser playback.' : 'VMA opened and ready to play.';
  if (playable.length === 1) return `${state.meta.version === 2 ? 'VMA v2 opened.' : 'VMA opened.'} Only ${names} is playable in this browser; the other original stream remains available for download.`;
  return `${state.meta.version === 2 ? 'VMA v2 opened.' : 'VMA opened.'} Browser playback is unavailable for these streams; download the original stream files below.`;
}
async function responseError(response) { const text = await response.text(); try { const payload = JSON.parse(text); return payload.detail || `Request failed (${response.status})`; } catch { return text.trim() || `Request failed (${response.status})`; } }
async function describeWav(file) {
  if (!file) return '';
  const bytes = new Uint8Array(await file.arrayBuffer()); const view = new DataView(bytes.buffer);
  if (bytes.length < 12 || String.fromCharCode(...bytes.slice(0, 4)) !== 'RIFF' || String.fromCharCode(...bytes.slice(8, 12)) !== 'WAVE') return `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
  let position = 12, fmt, dataSize = 0;
  while (position + 8 <= bytes.length) { const id = String.fromCharCode(...bytes.slice(position, position + 4)); const size = view.getUint32(position + 4, true); if (position + 8 + size > bytes.length) break; if (id === 'fmt ' && size >= 16) fmt = { channels: view.getUint16(position + 10, true), rate: view.getUint32(position + 12, true), bits: view.getUint16(position + 22, true), align: view.getUint16(position + 20, true) }; if (id === 'data') dataSize = size; position += 8 + size + (size % 2); }
  if (!fmt || !dataSize || !fmt.align) return `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
  return `${file.name} · ${(dataSize / fmt.align / fmt.rate).toFixed(2)}s · ${fmt.rate} Hz · ${fmt.channels === 1 ? 'Mono' : `${fmt.channels} channels`} · ${fmt.bits}-bit`;
}
['vocal-input', 'music-input'].forEach((id) => $(id).addEventListener('change', async () => { const summaries = await Promise.all([$('vocal-input').files[0], $('music-input').files[0]].map(describeWav)); $('source-info').textContent = summaries.filter(Boolean).join('  |  ') || 'Choose two files (any audio format, unknown format, or binary payload).'; }));

function clearCreateResult() {
  const link = $('download-vma');
  if (link.dataset.url) URL.revokeObjectURL(link.dataset.url);
  link.dataset.url = ''; link.removeAttribute?.('href'); link.classList.add('hidden');
  $('create-result').classList.add('hidden'); $('create-result-filename').textContent = 'song.vma';
}
function downloadFilename(response) {
  const disposition = response.headers.get('Content-Disposition') || '';
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const quoted = disposition.match(/filename="?([^";]+)"?/i);
  let name = encoded ? decodeURIComponent(encoded[1]) : quoted ? quoted[1] : 'song.vma';
  name = name.split(/[\\/]/).pop().trim();
  return name || 'song.vma';
}
async function handleCreateSubmit(event) {
  event.preventDefault(); const form = event.currentTarget;
  clearCreateResult(); status('create-status', '');
  if (!$('vocal-input').files[0] || !$('music-input').files[0]) { status('create-status', 'Select both a vocal and a music stream before creating VMA.', true); return; }
  const activation = beginVmaTransition(); form.dataset.activation = String(activation);
  setWorking(form, true, 'Creating VMA…'); status('create-status', 'Creating VMA…');
  try {
    const response = await fetch('/api/create', { method: 'POST', body: new FormData(event.target) });
    if (activation !== state.activation) return;
    if (!response.ok) throw new Error(await responseError(response));
    const blob = await response.blob();
    if (activation !== state.activation) return;
    const url = URL.createObjectURL(blob); const link = $('download-vma'); const filename = downloadFilename(response);
    link.href = url; link.dataset.url = url; link.download = filename; link.textContent = `Download ${filename}`; link.classList.remove('hidden');
    const session = response.headers.get('X-VMA-Session');
    if (session) await openSession(session, activation);
    if (activation !== state.activation) return;
    $('create-result-filename').textContent = filename; $('create-result').classList.remove('hidden');
    status('create-status', 'VMA created successfully. Download it now, or choose an optional next step below.');
  } catch (error) { if (activation === state.activation) status('create-status', error.message, true); } finally { if (form.dataset.activation === String(activation)) setWorking(form, false); }
}
$('create-form').addEventListener('submit', handleCreateSubmit);

async function handleOpenSubmit(event) {
  event.preventDefault(); const form = event.currentTarget;
  const activation = beginVmaTransition();
  if (!$('vma-input').files[0]) { status('open-status', 'Select a VMA file before opening it.', true); return; }
  form.dataset.activation = String(activation);
  setWorking(form, true, 'Opening VMA…'); status('open-status', 'Validating VMA…');
  try {
    const response = await fetch('/api/open', { method: 'POST', body: new FormData(event.target) });
    if (activation !== state.activation) return;
    if (!response.ok) throw new Error(await responseError(response));
    const payload = await response.json();
    if (activation !== state.activation) return;
    await activateVma(payload, activation);
    if (activation === state.activation) navigateView('inspect');
  } catch (error) { if (activation === state.activation) status('open-status', error.message, true); } finally { if (form.dataset.activation === String(activation)) setWorking(form, false); }
}
$('open-form').addEventListener('submit', handleOpenSubmit);

async function handleDemoOpen(event) {
  const button = event?.currentTarget || $('try-demo'); const previousLabel = button.textContent; const observedActivation = state.activation;
  button.disabled = true; button.textContent = 'Loading demo…'; status('demo-status', 'Preparing the synthetic welcome demo…');
  try {
    const response = await fetch('/api/demo', { method: 'POST' });
    if (!response.ok) throw new Error(await responseError(response));
    const payload = await response.json();
    if (observedActivation !== state.activation) return;
    const activation = beginVmaTransition();
    await activateVma(payload, activation);
    if (activation !== state.activation) return;
    status('demo-status', 'Welcome demo loaded in the synchronized player.');
    navigateView('playback');
  } catch (error) {
    if (observedActivation === state.activation) status('demo-status', error.message, true);
  } finally { button.disabled = false; button.textContent = previousLabel; }
}
$('try-demo').addEventListener('click', handleDemoOpen);
$('quick-demo').addEventListener('click', handleDemoOpen);
document.querySelectorAll('[data-demo-trigger]').forEach((button) => button.addEventListener('click', handleDemoOpen));

function handleUseOwnFiles(event) {
  if (state.demo) beginVmaTransition();
  const target = event?.currentTarget?.dataset?.route;
  if (target) navigateView(target);
}
document.querySelectorAll('[data-action="use-own-files"]').forEach((link) => link.addEventListener('click', handleUseOwnFiles));

async function deleteCurrentSession() {
  const session = state.session;
  if (!session) return;
  const button = $('delete-session');
  button.disabled = true;
  status('session-status', 'Deleting this browser session…');
  try {
    const response = await fetch(`/api/vma/${session}`, { method: 'DELETE' });
    if (!response.ok) throw new Error(await responseError(response));
    if (state.session !== session) return;
    beginVmaTransition();
    navigateView('home');
    status('demo-status', 'Session deleted from this browser.');
  } catch (error) {
    if (state.session === session) status('session-status', error.message, true);
  } finally {
    button.disabled = false;
  }
}
$('delete-session').addEventListener('click', deleteCurrentSession);

function beginVmaTransition() {
  const activation = ++state.activation;
  stop();
  state.session = null; state.meta = null; state.demo = false; state.buffers = {}; state.playbackStreams = {}; state.playbackStates = {}; state.position = 0; state.duration = 0; state.playbackReady = false; state.playbackLoading = false; state.scrubbing = false;
  $('metadata-list').innerHTML = ''; $('stream-list').innerHTML = ''; status('open-status', ''); status('demo-status', ''); status('session-status', ''); $('v2-playback-notice').textContent = '';
  $('vma-details').classList.add('hidden'); $('demo-notice').classList.add('hidden'); $('player-panel').classList.add('hidden'); $('v2-playback-notice').classList.add('hidden'); $('extract-panel').classList.add('hidden');
  $('inspect-empty').classList.remove('hidden'); $('playback-empty').classList.remove('hidden'); $('extract-empty').classList.remove('hidden'); $('session-strip').classList.add('hidden');
  $('session-chip').dataset.state = 'empty'; $('session-chip-text').textContent = 'No VMA loaded';
  $('v1-extract-actions').classList.remove('hidden'); $('v2-extract-list').classList.add('hidden'); $('v2-extract-list').innerHTML = '';
  ['play', 'pause', 'stop'].forEach((id) => { $(id).disabled = true; });
  $('seek').max = 0; $('seek').value = 0; updateTime();
  return activation;
}
async function openSession(session, activation = beginVmaTransition()) {
  const response = await fetch(`/api/vma/${session}`);
  if (activation !== state.activation) return;
  if (!response.ok) throw new Error(await responseError(response));
  const payload = await response.json();
  if (activation !== state.activation) return;
  await activateVma(payload, activation);
}
async function activateVma(payload, activation = beginVmaTransition()) {
  if (activation !== state.activation) return;
  state.session = payload.session_id; state.meta = payload; state.demo = payload.demo === true; state.buffers = {}; state.playbackStreams = {}; state.playbackStates = {}; state.position = 0; state.duration = 0; state.playbackReady = false; state.playbackLoading = true;
  showDetails(payload);
  status('open-status', `Checking browser playback for VMA v${payload.version} streams…`);
  await loadBuffers(activation);
  if (activation !== state.activation) return;
  state.playbackLoading = false;
  state.playbackReady = Object.values(state.playbackStreams).some(({ buffer }) => buffer);
  state.duration = playbackDuration(payload);
  renderWaveforms();
  showDetails(payload);
  status('open-status', activeVmaStatus(), !state.playbackReady);
}
function v1StreamCard(stream) {
  return `<article class="stream"><h3>${escapeHtml(stream.stream_type)}</h3><div>${escapeHtml(String(stream.codec))}</div><div>${stream.audio.sample_rate} Hz · ${stream.audio.channels === 1 ? 'Mono' : 'Stereo'} · ${stream.audio.bit_depth}-bit</div><div>Start ${stream.start_seconds.toFixed(3)}s · ${stream.duration_seconds.toFixed(3)}s</div></article>`;
}
function v2StreamCard(stream) {
  const format = stream.format_name ? `${stream.format_name} (0x${stream.format_id.toString(16).padStart(4, '0')})` : `FORMAT_ID 0x${stream.format_id.toString(16).padStart(4, '0')}`;
  const duration = stream.duration_seconds ? ` · ${stream.duration_seconds.toFixed(3)}s` : '';
  const playback = state.playbackStates[stream.stream_id] || 'Checking browser playback…';
  return `<article class="stream"><h3>${escapeHtml(stream.label)}</h3><div>${escapeHtml(stream.role_name)} · ${escapeHtml(format)}</div><div>${(stream.payload_size / 1024 / 1024).toFixed(2)} MB${duration} · Start ${stream.start_seconds.toFixed(3)}s</div><div>${escapeHtml(playback)}</div></article>`;
}
function v2ExtractCard(stream) {
  return `<a class="download extract-card" href="/api/vma/${state.session}/extract-stream/${stream.stream_id}" download="${escapeHtml(stream.download_filename)}"><b>⇩</b><strong>${escapeHtml(stream.label)}</strong><small>${escapeHtml(stream.download_filename)} · exact stored bytes</small></a>`;
}
function showDetails(data) {
  const isV2 = data.version === 2; const metadata = data.metadata || {};
  const title = metadata.title || 'Untitled'; const artist = metadata.artist || '—';
  const duration = Number(data.duration_seconds) || 0;
  $('metadata-list').innerHTML = `<dt>Container</dt><dd>VMA v${data.version}</dd><dt>Song</dt><dd>${escapeHtml(title)}</dd><dt>Artist</dt><dd>${escapeHtml(artist)}</dd><dt>Duration</dt><dd>${duration ? fmtTime(duration) : 'Unknown'}</dd>`;
  $('stream-list').innerHTML = isV2 ? data.streams.map(v2StreamCard).join('') : data.streams.map(v1StreamCard).join('');
  $('v2-playback-notice').classList.toggle('hidden', !isV2);
  $('demo-notice').classList.toggle('hidden', !state.demo);
  if (isV2) $('v2-playback-notice').textContent = v2PlaybackNotice();
  $('player-panel').classList.toggle('hidden', !state.playbackReady); $('extract-panel').classList.remove('hidden');
  $('inspect-empty').classList.add('hidden'); $('playback-empty').classList.toggle('hidden', state.playbackReady); $('extract-empty').classList.add('hidden');
  $('session-strip').classList.remove('hidden'); $('session-chip').dataset.state = state.demo ? 'demo' : 'active';
  $('session-chip-text').textContent = state.demo ? 'Demo loaded' : 'Personal VMA loaded';
  $('session-badge').textContent = state.demo ? 'Synthetic demo' : `VMA v${data.version}`;
  $('session-title').textContent = title; $('session-summary').textContent = `${data.streams.length} streams · ${duration ? fmtTime(duration) : 'duration pending'}`;
  $('v1-extract-actions').classList.toggle('hidden', isV2);
  $('v2-extract-list').classList.toggle('hidden', !isV2);
  $('v2-extract-list').innerHTML = isV2 ? data.streams.map(v2ExtractCard).join('') : '';
  ['play', 'pause', 'stop'].forEach((id) => { $(id).disabled = !state.playbackReady; });
  $('seek').max = state.duration || duration; $('seek').value = 0; updateTime();
  if (!isV2) {
    ['vocal', 'music'].forEach((kind) => { $(`extract-${kind}`).href = `/api/vma/${state.session}/extract/${kind}`; }); $('extract-all').href = `/api/vma/${state.session}/extract-all`;
  }
  $('vma-details').classList.remove('hidden');
}

function playbackInputs(payload) {
  return payload.streams.map((stream, index) => {
    const kind = payload.version === 1 ? stream.stream_type : (stream.role_name === 'AUDIO_PRIMARY' || index === 0 ? 'vocal' : 'music');
    const label = kind === 'vocal' ? 'Vocal' : 'Music / Instrumental';
    const endpoint = payload.version === 1 ? `/api/vma/${payload.session_id}/stream/${kind}` : `/api/vma/${payload.session_id}/extract-stream/${stream.stream_id}`;
    return { kind, label, stream, endpoint };
  }).filter(({ kind }, index, streams) => index === streams.findIndex((candidate) => candidate.kind === kind));
}
async function loadBuffers(activation) {
  ensureAudio();
  const streams = playbackInputs(state.meta);
  const results = await Promise.all(streams.map(async (entry) => {
    try {
      const response = await fetch(entry.endpoint);
      if (!response.ok) throw new Error('stream request failed');
      const buffer = await state.context.decodeAudioData(await response.arrayBuffer());
      return { ...entry, buffer, message: 'Playable in this browser.' };
    } catch {
      return { ...entry, buffer: null, message: 'Not playable in this browser; original download remains available.' };
    }
  }));
  if (activation !== state.activation) return;
  for (const entry of results) { state.playbackStreams[entry.kind] = entry; state.playbackStates[entry.stream.stream_id] = entry.message; if (entry.buffer) state.buffers[entry.kind] = entry.buffer; }
}
function drawWaveform(kind) {
  const canvas = $(`waveform-${kind}`); const entry = state.playbackStreams[kind];
  if (!canvas || !canvas.getContext) return;
  const context = canvas.getContext('2d'); if (!context) return;
  const width = canvas.width; const height = canvas.height; context.clearRect(0, 0, width, height);
  context.fillStyle = '#25272b'; context.fillRect(0, height / 2 - 1, width, 2);
  if (!entry?.buffer?.getChannelData) return;
  const samples = entry.buffer.getChannelData(0); const bars = 150; const stride = Math.max(1, Math.floor(samples.length / bars));
  context.fillStyle = kind === 'vocal' ? '#48b9ae' : '#ff7a1a';
  for (let bar = 0; bar < bars; bar += 1) {
    let peak = 0; const startIndex = bar * stride; const endIndex = Math.min(samples.length, startIndex + stride);
    for (let index = startIndex; index < endIndex; index += Math.max(1, Math.floor(stride / 48))) peak = Math.max(peak, Math.abs(samples[index] || 0));
    const barHeight = Math.max(3, peak * (height - 12)); const x = bar * width / bars; const barWidth = Math.max(2, width / bars - 2);
    context.fillRect(x, (height - barHeight) / 2, barWidth, barHeight);
  }
}
function renderWaveforms() { drawWaveform('vocal'); drawWaveform('music'); }
function drawSilentWaveform(kind) {
  const canvas = $('waveform-' + kind); if (!canvas?.getContext) return;
  const context = canvas.getContext('2d'); if (!context) return;
  context.clearRect(0, 0, canvas.width, canvas.height); context.fillStyle = '#25272b';
  context.fillRect(0, canvas.height / 2 - 1, canvas.width, 2);
}
function drawLiveWaveform(kind) {
  const canvas = $('waveform-' + kind); const analyser = state.analysers[kind];
  if (!canvas?.getContext || !analyser?.getByteTimeDomainData) return;
  const audible = state.sources[kind] && !state.muted[kind] && +$(kind + '-volume').value > 0 && +$('master-volume').value > 0;
  if (!audible) { drawSilentWaveform(kind); return; }
  const values = new Uint8Array(analyser.fftSize); analyser.getByteTimeDomainData(values);
  const context = canvas.getContext('2d'); if (!context) return;
  const width = canvas.width; const height = canvas.height; const bars = 90; const stride = Math.max(1, Math.floor(values.length / bars));
  const outputScale = +$(kind + '-volume').value * +$('master-volume').value;
  context.clearRect(0, 0, width, height); context.fillStyle = '#25272b'; context.fillRect(0, height / 2 - 1, width, 2);
  context.fillStyle = kind === 'vocal' ? '#48b9ae' : '#ff7a1a';
  for (let bar = 0; bar < bars; bar += 1) {
    let peak = 0;
    for (let index = bar * stride; index < Math.min(values.length, (bar + 1) * stride); index += 1) peak = Math.max(peak, Math.abs(values[index] - 128) / 128);
    const barHeight = Math.max(2, peak * outputScale * (height - 8)); const x = bar * width / bars;
    context.fillRect(x, (height - barHeight) / 2, Math.max(2, width / bars - 3), barHeight);
  }
}
function playbackViewVisible() {
  const view = document.querySelector?.('[data-view="playback"]');
  return !view || !view.classList.contains('hidden');
}
function reducedMotionPreferred() { return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true; }
function stopVisualization(restoreStatic = false) {
  if (state.visualizationFrame !== null && window.cancelAnimationFrame) window.cancelAnimationFrame(state.visualizationFrame);
  state.visualizationFrame = null;
  if (restoreStatic) renderWaveforms();
}
function startVisualization() {
  stopVisualization(false);
  if (!state.playing || !playbackViewVisible() || reducedMotionPreferred() || !window.requestAnimationFrame) { renderWaveforms(); return; }
  const frame = () => {
    if (!state.playing || !playbackViewVisible()) { stopVisualization(true); return; }
    drawLiveWaveform('vocal'); drawLiveWaveform('music');
    state.visualizationFrame = window.requestAnimationFrame(frame);
  };
  state.visualizationFrame = window.requestAnimationFrame(frame);
}
function updateWaveformPlayheads(position) {
  const percent = state.duration ? Math.min(100, Math.max(0, position / state.duration * 100)) : 0;
  ['vocal', 'music'].forEach((kind) => { const playhead = $(`waveform-${kind}-playhead`); if (playhead?.style) playhead.style.left = `${percent}%`; });
}
function playbackDuration(payload) {
  const decodedDuration = Math.max(0, ...Object.values(state.playbackStreams).map(({ buffer, stream }) => buffer ? (stream.start_seconds || 0) + buffer.duration : 0));
  return payload.version === 1 ? (Number(payload.duration_seconds) || decodedDuration) : decodedDuration;
}
function v2PlaybackNotice() {
  if (state.playbackLoading) return 'VMA v2 preserves the original stream bytes. Checking whether this browser can decode each stream for playback; downloads remain byte-exact.';
  if (!state.playbackReady) return 'VMA v2 preserves the original stream bytes for inspection and download. None of these streams can be decoded by this browser; download the originals to use another compatible player.';
  if (Object.values(state.playbackStreams).filter(({ buffer }) => buffer).length === 1) return 'VMA v2 preserves original stream bytes. One stream is playable in this browser; the other remains available for byte-exact download.';
  return 'VMA v2 preserves original stream bytes. Both streams decoded in this browser; downloads remain byte-exact originals.';
}
function ensureAudio() { if (state.context) return; state.context = new AudioContext(); state.master = state.context.createGain(); state.master.connect(state.context.destination); ['vocal', 'music'].forEach((kind) => { const gain = state.context.createGain(); gain.connect(state.master); state.gains[kind] = gain; if (state.context.createAnalyser) { const analyser = state.context.createAnalyser(); analyser.fftSize = 256; analyser.smoothingTimeConstant = 0.68; analyser.connect(gain); state.analysers[kind] = analyser; } }); syncGains(); }
function syncGains() { if (!state.master) return; state.master.gain.value = +$('master-volume').value; for (const kind of ['vocal', 'music']) state.gains[kind].gain.value = state.muted[kind] ? 0 : +$(`${kind}-volume`).value; }
async function start() { if (!state.meta || state.playing || !state.playbackReady) return; const activation = state.activation; ensureAudio(); try { await state.context.resume(); } catch { if (activation === state.activation) status('open-status', 'Browser playback could not start. Interact with the page and try Play again.', true); return; } if (activation !== state.activation || !state.playbackReady || state.playing) return; state.startedAt = state.context.currentTime - state.position; state.sources = {}; for (const [kind, { stream, buffer }] of Object.entries(state.playbackStreams)) { if (!buffer) continue; const source = state.context.createBufferSource(); source.buffer = buffer; source.connect(state.analysers[kind] || state.gains[kind]); const streamStart = stream.start_seconds || 0; if (state.position < streamStart + buffer.duration) { const when = state.context.currentTime + Math.max(0, streamStart - state.position); const offset = Math.max(0, state.position - streamStart); source.start(when, offset); state.sources[kind] = source; } } state.playing = true; startVisualization(); tick(); }
function pause() { if (!state.playing) return; state.position = currentPosition(); clearSources(); state.playing = false; stopVisualization(true); updateTime(); }
function stop() { clearSources(); state.playing = false; state.scrubbing = false; stopVisualization(true); state.position = 0; $('seek').value = 0; updateTime(); }
function clearSources() { Object.values(state.sources).forEach((source) => { try { source.stop(); } catch {} }); state.sources = {}; clearInterval(state.timer); state.timer = null; }
function currentPosition() { return Math.min(state.duration || 0, Math.max(0, state.context.currentTime - state.startedAt)); }
function tick() { clearInterval(state.timer); state.timer = setInterval(() => { if (!state.playing || state.scrubbing) return; state.position = currentPosition(); if (state.position >= state.duration) { stop(); return; } $('seek').value = state.position; updateTime(); }, 80); }
function boundedPosition(value) { const position = Number(value); return Math.min(state.duration || 0, Math.max(0, Number.isFinite(position) ? position : 0)); }
function previewSeek(event) { state.scrubbing = true; updateTime(boundedPosition(event.target.value)); }
function commitSeek(event) { const wasPlaying = state.playing; clearSources(); state.playing = false; stopVisualization(true); state.scrubbing = false; state.position = boundedPosition(event.target.value); $('seek').value = state.position; updateTime(); if (wasPlaying && state.position < state.duration) start(); }
function updateTime(position = state.position) { $('time').textContent = `${fmtTime(position)} / ${fmtTime(state.duration || 0)}`; updateWaveformPlayheads(position); }
function escapeHtml(value) { const node = document.createElement('span'); node.textContent = value; return node.innerHTML; }
$('play').addEventListener('click', start); $('pause').addEventListener('click', pause); $('stop').addEventListener('click', stop);
$('seek').addEventListener('input', previewSeek);
$('seek').addEventListener('change', commitSeek);
['master-volume', 'vocal-volume', 'music-volume'].forEach((id) => $(id).addEventListener('input', syncGains));
['vocal', 'music'].forEach((kind) => $(`${kind}-mute`).addEventListener('click', () => { state.muted[kind] = !state.muted[kind]; $(`${kind}-mute`).textContent = state.muted[kind] ? `Unmute ${kind}` : `Mute ${kind}`; syncGains(); }));
['vocal', 'music', 'all'].forEach((kind) => $(`extract-${kind}`).addEventListener('click', (event) => { if (!state.session) return; status('extract-status', `Preparing ${kind === 'all' ? 'both tracks' : `${kind} track`} download…`); window.setTimeout(() => status('extract-status', 'Download started.'), 250); }));
document.querySelectorAll('form button[type="submit"]').forEach((button) => { button.dataset.label = button.textContent; });
