const state = { session: null, meta: null, context: null, master: null, gains: {}, buffers: {}, sources: {}, position: 0, startedAt: 0, playing: false, muted: { vocal: false, music: false }, timer: null };
const $ = (id) => document.getElementById(id);
const fmtTime = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;

function status(id, message, error = false) { const node = $(id); node.textContent = message; node.classList.toggle('error', error); }
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
['vocal-input', 'music-input'].forEach((id) => $(id).addEventListener('change', async () => { const summaries = await Promise.all([$('vocal-input').files[0], $('music-input').files[0]].map(describeWav)); $('source-info').textContent = summaries.filter(Boolean).join('  |  ') || 'Choose two PCM WAV files.'; }));

$('create-form').addEventListener('submit', async (event) => {
  event.preventDefault(); status('create-status', 'Creating VMA…'); $('download-vma').classList.add('hidden');
  try {
    const response = await fetch('/api/create', { method: 'POST', body: new FormData(event.target) });
    if (!response.ok) throw new Error(await responseError(response));
    const url = URL.createObjectURL(await response.blob()); const link = $('download-vma');
    if (link.dataset.url) URL.revokeObjectURL(link.dataset.url); link.href = url; link.dataset.url = url; link.classList.remove('hidden'); status('create-status', 'VMA created successfully.');
  } catch (error) { status('create-status', error.message, true); }
});

$('open-form').addEventListener('submit', async (event) => {
  event.preventDefault(); stop(); status('open-status', 'Validating VMA…');
  try {
    const response = await fetch('/api/open', { method: 'POST', body: new FormData(event.target) });
    if (!response.ok) throw new Error(await responseError(response)); const payload = await response.json();
    state.session = payload.session_id; state.meta = payload; state.buffers = {}; state.position = 0;
    showDetails(payload); await loadBuffers(); status('open-status', 'VMA opened and ready to play.');
  } catch (error) { status('open-status', error.message, true); }
});

function showDetails(data) {
  const title = data.metadata.title || 'Untitled'; const artist = data.metadata.artist || '—';
  $('metadata-list').innerHTML = `<dt>Song</dt><dd>${escapeHtml(title)}</dd><dt>Artist</dt><dd>${escapeHtml(artist)}</dd><dt>Duration</dt><dd>${fmtTime(data.duration_seconds)}</dd>`;
  $('stream-list').innerHTML = data.streams.map((s) => `<article class="stream"><h3>${escapeHtml(s.stream_type)}</h3><div>${s.codec}</div><div>${s.audio.sample_rate} Hz · ${s.audio.channels === 1 ? 'Mono' : 'Stereo'} · ${s.audio.bit_depth}-bit</div><div>Start ${s.start_seconds.toFixed(3)}s · ${s.duration_seconds.toFixed(3)}s</div></article>`).join('');
  $('seek').max = data.duration_seconds; $('seek').value = 0; updateTime(); $('vma-details').classList.remove('hidden');
  ['vocal', 'music'].forEach((kind) => { $(`extract-${kind}`).href = `/api/vma/${state.session}/extract/${kind}`; }); $('extract-all').href = `/api/vma/${state.session}/extract-all`;
}

async function loadBuffers() {
  ensureAudio();
  for (const kind of ['vocal', 'music']) { const response = await fetch(`/api/vma/${state.session}/stream/${kind}`); if (!response.ok) throw new Error(`Unable to load ${kind} stream`); state.buffers[kind] = await state.context.decodeAudioData(await response.arrayBuffer()); }
}
function ensureAudio() { if (state.context) return; state.context = new AudioContext(); state.master = state.context.createGain(); state.master.connect(state.context.destination); ['vocal', 'music'].forEach((kind) => { const gain = state.context.createGain(); gain.connect(state.master); state.gains[kind] = gain; }); syncGains(); }
function syncGains() { if (!state.master) return; state.master.gain.value = +$('master-volume').value; for (const kind of ['vocal', 'music']) state.gains[kind].gain.value = state.muted[kind] ? 0 : +$(`${kind}-volume`).value; }
function start() { if (!state.meta || state.playing) return; ensureAudio(); state.context.resume(); state.startedAt = state.context.currentTime - state.position; state.sources = {}; for (const stream of state.meta.streams) { const kind = stream.stream_type; const buffer = state.buffers[kind]; const source = state.context.createBufferSource(); source.buffer = buffer; source.connect(state.gains[kind]); const start = stream.start_seconds; if (state.position < start + buffer.duration) { const when = state.context.currentTime + Math.max(0, start - state.position); const offset = Math.max(0, state.position - start); source.start(when, offset); state.sources[kind] = source; } } state.playing = true; tick(); }
function pause() { if (!state.playing) return; state.position = currentPosition(); clearSources(); state.playing = false; updateTime(); }
function stop() { clearSources(); state.playing = false; state.position = 0; $('seek').value = 0; updateTime(); }
function clearSources() { Object.values(state.sources).forEach((source) => { try { source.stop(); } catch {} }); state.sources = {}; clearInterval(state.timer); state.timer = null; }
function currentPosition() { return Math.min(state.meta?.duration_seconds || 0, Math.max(0, state.context.currentTime - state.startedAt)); }
function tick() { clearInterval(state.timer); state.timer = setInterval(() => { if (!state.playing) return; state.position = currentPosition(); if (state.position >= state.meta.duration_seconds) { stop(); return; } $('seek').value = state.position; updateTime(); }, 80); }
function updateTime() { const duration = state.meta?.duration_seconds || 0; $('time').textContent = `${fmtTime(state.position)} / ${fmtTime(duration)}`; }
function escapeHtml(value) { const node = document.createElement('span'); node.textContent = value; return node.innerHTML; }
$('play').addEventListener('click', start); $('pause').addEventListener('click', pause); $('stop').addEventListener('click', stop);
$('seek').addEventListener('input', (event) => { state.position = +event.target.value; if (state.playing) { clearSources(); state.playing = false; start(); } updateTime(); });
['master-volume', 'vocal-volume', 'music-volume'].forEach((id) => $(id).addEventListener('input', syncGains));
['vocal', 'music'].forEach((kind) => $(`${kind}-mute`).addEventListener('click', () => { state.muted[kind] = !state.muted[kind]; $(`${kind}-mute`).textContent = state.muted[kind] ? `Unmute ${kind}` : `Mute ${kind}`; syncGains(); }));
