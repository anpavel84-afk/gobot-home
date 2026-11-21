'use strict';
// One continuous converter per active input. Closed gates discard all history.
class SophiaPCM extends AudioWorkletProcessor {
  constructor() {
    super();
    this.open = false;
    this.generation = 0;
    this.tail = [];
    this.position = 0;
    this.pending = [];
    this.outstanding = new Set(); this.sequence = 0; this.failed = false;
    this.port.onmessage = ({data}) => {
      if (data.type === 'gate') {
        this.open = data.open === true;
        this.generation = data.generation;
        this.tail = []; this.pending = []; this.position = 0;
        this.outstanding.clear(); this.sequence = 0; this.failed = false;
      } else if (data.type === 'consumed' && data.generation === this.generation) {
        this.outstanding.delete(data.sequence);
      } else if (data.type === 'finish' && data.generation === this.generation) {
        this.open = false;
        if (!this.flush()) return;
        this.tail = []; this.position = 0;
        this.port.postMessage({end: true, generation: this.generation});
      }
    };
  }
  flush() {
    if (!this.pending.length) return !this.failed;
    if (this.outstanding.size >= 8) {
      this.open = false; this.tail = []; this.pending = []; this.position = 0;
      if (!this.failed) this.port.postMessage({error: 'browser_capture_queue_overflow', generation: this.generation});
      this.failed = true;
      return false;
    }
    const pcm = new Int16Array(this.pending);
    this.pending = [];
    const sequence = this.sequence++; this.outstanding.add(sequence);
    this.port.postMessage({pcm: pcm.buffer, generation: this.generation, sequence}, [pcm.buffer]);
    return true;
  }
  process(inputs) {
    if (!this.open) return true;
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    const input = this.tail.concat(Array.from(channel));
    const step = sampleRate / 24000;
    while (this.position + 1 < input.length) {
      const index = Math.floor(this.position), fraction = this.position - index;
      const value = Math.max(-1, Math.min(1, input[index] * (1-fraction) + input[index+1] * fraction));
      this.pending.push(Math.round(value * 32767));
      this.position += step;
      if (this.pending.length === 960 && !this.flush()) return true; // 40 ms, bounded transfer.
    }
    const consumed = Math.min(input.length, Math.floor(this.position));
    this.tail = input.slice(consumed); this.position -= consumed;
    return true;
  }
}
registerProcessor('gobot-sophia-pcm', SophiaPCM);
