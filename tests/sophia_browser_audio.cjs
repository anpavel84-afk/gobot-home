'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {Playback, Capture, BrowserVoice, eligibility} = require('../services/phone/dist/sophia-audio.js');
const pcm = (samples, value = 100) => Buffer.from(new Int16Array(samples).fill(value).buffer).toString('base64');

class Context {
  constructor() {
    this.currentTime = 0; this.state = 'running'; this.destination = {}; this.sources = [];
    this.audioWorklet = {addModule: async () => {}};
  }
  async resume() { this.state = 'running'; }
  createBuffer(_channels, length) { return {getChannelData: () => new Float32Array(length)}; }
  createBufferSource() {
    const source = {connect() {}, disconnect() {}, start(time) { this.time = time; }, stop() { this.stopped = true; this.onended?.(); }};
    this.sources.push(source); return source;
  }
  createMediaStreamSource() { return {connect() {}, disconnect() {}}; }
  createGain() { return {gain: {value: 1}, connect() { return this; }, disconnect() {}}; }
}

function audio() {
  const context = new Context(), events = [], drained = [];
  const playback = new Playback(context, event => events.push(event), {onDrained: role => drained.push(role)});
  return {context, events, drained, playback};
}

test('segments and whole response ACK follow actual WebAudio end, never delivery', () => {
  const {context, events, playback, drained} = audio();
  playback.begin({response_id: 'answer', audio_role: 'expert_answer'});
  playback.append({response_id: 'answer', pcm: pcm(240), sample_rate: 24000});
  playback.segment({response_id: 'answer', segment_id: 'sentence-1'});
  playback.append({response_id: 'answer', pcm: pcm(480)});
  playback.segment({response_id: 'answer', segment_id: 'sentence-2'});
  playback.end({response_id: 'answer', reason: 'finished'});
  assert.equal(events.length, 0);
  context.sources[0].onended();
  assert.deepEqual(events, [
    {type: 'playback_started', response_id: 'answer'},
    {type: 'playback_progress', response_id: 'answer', played_samples: 240},
    {type: 'playback_finished', response_id: 'answer', segment_id: 'sentence-1'},
  ]);
  context.sources[1].onended();
  assert.deepEqual(events.slice(3), [
    {type: 'playback_progress', response_id: 'answer', played_samples: 720},
    {type: 'playback_finished', response_id: 'answer', segment_id: 'sentence-2'},
    {type: 'playback_finished', response_id: 'answer'},
  ]);
  assert.deepEqual(drained, ['expert_answer']);
});

test('out-of-order callbacks cannot cross an unplayed segment fence', () => {
  const {context, events, playback} = audio();
  playback.begin({response_id: 'answer'});
  playback.append({response_id: 'answer', pcm: pcm(240)});
  playback.append({response_id: 'answer', pcm: pcm(240)});
  playback.segment({response_id: 'answer', segment_id: 'both'});
  playback.end({response_id: 'answer', reason: 'finished'});
  context.sources[1].onended();
  assert.equal(events.filter(x => x.type === 'playback_finished').length, 0);
  context.sources[0].onended();
  assert.equal(events.filter(x => x.type === 'playback_finished').length, 2);
});

test('cancellation suppresses all pending completion callbacks and buffers are bounded', () => {
  const {context, events, playback} = audio();
  playback.begin({response_id: 'cancelled'});
  playback.append({response_id: 'cancelled', pcm: pcm(240)});
  playback.segment({response_id: 'cancelled', segment_id: 'never-played'});
  playback.end({response_id: 'cancelled', reason: 'finished'});
  const lateEnd = context.sources[0].onended;
  playback.cancel(); lateEnd();
  assert.equal(events.length, 0);
  assert.equal(context.sources[0].stopped, true);
  playback.begin({response_id: 'bounded'});
  for (let i=0; i<20; i++) playback.append({response_id: 'bounded', pcm: pcm(24000)});
  assert.throws(() => playback.append({response_id: 'bounded', pcm: pcm(24)}), /queue_overflow/);
  playback.cancel();
});

