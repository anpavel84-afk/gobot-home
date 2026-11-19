'use strict';
(function(root) {
  const id = value => typeof value === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(value);
  const subscriberCodes = new Set(['manual_activation_available', 'realtime_session_budget_exhausted',
    'owner_realtime_daily_limit', 'owner_api_estimate_limit', 'realtime_budget_missing_or_expired']);
  function eligibility(status, ids) {
    const existing = ids && status?.brain?.sessions?.find(s =>
      s.session_id === ids.session_id && s.conversation_id === ids.conversation_id);
    const conflict = !existing && status?.brain?.sessions?.length > 0;
    const input = !conflict && (status?.available === true || (status?.code === 'realtime_session_budget_exhausted' &&
      existing?.generation_allowed === true));
    const subscriber = existing?.expert_active === true && subscriberCodes.has(status?.code);
    return {allowed: input || subscriber, input, subscriber, existing,
      code: conflict ? 'realtime_audio_session_already_active' : status?.code};
  }

  class Playback {
    constructor(context, send, {onError = () => {}, onDrained = () => {}, maxSeconds = 20} = {}) {
      this.context = context; this.send = send; this.onError = onError; this.onDrained = onDrained;
      this.maxSeconds = maxSeconds; this.current = null;
      this.retired = new Set();
    }
    begin(data) {
      if (this.retired.has(data.response_id)) return false;
      if (!id(data.response_id) || this.current) throw Error('browser_output_owner_conflict');
      this.current = {id: data.response_id, role: data.audio_role, nextTime: this.context.currentTime,
        total: 0, played: 0, nextPlayed: 0, serial: 0, chunks: new Map(), segments: new Map(),
        sealed: false, started: false, startTimer: null, progress: 0};
      return true;
    }
    retire(response) {
      if (!id(response)) return;
      this.retired.add(response);
      if (this.retired.size > 128) this.retired.delete(this.retired.values().next().value);
    }
    resetTransport() { this.cancel(); this.retired.clear(); }
    started(owner) {
      if (this.current !== owner || owner.started) return;
      owner.started = true;
      this.send({type: 'playback_started', response_id: owner.id});
    }
    append(data) {
      if (this.retired.has(data.response_id)) return;
      const owner = this.current;
      if (!owner || data.response_id !== owner.id) throw Error('browser_output_response_mismatch');
      if (owner.sealed || (data.sample_rate !== undefined && data.sample_rate !== 24000) ||
          typeof data.pcm !== 'string' || data.pcm.length > 128000) throw Error('invalid_browser_pcm24');
      const raw = atob(data.pcm);
      if (!raw.length || raw.length % 2) throw Error('invalid_browser_pcm24');
      const samples = raw.length / 2;
      if (owner.total - owner.played + samples > this.maxSeconds * 24000 || owner.chunks.size >= 256)
        throw Error('browser_output_queue_overflow');
      if (this.context.state !== 'running') throw Error('browser_audio_suspended');
      const buffer = this.context.createBuffer(1, samples, 24000), channel = buffer.getChannelData(0);
      for (let i=0; i<samples; i++) {
        let value = raw.charCodeAt(2*i) | (raw.charCodeAt(2*i+1) << 8);
        if (value & 32768) value -= 65536;
        channel[i] = value / 32768;
      }
      const source = this.context.createBufferSource(); source.buffer = buffer;
      source.connect(this.context.destination);
      const serial = owner.serial++, start = Math.max(owner.nextTime, this.context.currentTime + .015);
      owner.nextTime = start + samples/24000;
      owner.total += samples;
      const chunk = {source, end: owner.total, ended: false}; owner.chunks.set(serial, chunk);
      source.onended = () => {
        source.disconnect();
        if (this.current !== owner) return; // cancelled output is never acknowledged.
        chunk.ended = true;
        this.started(owner);
        while (owner.chunks.get(owner.nextPlayed)?.ended) {
          owner.played = owner.chunks.get(owner.nextPlayed).end;
          owner.chunks.delete(owner.nextPlayed++);
        }
        this.receipts(owner);
      };
      source.start(start);
      if (!owner.started && owner.startTimer === null) {
        const observe = () => {
          owner.startTimer = null;
          if (this.current !== owner) return;
          if (this.context.state !== 'running') { this.onError('browser_audio_suspended'); return; }
          if (this.context.currentTime >= start) this.started(owner);
          else owner.startTimer = setTimeout(observe, 10);
        };
        owner.startTimer = setTimeout(observe, Math.max(1, (start-this.context.currentTime)*1000));
      }
    }
    segment(data) {
      if (this.retired.has(data.response_id)) return;
      const owner = this.current;
      if (!owner || data.response_id !== owner.id || !id(data.segment_id) || !owner.total)
        throw Error('invalid_browser_segment_fence');
      if (owner.segments.has(data.segment_id)) return;
      if (owner.segments.size >= 256) throw Error('browser_segment_queue_overflow');
      owner.segments.set(data.segment_id, {sample: owner.total, acknowledged: false});
      this.receipts(owner);
    }
    end(data) {
      const owner = this.current;
      if (!owner || data.response_id !== owner.id) return;
      if (data.reason && data.reason !== 'finished') { this.cancel(); return; }
      owner.sealed = true;
      this.receipts(owner);
    }
    receipts(owner) {
      if (this.current !== owner) return;
      if (owner.played > owner.progress) {
        this.send({type: 'playback_progress', response_id: owner.id, played_samples: owner.played});
        owner.progress = owner.played;
      }
      for (const [segment, fence] of owner.segments) {
        if (!fence.acknowledged && owner.played >= fence.sample) {
          fence.acknowledged = true;
          this.send({type: 'playback_finished', response_id: owner.id, segment_id: segment});
        }
      }
      if (owner.sealed && owner.total && owner.played === owner.total && !owner.chunks.size) {
        this.retire(owner.id);
        clearTimeout(owner.startTimer); this.current = null;
        // WebAudio completion is client evidence; it is not acoustic measurement.
        this.send({type: 'playback_finished', response_id: owner.id});
        this.onDrained(owner.role);
      }
    }
    cancel(response = null) {
      const owner = this.current;
      this.retire(response);
      if (response && owner?.id !== response) return;
      this.current = null;
      if (!owner) return;
      this.retire(owner.id);
      clearTimeout(owner.startTimer);
      for (const {source} of owner.chunks.values()) {
        source.onended = null;
        try { source.stop(); } catch {}
        source.disconnect();
      }
      owner.chunks.clear(); owner.segments.clear();
    }
  }

  class Capture {
    constructor(context, onPCM, onError) {
      this.context = context; this.onPCM = onPCM; this.onError = onError;
      this.stream = null; this.node = null; this.enabled = false; this.generation = 0;
      this.revision = 0; this.finished = null;
    }
    async prepare() {
      if (this.stream) return;
      if (!root.isSecureContext || !navigator.mediaDevices?.getUserMedia || !this.context.audioWorklet)
        throw Error('browser_microphone_requires_https');
      const revision = ++this.revision;
      const stream = await navigator.mediaDevices.getUserMedia({audio: {
        echoCancellation: true, noiseSuppression: true, autoGainControl: true}, video: false});
      if (revision !== this.revision) { stream.getTracks().forEach(t => t.stop()); throw Error('browser_start_cancelled'); }
      try {
        await this.context.audioWorklet.addModule('/sophia/sophia-pcm-worklet.js');
        if (revision !== this.revision) throw Error('browser_start_cancelled');
        this.stream = stream;
        this.source = this.context.createMediaStreamSource(stream);
        this.node = new AudioWorkletNode(this.context, 'gobot-sophia-pcm');
        this.silent = this.context.createGain(); this.silent.gain.value = 0;
        this.source.connect(this.node); this.node.connect(this.silent).connect(this.context.destination);
        this.node.port.onmessage = ({data}) => {
          if (data.generation !== this.generation) return;
          if (data.error) { this.onError(data.error); return; }
          if (data.pcm) {
            const node = this.node, generation = this.generation;
            try { if (this.enabled) this.onPCM(data.pcm); }
            finally {
              if (this.node === node && this.generation === generation)
                node?.port.postMessage({type: 'consumed', generation, sequence: data.sequence});
            }
          }
          if (data.end && this.finished) {
            const done = this.finished; this.finished = null; this.enabled = false;
            clearTimeout(done.timer); done.resolve(true);
          }
        };
        for (const track of stream.getAudioTracks()) {
          track.addEventListener('ended', () => { if (this.stream === stream) this.onError('browser_microphone_ended'); });
          track.addEventListener('mute', () => { if (this.stream === stream) this.onError('browser_microphone_suspended'); });
        }
        this.gate(false);
      } catch (error) {
        stream.getTracks().forEach(t => t.stop()); this.close(); throw error;
      }
    }
    gate(open) {
      if (this.finished) {
        const done = this.finished; this.finished = null;
        clearTimeout(done.timer); done.resolve(false);
      }
      this.enabled = !!open && !!this.node;
      this.generation++;
      this.node?.port.postMessage({type: 'gate', open: this.enabled, generation: this.generation});
    }
    async finish() {
      if (!this.node || !this.enabled || this.finished) return false;
      return await new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          this.finished = null; this.gate(false); reject(Error('browser_microphone_flush_timeout'));
        }, 1000);
        this.finished = {timer, resolve};
        this.node.port.postMessage({type: 'finish', generation: this.generation});
      });
    }
    close() {
      ++this.revision; this.gate(false);
      const stream = this.stream; this.stream = null;
      stream?.getTracks().forEach(t => t.stop());
      this.source?.disconnect(); this.node?.disconnect(); this.silent?.disconnect();
      if (this.node) this.node.port.onmessage = null;
      this.node = null; this.source = null; this.silent = null;
    }
  }

  class BrowserVoice {
    constructor({onState = () => {}, onError = () => {}, onText = () => {}} = {}) {
      this.onState = onState; this.onError = onError; this.onText = onText;
      this.socket = null; this.context = null; this.capture = null; this.playback = null;
      this.ready = false; this.allowed = false; this.inputOpen = false; this.muted = false;
      this.phase = 'disconnected'; this.mode = 'fast'; this.startRequested = false;
      this.revision = 0; this.endpoint = null; this.heartbeat = null; this.connected = false;
      this.session = null; this.subscriberOnly = false; this.finishing = false; this.expertActive = false;
      this.suppressOutput = false;
      this.activationPending = false;
      this.stopPending = false;
    }
    state() {
      return {ready: this.ready, generation_allowed: this.allowed, input_open: this.inputOpen,
        muted: this.muted, state: this.phase, input_mode: this.mode,
        capture_connected: this.connected, local_microphone: !!this.capture?.stream,
        expert_active: this.expertActive, subscriber_only: this.subscriberOnly,
        playback_evidence: 'webaudio_ended_proxy_not_acoustic'};
    }
    changed() { this.onState(this.state()); }
    send(obj) {
      if (this.socket?.readyState !== 1) return false;
      try { this.socket.send(JSON.stringify(obj)); return true; } catch { return false; }
    }
    rememberedSession() {
      if (this.session) return this.session;
      // Only opaque IDs survive a reload, never PCM, text or profile/credentials.
      try {
        const stored = JSON.parse(sessionStorage.getItem('gobot.sophia.browser.ids') || 'null');
        if (stored && id(stored.session_id) && id(stored.conversation_id)) this.session = stored;
      } catch {}
      return this.session;
    }
    logicalSession() {
      this.rememberedSession();
      if (!this.session) this.session = {session_id: crypto.randomUUID(), conversation_id: crypto.randomUUID()};
      try { sessionStorage.setItem('gobot.sophia.browser.ids', JSON.stringify(this.session)); } catch {}
      return this.session;
    }
    eligibility(status) { return eligibility(status, this.rememberedSession()); }
    prepareAudio() {
      if (!this.context || this.context.state === 'closed') {
        const Audio = root.AudioContext || root.webkitAudioContext;
        if (!Audio) throw Error('browser_audio_unavailable');
        this.context = new Audio({sampleRate: 24000, latencyHint: 'interactive'});
        this.capture = new Capture(this.context, pcm => this.pcm(pcm), code => this.failure(code));
        this.playback = new Playback(this.context, obj => this.send(obj), {
          onError: code => this.failure(code), onDrained: role => {
            this.phase = role === 'service_cue' || this.expertActive ? 'thinking' : 'waiting'; this.changed();
          }});
      }
      // The button gesture unlocks output. It does not open the microphone.
      return this.context.resume();
    }
    async start(mode = this.mode) {
      if (this.startRequested || this.stopPending || this.activationPending || this.inputOpen || this.playback?.current ||
          ['connecting', 'thinking', 'speaking', 'waiting', 'closing_input'].includes(this.phase))
        throw Error('conversation_busy');
      const revision = ++this.revision;
      this.mode = mode; this.startRequested = true; this.phase = 'connecting'; this.changed();
      try {
        await this.prepareAudio();
        if (this.context.state !== 'running') throw Error('browser_audio_suspended');
        const response = await fetch('/api/sophia/browser/status', {cache: 'no-store'});
        const availability = await response.json(), admission = this.eligibility(availability);
        if (!response.ok || !admission.allowed) throw Error(admission.code || 'browser_admission_unavailable');
        if (mode === 'expert' && !admission.existing && !availability.expert_available)
          throw Error('browser_expert_not_authorized');
        if (revision !== this.revision) return;
        if (this.subscriberOnly && this.socket) {
          const previous = this.socket; this.socket = null; previous.close();
          clearInterval(this.heartbeat); this.connected = this.ready = false;
        }
        this.subscriberOnly = admission.subscriber;
        this.expertActive = admission.existing?.expert_active === true;
        this.allowed = admission.input;
        this.suppressOutput = false;
        if (!this.subscriberOnly) await this.capture.prepare();
        if (revision !== this.revision) { this.capture.close(); return; }
        if (this.socket?.readyState === 1 && this.ready) {
          if (this.muted) this.send({type: 'mute', muted: false});
          this.activate(); return;
        }
        const url = new URL('/api/sophia/browser/stream', location.href);
        url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.playback.resetTransport();
        const socket = new WebSocket(url); this.socket = socket;
        socket.onopen = () => {
          if (this.socket !== socket) { socket.close(); return; }
          this.connected = true;
          this.send({type: 'hello', ...this.logicalSession(), mode: this.mode, consent: true});
          this.heartbeat = setInterval(() => this.send({type: 'ping'}), 15000);
          this.changed();
        };
        socket.onmessage = ({data}) => {
          if (this.socket !== socket) return;
          try { this.event(JSON.parse(data)); } catch (error) { this.failure(error.message); }
        };
        socket.onerror = () => { if (this.socket === socket) this.onError('browser_voice_connection_lost'); };
        socket.onclose = () => {
          if (this.socket !== socket) return;
          clearInterval(this.heartbeat); this.socket = null;
          this.ready = this.connected = this.inputOpen = this.startRequested = false;
          this.activationPending = false;
          this.stopPending = false;
          this.capture?.close(); this.playback?.cancel(); this.phase = 'disconnected'; this.changed();
        };
      } catch (error) {
        if (revision !== this.revision) return;
        this.startRequested = false; this.capture?.close(); this.phase = 'blocked'; this.changed(); throw error;
      }
    }
    activate() {
      if (!this.startRequested || !this.ready || this.muted) return;
      if (this.subscriberOnly || this.expertActive) {
        this.startRequested = false; this.capture?.close(); this.phase = 'thinking'; this.changed(); return;
      }
      if (!this.allowed) {
        this.startRequested = false; this.capture?.close(); this.phase = 'blocked';
        this.onError('browser_admission_unavailable'); this.changed(); return;
      }
      this.startRequested = false;
      this.phase = 'connecting'; this.activationPending = true;
      this.send({type: 'wake', wake_id: 'browser_'+crypto.randomUUID(), mode: this.mode});
    }
    pcm(raw) {
      if (!this.inputOpen || this.muted || !this.ready || this.socket?.readyState !== 1) return;
      if (this.socket.bufferedAmount > 192000) { this.failure('browser_microphone_queue_overflow'); return; }
      const endpoint = this.endpoint;
      if (this.mode === 'expert' && endpoint) {
        const remaining = Math.max(0, endpoint.limit * 24000 - endpoint.samples);
        raw = raw.slice(0, Math.min(raw.byteLength, remaining*2));
      }
      if (raw.byteLength) this.socket.send(raw);
      if (this.mode === 'expert' && endpoint && raw.byteLength) {
        const values = new Int16Array(raw); let sum = 0;
        for (const value of values) sum += (value/32768)**2;
        const rms = Math.sqrt(sum/values.length), seconds = values.length/24000;
        endpoint.samples += values.length;
        if (rms > Math.max(.012, endpoint.noise*2.8)) { endpoint.speech = true; endpoint.quiet = 0; }
        else if (endpoint.speech) endpoint.quiet += seconds;
        else endpoint.noise = .97*endpoint.noise + .03*Math.min(rms, .01);
        if ((endpoint.speech && endpoint.quiet >= 1.4) || endpoint.samples >= endpoint.limit*24000 ||
            (!endpoint.speech && endpoint.samples >= 12*24000)) {
          this.inputOpen = false; this.capture.gate(false); this.phase = 'thinking';
          this.send({type: 'input_end'}); this.changed();
        }
      }
    }
    event(event) {
      const kind = event.type, data = event.data || {};
      if (this.suppressOutput && ['audio_start', 'audio_chunk', 'audio_segment_done', 'audio_stop'].includes(kind)) return;
      if (kind === 'ready') {
        this.ready = data.configuration_confirmed === true;
        this.allowed = data.generation_allowed === true;
        if (!this.startRequested) this.mode = data.input_mode || this.mode;
        this.muted = data.muted === true; this.expertActive = data.expert_active === true;
        this.phase = this.stopPending ? 'stopping' : this.expertActive ? 'thinking' : this.activationPending ? 'connecting' : this.ready ? 'ready' : 'connecting';
        if (this.muted && this.startRequested && !this.subscriberOnly) this.send({type: 'mute', muted: false});
        this.activate();
      } else if (kind === 'listening' || kind === 'followup') {
        this.activationPending = false;
        if (!this.capture?.stream || this.muted || this.subscriberOnly) {
          this.send({type: 'stop'}); this.phase = this.muted ? 'muted' : 'ready'; this.changed(); return;
        }
        this.mode = data.mode || 'fast'; this.inputOpen = true; this.phase = 'listening';
        this.endpoint = {samples: 0, quiet: 0, noise: .003, speech: false,
          limit: Math.min(180, Math.max(1, data.max_audio_seconds || 180))};
        this.capture.gate(true);
      } else if (['input_closed', 'followup_closed', 'transport_disconnected', 'transport_reconnecting'].includes(kind)) {
        this.inputOpen = false; this.capture?.gate(false);
        this.phase = kind === 'input_closed' ? 'thinking' : kind === 'followup_closed' ? 'ready' : 'connecting';
        if (kind.startsWith('transport_')) this.ready = false;
      } else if (kind === 'audio_start') {
        if (!this.playback.begin(data)) return;
        this.inputOpen = false; this.capture?.gate(false); this.phase = 'speaking';
      } else if (kind === 'audio_chunk') this.playback.append(data);
      else if (kind === 'audio_segment_done') this.playback.segment(data);
      else if (kind === 'audio_stop') this.playback.end(data);
      else if (kind === 'audio_cancel' || kind === 'stopped') {
        if (kind === 'audio_cancel' && data.response_id && this.playback?.current &&
            data.response_id !== this.playback.current.id) { this.playback.retire(data.response_id); return; }
        this.activationPending = false;
        this.inputOpen = false; this.capture?.gate(false); this.playback?.cancel(data.response_id);
        if (kind === 'stopped') { this.expertActive = false; this.stopPending = false; }
        this.phase = this.stopPending ? 'stopping' : this.muted ? 'muted' : this.expertActive ? 'thinking' : 'ready';
      } else if (kind === 'muted') {
        this.activationPending = false;
        this.stopPending = false;
        this.muted = data.muted === true; this.inputOpen = false; this.capture?.gate(false);
        if (this.muted) { this.capture?.close(); this.playback?.cancel(); }
        this.phase = this.muted ? 'muted' : 'ready'; this.activate();
      } else if (kind === 'mode_selected') this.mode = data.mode;
      else if (kind === 'expert_job') {
        this.expertActive = ['queued', 'running'].includes(data.job?.state);
        if (!this.playback?.current) this.phase = this.expertActive ? 'thinking' : 'ready';
        if (data.job?.error) this.onError(data.job.error);
      }
      else if (kind === 'expert_result') {
        this.expertActive = false;
        if (data.result?.display_text) this.onText(data.result.display_text, 'expert_result');
        if (!this.playback?.current) this.phase = 'ready';
      }
      else if (['input_transcript', 'stt_partial', 'stt_final'].includes(kind)) this.onText(data.text || '', kind);
      else if (kind === 'expert_text_delta') this.onText(data.text || '', kind);
      else if (kind === 'admission_denied' || kind === 'error' || kind === 'narration_unavailable') {
        this.activationPending = false;
        this.inputOpen = false; this.startRequested = false; this.capture?.close();
        if (kind !== 'narration_unavailable') this.playback?.cancel();
        this.phase = kind === 'narration_unavailable' && this.expertActive ? 'thinking' : 'blocked';
        if (data.code === 'logical_conversation_closed') {
          this.session = null;
          try { sessionStorage.removeItem('gobot.sophia.browser.ids'); } catch {}
        }
        this.onError(data.code || data.reason || kind);
      } else if (kind === 'closed') {
        this.detach();
        this.session = null;
        try { sessionStorage.removeItem('gobot.sophia.browser.ids'); } catch {}
      }
      this.changed();
    }
    async finishInput() {
      if (!this.inputOpen || this.mode !== 'expert' || this.finishing) return;
      const revision = this.revision; this.finishing = true; this.phase = 'closing_input'; this.changed();
      try {
        const finished = await this.capture.finish();
        if (!finished || revision !== this.revision || !this.inputOpen) return;
        this.inputOpen = false; this.phase = 'thinking'; this.send({type: 'input_end'}); this.changed();
      } finally { this.finishing = false; }
    }
    selectMode(mode) {
      if (!['fast', 'expert'].includes(mode) || this.inputOpen || this.playback?.current ||
          ['thinking', 'connecting', 'waiting', 'closing_input'].includes(this.phase))
        throw Error('mode_change_requires_idle');
      if (this.socket?.readyState === 1) this.send({type: 'mode', mode});
      else this.mode = mode;
      this.changed();
    }
    stop() {
      ++this.revision; this.startRequested = this.activationPending = this.inputOpen = false; this.suppressOutput = true;
      this.stopPending = this.socket?.readyState === 1;
      this.capture?.close(); this.playback?.cancel(); this.send({type: 'stop'});
      this.phase = this.stopPending ? 'stopping' : this.muted ? 'muted' : this.ready ? 'ready' : 'disconnected'; this.changed();
    }
    mute(value) {
      if (value) {
        ++this.revision; this.muted = true; this.startRequested = this.activationPending = this.inputOpen = false; this.suppressOutput = true;
        this.capture?.close(); this.playback?.cancel(); this.phase = 'muted'; this.changed();
      }
      return this.send({type: 'mute', muted: !!value});
    }
    failure(code) { this.stop(); this.phase = 'blocked'; this.onError(code || 'browser_audio_failed'); this.changed(); }
    detach() {
      ++this.revision; this.startRequested = this.activationPending = this.inputOpen = this.ready = this.connected = false;
      this.stopPending = false;
      this.suppressOutput = true;
      this.capture?.close(); this.playback?.cancel(); clearInterval(this.heartbeat);
      const socket = this.socket; this.socket = null; socket?.close();
      this.phase = 'disconnected'; this.changed();
    }
  }
  root.GoBotSophiaAudio = {Playback, Capture, BrowserVoice, eligibility};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.GoBotSophiaAudio;
})(globalThis);
