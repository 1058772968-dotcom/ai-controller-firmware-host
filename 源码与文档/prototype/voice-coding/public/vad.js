// 纯逻辑的说话切分：输入一块块浮点采样，输出「一段话起始/结束」和电平。
// 不碰 DOM、不碰音频设备，所以能在 Node 里直接测。
// 手柄按住 V 只是把麦克风闸门打开，声音什么时候出现由这里判断。

const rms = (samples) => {
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
  return Math.sqrt(sum / Math.max(1, samples.length));
};

export class VadSegmenter {
  constructor({
    sampleRate = 16000,
    threshold = 0.012,
    startHoldMs = 120,
    hangoverMs = 650,
    preRollMs = 320,
    maxUtteranceMs = 60000,
  } = {}) {
    this.sampleRate = sampleRate;
    this.threshold = threshold;
    this.startHoldMs = startHoldMs;
    this.hangoverMs = hangoverMs;
    this.preRollMs = preRollMs;
    this.maxUtteranceMs = maxUtteranceMs;
    this.reset();
  }

  reset() {
    this.active = false;
    this.level = 0;
    this.blocks = [];
    this.samples = 0;
    this.preroll = [];
    this.prerollSamples = 0;
    this.lastVoiceAt = 0;
    this.startedAt = 0;
    this.voiceMs = 0;
    this.peak = 0;
  }

  get state() { return this.active ? 'active' : 'idle'; }

  _pushPreroll(block) {
    this.preroll.push(block);
    this.prerollSamples += block.length;
    const cap = Math.round((this.preRollMs / 1000) * this.sampleRate);
    while (this.prerollSamples > cap && this.preroll.length > 1) {
      this.prerollSamples -= this.preroll.shift().length;
    }
  }

  _begin(nowMs) {
    this.active = true;
    this.blocks = [...this.preroll];
    this.samples = this.prerollSamples;
    this.preroll = [];
    this.prerollSamples = 0;
    this.startedAt = nowMs;
    this.lastVoiceAt = nowMs;
    this.voiceMs = 0;
    this.peak = 0;
  }

  _end() {
    const total = this.blocks.reduce((n, b) => n + b.length, 0);
    const samples = new Float32Array(total);
    let offset = 0;
    for (const b of this.blocks) { samples.set(b, offset); offset += b.length; }
    const durationMs = Math.round((total / this.sampleRate) * 1000);
    const utterance = { samples, durationMs, peak: this.peak };
    this.reset();
    return utterance;
  }

  // 返回 { level, started, utterance }：started 只在开头那一块为 true；
  // utterance 只在结束那一块给出，别的块是 null。
  push(block, nowMs = Date.now()) {
    const samples = block instanceof Float32Array ? block : Float32Array.from(block);
    const level = rms(samples);
    this.level = level;
    const speech = level >= this.threshold;
    let started = false;
    let utterance = null;

    if (!this.active) {
      this._pushPreroll(samples);
      if (speech) {
        this.voiceMs += (samples.length / this.sampleRate) * 1000;
        if (this.voiceMs >= this.startHoldMs) { this._begin(nowMs); started = true; }
      } else {
        this.voiceMs = 0;
      }
      return { level, started, utterance };
    }

    this.blocks.push(samples);
    this.samples += samples.length;
    if (level > this.peak) this.peak = level;
    if (speech) this.lastVoiceAt = nowMs;
    const elapsed = (this.samples / this.sampleRate) * 1000;
    if (nowMs - this.lastVoiceAt >= this.hangoverMs || elapsed >= this.maxUtteranceMs) {
      utterance = this._end();
    }
    return { level, started, utterance };
  }

  // 手动结束（松开按键、停止监听时调用）
  flush() {
    if (!this.active) { this.reset(); return null; }
    return this._end();
  }
}

// 一段 Float32 采样转成 16 bit 小端 PCM
export function floatToPcm16(samples) {
  const out = new Uint8Array(samples.length * 2);
  const view = new DataView(out.buffer);
  for (let i = 0; i < samples.length; i += 1) {
    const v = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(i * 2, Math.round(v < 0 ? v * 0x8000 : v * 0x7fff), true);
  }
  return out;
}