test('cue completion is separate from the answer, empty audio cannot fabricate completion', () => {
  const {context, events, playback, drained} = audio();
  playback.begin({response_id: 'cue', audio_role: 'service_cue'});
  playback.append({response_id: 'cue', pcm: pcm(240)});
  playback.end({response_id: 'cue', reason: 'finished'});
  context.sources[0].onended();
  assert.deepEqual(drained, ['service_cue']);
  assert.equal(events.at(-1).response_id, 'cue');
  playback.begin({response_id: 'answer'});
  playback.end({response_id: 'answer', reason: 'finished'});
  assert.equal(events.some(e => e.response_id === 'answer'), false);
  playback.cancel();
});

function browserEnvironment(t, status) {
  const counts = {microphones: 0, sockets: [], tracksStopped: 0, errors: []};
  const store = new Map();
  class Worklet {
    constructor() { this.port = {messages: [], postMessage(message) { this.messages.push(message); }}; }
    connect() { return {connect() {}}; }
    disconnect() {}
  }
  class Socket {
    constructor(url) { this.url = String(url); this.readyState = 0; this.bufferedAmount = 0; this.sent = []; counts.sockets.push(this); }
    open() { this.readyState = 1; this.onopen?.(); }
    send(data) { this.sent.push(data); }
    close() { this.readyState = 3; this.onclose?.(); }
    event(type, data) { this.onmessage?.({data: JSON.stringify({type, data})}); }
  }
  const values = {
    isSecureContext: true, AudioContext: Context, AudioWorkletNode: Worklet, WebSocket: Socket,
    location: {href: 'https://plan.tailffc57c.ts.net/sophia', protocol: 'https:'},
    sessionStorage: {getItem: key => store.get(key) || null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key)},
    navigator: {mediaDevices: {getUserMedia: async () => {
      counts.microphones++;
      const track = {stop() { counts.tracksStopped++; }, addEventListener() {}};
      return {getTracks: () => [track], getAudioTracks: () => [track]};
    }}},
    fetch: async () => ({ok: true, json: async () => status}),
  };
  const previous = new Map();
  for (const [key, value] of Object.entries(values)) {
    previous.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, {value, configurable: true, writable: true});
  }
  t.after(() => {
    for (const [key, descriptor] of previous) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  });
  const browser = new BrowserVoice({onError: code => counts.errors.push(code)});
  t.after(() => browser.detach());
  return {browser, counts, store};
}
const available = () => ({available: true, generation_allowed: true, expert_available: true,
  code: 'manual_activation_available', brain: {sessions: []}});
const controls = socket => socket.sent.filter(x => typeof x === 'string').map(x => JSON.parse(x));

