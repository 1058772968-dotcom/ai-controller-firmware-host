// 麦克风取流。手柄的 USB 麦克风在系统里叫 Held-key microphone（POC 档叫 AI KEY Mic POC）。
// 语音处理全关：降噪和自动增益会把「手柄闸门关着时到底是不是全零」搞乱，也会吃掉轻声。
import { VadSegmenter, floatToPcm16 } from './vad.js';
import { isBoardMic, DEFAULT_BOARD_MIC_NAMES } from './mic-match.js';

export const CONTROLLER_MICS = DEFAULT_BOARD_MIC_NAMES;

// 默认不弹权限框：页面一打开就开麦克风会吓人，也容易卡在权限确认上。
// 需要设备名（或要真录音）时再传 requestPermission: true。
export async function listMics({ requestPermission = false } = {}) {
  let list = await navigator.mediaDevices.enumerateDevices();
  const unnamed = !list.some((d) => d.kind === 'audioinput' && d.label);
  if (unnamed && requestPermission) {
    const s = await navigator.mediaDevices.getUserMedia({ audio: true });
    s.getTracks().forEach((t) => t.stop());
    list = await navigator.mediaDevices.enumerateDevices();
  }
  return list.filter((d) => d.kind === 'audioinput');
}

export function isControllerMic(label) {
  return isBoardMic(label, CONTROLLER_MICS);
}

// 取错设备时抛这个：宁可不录，也不悄悄录电脑麦克风
export class BoardMicError extends Error {
  constructor(message, code) {
    super(message);
    this.name = 'BoardMicError';
    this.code = code;
  }
}

export class Recorder {
  constructor({ onLevel, onUtterance, onState, threshold = 0.012 } = {}) {
    Object.assign(this, { onLevel, onUtterance, onState });
    this.threshold = threshold;
    this.ctx = null;
    this.stream = null;
    this.vad = null;
    this.mode = 'ptt';
    this.blocks = [];
    this.frames = 0;
    this.sampleRate = 16000;
  }

  get running() { return !!this.ctx; }

  // expectedNames 非空 = 只接受板载麦克风；取到的设备名对不上就关掉并报错，不退回别的麦
  async start({ deviceId, mode = 'ptt', expectedNames = [] } = {}) {
    if (this.running) return;
    const audio = {
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
      channelCount: 1,
    };
    if (deviceId) audio.deviceId = { exact: deviceId };
    this.stream = await navigator.mediaDevices.getUserMedia({ audio });
    const label = this.stream.getAudioTracks()[0]?.label || '';
    if (expectedNames.length && !isBoardMic(label, expectedNames)) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
      throw new BoardMicError(
        '取到的不是板载麦克风（拿到的是「' + (label || '未命名设备') + '」），已放弃这次录音',
        'BOARD_MIC_MISMATCH',
      );
    }
    this.ctx = new AudioContext({ sampleRate: 16000 });
    // resume() 在没有用户手势 / 无音频输出设备的页面里可能一直不返回：别把界面卡在「正在开麦」
    await Promise.race([this.ctx.resume().catch(() => {}), new Promise((r) => setTimeout(r, 1500))]);
    if (this.ctx.state !== 'running') {
      const state = this.ctx.state;
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
      const ctx = this.ctx;
      this.ctx = null;
      await ctx.close().catch(() => {});
      throw new Error('音频没启动（' + state + '）：在页面上点一下再按说话');
    }
    this.sampleRate = this.ctx.sampleRate;
    this.mode = mode;
    this.blocks = [];
    this.frames = 0;
    this.vad = new VadSegmenter({ sampleRate: this.sampleRate, threshold: this.threshold });
    const src = this.ctx.createMediaStreamSource(this.stream);
    const proc = this.ctx.createScriptProcessor(1024, 1, 1);
    const sink = this.ctx.createGain();
    sink.gain.value = 0; // 不外放，免得啸叫
    this.proc = proc;
    this.src = src;
    this.sink = sink;
    proc.onaudioprocess = (e) => {
      const block = new Float32Array(e.inputBuffer.getChannelData(0));
      if (this.mode === 'auto') {
        const r = this.vad.push(block, performance.now());
        this.onLevel?.(r.level);
        if (r.utterance) this.emit(r.utterance.samples, r.utterance.durationMs);
        return;
      }
      this.blocks.push(block);
      const r = this.vad.push(block, performance.now());
      void r;
      let sum = 0;
      for (let i = 0; i < block.length; i += 1) sum += block[i] * block[i];
      this.onLevel?.(Math.sqrt(sum / block.length));
    };
    src.connect(proc);
    proc.connect(sink);
    sink.connect(this.ctx.destination);
    return { label, sampleRate: this.sampleRate };
  }

  // 统一出口：给上层的一定是带 pcm 的对象（stop() 的返回值也用它，别再自己拼一个）
  emit(samples, durationMs) {
    const utterance = { pcm: floatToPcm16(samples), sampleRate: this.sampleRate, durationMs };
    this.onUtterance?.(utterance);
    return utterance;
  }

  // 松开按键：把这一段切出来，交给上层去识别
  async stop() {
    if (!this.running) return null;
    let utterance = this.vad ? this.vad.flush() : null;
    if (this.mode === 'ptt') {
      const total = this.blocks.reduce((n, b) => n + b.length, 0);
      if (total > 0) {
        const samples = new Float32Array(total);
        let off = 0;
        for (const b of this.blocks) { samples.set(b, off); off += b.length; }
        utterance = { samples, durationMs: Math.round((total / this.sampleRate) * 1000) };
      }
    }
    await this.teardown();
    return utterance ? this.emit(utterance.samples, utterance.durationMs) : null;
  }

  async cancel() {
    await this.teardown();
    this.blocks = [];
  }

  async teardown() {
    if (!this.ctx) return;
    try { this.proc.onaudioprocess = null; } catch { /* 已经断开了 */ }
    try { this.src.disconnect(); } catch { /* 同上 */ }
    try { this.proc.disconnect(); } catch { /* 同上 */ }
    try { this.sink.disconnect(); } catch { /* 同上 */ }
    this.stream?.getTracks().forEach((t) => t.stop());
    const ctx = this.ctx;
    this.ctx = null;
    this.stream = null;
    this.proc = null;
    this.src = null;
    this.sink = null;
    await ctx.close().catch(() => {});
    this.onLevel?.(0);
  }
}