test('constructor and mode selection do not capture; explicit start still waits for backend configuration and listening', async t => {
  const {browser, counts} = browserEnvironment(t, available());
  browser.selectMode('expert');
  assert.equal(counts.microphones, 0); assert.equal(counts.sockets.length, 0);
  await browser.start('expert');
  assert.equal(counts.microphones, 1);
  assert.equal(browser.capture.enabled, false);
  const socket = counts.sockets[0]; socket.open();
  assert.equal(controls(socket)[0].type, 'hello');
  assert.equal('client_id' in controls(socket)[0], false);
  socket.event('ready', {configuration_confirmed: false, generation_allowed: true});
  assert.equal(controls(socket).filter(x => x.type === 'wake').length, 0);
  socket.event('ready', {configuration_confirmed: true, generation_allowed: true, input_mode: 'expert'});
  socket.event('ready', {configuration_confirmed: true, generation_allowed: true, input_mode: 'expert'});
  assert.equal(controls(socket).filter(x => x.type === 'wake').length, 1);
  assert.equal(browser.phase, 'connecting');
  await assert.rejects(browser.start(), /conversation_busy/);
  browser.pcm(new ArrayBuffer(4));
  assert.equal(socket.sent.some(x => x instanceof ArrayBuffer), false);
  socket.event('listening', {mode: 'expert', max_audio_seconds: 180});
  assert.equal(browser.capture.enabled, true);
  browser.pcm(new ArrayBuffer(4));
  assert.equal(socket.sent.filter(x => x instanceof ArrayBuffer).length, 1);
  browser.stop();
  browser.pcm(new ArrayBuffer(4));
  socket.event('audio_start', {response_id: 'late-after-stop'});
  socket.event('audio_chunk', {response_id: 'late-after-stop', pcm: pcm(240)});
  assert.equal(socket.sent.filter(x => x instanceof ArrayBuffer).length, 1);
  assert.equal(browser.context.sources.length, 0);
  assert.equal(counts.tracksStopped, 1);
  await assert.rejects(browser.start(), /conversation_busy/);
  socket.event('stopped', {});
  assert.equal(browser.stopPending, false);
});

test('Stop during microphone flush prevents late input_end and frees the physical track immediately', async t => {
  const {browser, counts} = browserEnvironment(t, available());
  await browser.start('expert');
  const socket = counts.sockets[0]; socket.open();
  socket.event('ready', {configuration_confirmed: true, generation_allowed: true});
  socket.event('listening', {mode: 'expert'});
  const finishing = browser.finishInput();
  assert.ok(browser.capture.finished);
  browser.stop();
  assert.equal(counts.tracksStopped, 1);
  await finishing;
  assert.equal(controls(socket).filter(x => x.type === 'input_end').length, 0);
  assert.equal(controls(socket).filter(x => x.type === 'stop').length, 1);
});

test('missing or foreign admission cannot request microphone permission or open a provider proxy', async t => {
  const {browser, counts} = browserEnvironment(t, {available: false, code: 'exact_authorized_client_required'});
  await assert.rejects(browser.start(), /exact_authorized_client_required/);
  assert.equal(counts.microphones, 0); assert.equal(counts.sockets.length, 0);
});

test('known active expert reconnects only as an empty subscriber, never a new wake', async t => {
  const ids = {session_id: 'same-session', conversation_id: 'same-conversation'};
  const state = {available: false, code: 'realtime_budget_missing_or_expired', brain: {sessions: [
    {...ids, generation_allowed: false, expert_active: true, input_mode: 'expert'}]}};
  const {browser, counts} = browserEnvironment(t, state);
  browser.session = ids;
  await browser.start();
  const socket = counts.sockets[0]; socket.open();
  socket.event('ready', {configuration_confirmed: true, generation_allowed: false, expert_active: true, input_mode: 'expert'});
  assert.equal(browser.phase, 'thinking');
  assert.equal(counts.microphones, 0);
  assert.equal(controls(socket).filter(x => x.type === 'wake').length, 0);
  browser.pcm(new ArrayBuffer(4));
  assert.equal(socket.sent.some(x => x instanceof ArrayBuffer), false);
  assert.equal(controls(socket)[0].session_id, ids.session_id);
  browser.detach();
  assert.equal(controls(socket).some(x => x.type === 'stop'), false);
});

test('known last operation resumes same logical IDs; count exhaustion never authorizes another conversation or cost-limit bypass', async t => {
  const state = available(), {browser, counts} = browserEnvironment(t, state);
  await browser.start();
  const first = counts.sockets[0]; first.open();
  first.event('ready', {configuration_confirmed: true, generation_allowed: true});
  const ids = {...browser.session};
  browser.detach();
  state.available = false; state.code = 'realtime_session_budget_exhausted';
  state.brain.sessions = [{...ids, generation_allowed: true, expert_active: false}];
  assert.equal(browser.eligibility(state).allowed, true);
  await browser.start();
  const second = counts.sockets[1]; second.open();
  assert.equal(controls(second)[0].session_id, ids.session_id);
  assert.equal(controls(second)[0].conversation_id, ids.conversation_id);
  assert.equal(eligibility(state, {...ids, conversation_id: 'different'}).allowed, false);
  state.code = 'owner_api_estimate_limit';
  assert.equal(browser.eligibility(state).allowed, false);
  state.code = 'exact_authorized_client_required'; state.brain.sessions[0].expert_active = true;
  assert.equal(browser.eligibility(state).allowed, false);
});

function worklet(rate) {
  let Constructor; const messages = [];
  const scope = {sampleRate: rate, Int16Array, Float32Array, Math,
    AudioWorkletProcessor: class {constructor() { this.port = {postMessage: m => messages.push(m)}; }},
    registerProcessor(name, klass) { assert.equal(name, 'gobot-sophia-pcm'); Constructor = klass; }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../services/phone/dist/sophia-pcm-worklet.js'), 'utf8'), scope);
  return {node: new Constructor(), messages};
}

test('worklet drops closed-gate history and sends only bounded PCM with the current generation', () => {
  const {node, messages} = worklet(48000);
  for (let i=0; i<30; i++) node.process([[new Float32Array(128).fill(.8)]]);
  assert.equal(messages.length, 0);
  node.port.onmessage({data: {type: 'gate', open: true, generation: 1}});
  for (let i=0; i<30; i++) node.process([[new Float32Array(128).fill(.4)]]);
  assert.equal(messages.length, 2);
  for (const message of messages) {
    assert.equal(message.generation, 1); assert.equal(message.pcm.byteLength, 1920);
    assert.equal(new Int16Array(message.pcm).every(x => x === 13107), true);
  }
  node.process([[new Float32Array(128).fill(.9)]]);
  node.port.onmessage({data: {type: 'gate', open: false, generation: 2}});
  node.port.onmessage({data: {type: 'gate', open: true, generation: 3}});
  node.process([[new Float32Array(128).fill(-.3)]]);
  node.port.onmessage({data: {type: 'finish', generation: 3}});
  assert.equal(messages.at(-1).end, true);
  const last = messages.at(-2); assert.equal(last.generation, 3);
  assert.equal(new Int16Array(last.pcm).every(x => x === -9830), true);
});

test('stalled main thread cannot accumulate unlimited microphone PCM or resume after overflow', () => {
  const {node, messages} = worklet(24000);
  node.port.onmessage({data: {type: 'gate', open: true, generation: 1}});
  for (let i=0; i<1000; i++) node.process([[new Float32Array(128).fill(.3)]]);
  assert.equal(messages.filter(m => m.pcm).length, 8);
  assert.equal(messages.filter(m => m.error === 'browser_capture_queue_overflow').length, 1);
  assert.equal(node.open, false); assert.equal(node.pending.length, 0);
  node.port.onmessage({data: {type: 'consumed', generation: 1, sequence: 0}});
  node.process([[new Float32Array(128).fill(.3)]]);
  node.port.onmessage({data: {type: 'finish', generation: 1}});
  assert.equal(messages.filter(m => m.pcm).length, 8);
  assert.equal(messages.some(m => m.end), false);
});

test('worklet stale, future and duplicate ACK cannot create credit in a new generation', () => {
  const {node, messages} = worklet(24000);
  node.port.onmessage({data: {type: 'gate', open: true, generation: 1}});
  for (let i=0; i<8; i++) node.process([[new Float32Array(128).fill(.4)]]);
  assert.equal(messages.filter(m => m.pcm).length, 1);
  node.port.onmessage({data: {type: 'gate', open: false, generation: 2}});
  node.port.onmessage({data: {type: 'gate', open: true, generation: 3}});
  for (let i=0; i<8; i++) node.process([[new Float32Array(128).fill(-.4)]]);
  assert.equal(node.outstanding.size, 1);
  for (const data of [
    {type: 'consumed', generation: 1, sequence: 0},
    {type: 'consumed', generation: 3, sequence: 999},
    {type: 'finish', generation: 1},
  ]) node.port.onmessage({data});
  assert.equal(node.outstanding.size, 1); assert.equal(node.open, true);
  node.port.onmessage({data: {type: 'consumed', generation: 3, sequence: 0}});
  assert.equal(node.outstanding.size, 0);
  node.port.onmessage({data: {type: 'consumed', generation: 3, sequence: 0}});
  node.port.onmessage({data: {type: 'finish', generation: 3}});
  assert.equal(messages.at(-1).end, true);
  assert.equal(messages.at(-2).generation, 3);
  assert.equal(new Int16Array(messages.at(-2).pcm).every(x => x === -13107), true);
});

test('onPCM gate change cannot ACK old audio into a fresh capture generation', async t => {
  const {browser, counts} = browserEnvironment(t, available());
  await browser.start();
  const capture = browser.capture, node = capture.node;
  capture.gate(true);
  const generation = capture.generation;
  capture.onPCM = () => capture.gate(false);
  node.port.onmessage({data: {pcm: new ArrayBuffer(4), generation, sequence: 3}});
  assert.equal(node.port.messages.some(m => m.type === 'consumed'), false);
  assert.equal(capture.generation, generation+1);
  assert.equal(counts.microphones, 1);
});

test('retired output cannot restart after Stop and is isolated from a new transport', () => {
  const {context, playback} = audio();
  playback.begin({response_id: 'old'});
  playback.append({response_id: 'old', pcm: pcm(240)});
  playback.cancel();
  assert.equal(playback.begin({response_id: 'old'}), false);
  playback.append({response_id: 'old', pcm: pcm(240)});
  assert.equal(context.sources.length, 1);
  assert.equal(playback.begin({response_id: 'fresh'}), true);
  playback.cancel('old');
  assert.equal(playback.current.id, 'fresh');
  playback.resetTransport();
  assert.equal(playback.begin({response_id: 'old'}), true); // explicit reattach may resume a surviving job.
  playback.cancel();
});

for (const rate of [44100, 48000, 96000]) test('worklet continuous resampling preserves phase at '+rate+' Hz', () => {
  const {node, messages} = worklet(rate), input = Float32Array.from({length: 5000}, (_, i) => .4*Math.sin(i/37));
  node.port.onmessage({data: {type: 'gate', open: true, generation: 7}});
  for (let offset=0; offset<input.length; offset+=37) node.process([[input.slice(offset, offset+37)]]);
  node.port.onmessage({data: {type: 'finish', generation: 7}});
  const result = messages.filter(m => m.pcm).flatMap(m => Array.from(new Int16Array(m.pcm)));
  const expected = [];
  for (let n=0; n*rate/24000+1<input.length; n++) {
    const at = n*rate/24000, index = Math.floor(at), fraction = at-index;
    expected.push(Math.round((input[index]*(1-fraction)+input[index+1]*fraction)*32767));
  }
  assert.equal(result.length, expected.length);
  assert.equal(result.every((value, i) => Math.abs(value-expected[i]) <= 1), true);
});

test('page renders physical connection and explicitly binds a browser without starting its microphone', async () => {
  const html = fs.readFileSync(path.join(__dirname, '../services/phone/dist/sophia.html'), 'utf8');
  assert.match(html, /<option value="browser">/);
  const elements = new Map();
  for (const [, name] of html.matchAll(/id="([^"]+)"/g)) elements.set(name, {
    textContent: '', dataset: {}, hidden: false, disabled: false, value: '', listeners: {},
    setAttribute(key, value) { this[key] = value; }, addEventListener(name, fn) { this.listeners[name] = fn; },
  });
  const get = id => elements.get(id); let starts = 0, binds = 0, detached = 0, instance;
  const removed = [];
  get('fast').dataset.mode = 'fast'; get('expert').dataset.mode = 'expert'; get('source').value = 'spotpear';
  class Browser {
    constructor() {
      this.mode = 'fast'; this.phase = 'disconnected'; this.connected = false; this.startRequested = false; this.stopPending = false;
      this.session = {session_id: 'expired-identity-session'}; instance = this;
    }
    state() { return {ready: false, state: this.phase, input_mode: this.mode, muted: false}; }
    eligibility(status) { return {allowed: status?.available === true, input: false, code: status?.code}; }
    async start() { starts++; }
    detach() { detached++; }
  }
  const board = {status: 'connected', device: {device_protocol_confirmed: true, cloud_ready: true, generation_allowed: false,
    wake_ui_measurement: 'lvgl_refr_ready_not_panel_dma', last_error: 'realtime_budget_or_consent_required'},
    brain: {sessions: [{ready: true, state: 'ready', generation_allowed: false, input_mode: 'fast',
      selected_expert: {provider: 'antigravity', model: 'gemini-4-argon-medium', requested_label: 'Argon Deep'}}]}};
  const browser = {binding_present: false, available: false, generation_allowed: false, code: 'browser_binding_missing'};
  const scope = {GoBotSophiaAudio: {BrowserVoice: Browser},
    document: {hidden: false, getElementById: get, querySelectorAll: () => [get('fast'), get('expert')], addEventListener() {}},
    window: {addEventListener() {}}, setInterval() {}, Date, JSON, String, Promise,
    sessionStorage: {removeItem(key) { removed.push(key); }},
    fetch: async (url, options) => {
      if (url === '/api/sophia/browser/bind') {
        assert.equal(options.method, 'POST'); assert.equal(options.body, '{}');
        binds++;
        browser.binding_present = true; browser.code = 'exact_authorized_client_required';
        return {ok: true, json: async () => ({created: true, binding_present: true, guest: true})};
      }
      return {ok: true, json: async () => url.includes('/browser/') ? browser : board};
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../services/phone/dist/sophia.js'), 'utf8'), scope);
  await new Promise(setImmediate);
  assert.equal(get('stop').disabled, false); assert.equal(get('mute').disabled, false);
  assert.equal(get('fast').disabled, false); assert.equal(get('expert').disabled, false);
  assert.equal(get('expertLabel').textContent, 'Эксперт Gemini');
  assert.equal(get('expertModel').textContent, 'Antigravity CLI · gemini-4-argon-medium');
  assert.match(get('deviceConnection').textContent, /подключена/);
  assert.match(get('sourceAdmission').textContent, /допуск закрыт/);
  assert.match(get('alert').textContent, /Нет действующего разрешения/);
  assert.equal(get('alert').textContent.includes('realtime_budget_or_consent_required'), false);
  get('source').value = 'browser'; get('source').listeners.change();
  assert.equal(get('expertLabel').textContent, 'Эксперт');
  assert.equal(get('expertModel').textContent, 'Продиктуйте задачу целиком');
  assert.equal(get('browserActions').hidden, false); assert.equal(get('browserStart').disabled, true);
  assert.match(get('description').textContent, /Подключите этот браузер/);
  assert.equal(get('browserConnect').disabled, false); assert.equal(binds, 0); assert.equal(starts, 0);
  await get('browserConnect').listeners.click();
  assert.equal(binds, 1); assert.equal(starts, 0); assert.equal(detached, 1);
  assert.equal(instance.session, null); assert.deepEqual(removed, ['gobot.sophia.browser.ids']);
  assert.equal(get('browserConnect').hidden, true); assert.equal(get('browserStart').disabled, true);
  assert.match(get('browserBinding').textContent, /подключён как гость/);
  assert.match(get('description').textContent, /Разрешение.*другому устройству/);
});
