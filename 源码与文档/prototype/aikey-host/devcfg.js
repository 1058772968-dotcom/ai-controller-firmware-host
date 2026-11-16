// 配置通道（USB 报告 3）：帧、16 字节指向参数、请求队列。
// 与 engineering/e24/firmware/components/aikey_core/devcfg.c、pointer.c 逐字节对应，固件是最终裁判。
import { crc16 } from '../island-poc/protocol.js';

export const OP = { GET: 0x10, SET: 0x11, SAVE: 0x12, CAL: 0x13, TEL: 0x14, DFU: 0x15, DEFAULTS: 0x16, AUDIO: 0x17, MIC_TEST: 0x18, TONE: 0x19 };
export const OP_NAME = { 0x10: '读参数', 0x11: '写参数', 0x12: '保存', 0x13: '校准', 0x14: '遥测开关', 0x15: '进下载模式', 0x16: '恢复默认', 0x17: '读音频状态', 0x18: '麦克风自检', 0x19: '提示音' };
export const RESULT_TEXT = ['成功', '帧格式错误', 'session 不符', '参数超出范围', '保存失败（NVS）', '音频忙（录音、自检或播放中）', '音频不可用'];
export const PTR_STATE = ['未校准', '校准中', '可用'];
export const DEFAULT_CFG = { sens: 28, accel: 1.8, accelLo: 30, accelHi: 250, deadzone: 0.7, smoothLo: 4, smoothHi: 15, tau: 40, freeze: 70, invertX: false, invertY: false, gravity: true, axisSrc: [0, 1, 2], axisNeg: 0 };

const put32 = (b, o, v) => { for (let i = 0; i < 4; i++) b[o + i] = (v >>> (8 * i)) & 0xff; };
const get32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;
const seal = (b) => { const c = crc16(b, 30); b[30] = c & 0xff; b[31] = c >> 8; return b; };

export function buildFrame(op, session, tx, payload = new Uint8Array(16)) {
  const b = new Uint8Array(32);
  b[0] = 1; b[1] = op; put32(b, 4, session); put32(b, 8, tx); b.set(payload, 12);
  return seal(b);
}

export function parseReply(bytes) {
  const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (b.length !== 32 || b[0] !== 1 || !(b[1] & 0x80)) return null;
  const c = crc16(b, 30);
  if (b[30] !== (c & 0xff) || b[31] !== c >> 8) return null;
  const cfgBytes = b.slice(12, 28), op = b[1] & 0x7f, audio = op >= OP.AUDIO && op <= OP.TONE;
  return { op, code: b[2], state: b[3], session: get32(b, 4), tx: get32(b, 8), cfgBytes, cfg: audio ? null : decodeCfg(cfgBytes), audio: audio ? decodeAudio(cfgBytes) : null, telemetry: !!(b[28] & 1) };
}

// 16 字节音频状态，格式见固件 devcfg.h。
const get16s = (b, o) => { const v = b[o] | (b[o + 1] << 8); return v & 0x8000 ? v - 0x10000 : v; };
export function decodeAudio(b) {
  const f = b[0];
  return {
    clock: !!(f & 1), gate: !!(f & 2), testing: !!(f & 4), testValid: !!(f & 8), tone: !!(f & 16), amp: !!(f & 32), streaming: !!(f & 64), failed: !!(f & 128),
    leftPct: b[1], rightPct: b[2], rmsDb: get16s(b, 4) / 100, peakDb: get16s(b, 6) / 100,
    frames: get32(b, 8), rxErrors: b[12] | (b[13] << 8), uacOverflow: b[14] | (b[15] << 8),
  };
}
export function encodeTone(hz, ms, attenDb) {
  const p = new Uint8Array(16);
  p.set([0x53, 0x50, 0x4b, 0x21, hz & 0xff, hz >> 8, ms & 0xff, ms >> 8, attenDb]); // "SPK!"
  return p;
}

// 同固件 q8/q16：加 0.5 后截断到范围。
const q = (v, scale, hi) => Math.trunc(Math.min(Math.max(v * scale + 0.5, 0), hi));

export function encodeCfg(c) {
  const o = new Uint8Array(16), s = q(c.sens, 100, 65535), a = q(c.accel, 100, 65535);
  o[0] = s & 0xff; o[1] = s >> 8; o[2] = a & 0xff; o[3] = a >> 8;
  o[4] = q(c.accelLo, 1, 255); o[5] = q(c.accelHi, 0.5, 255); o[6] = q(c.deadzone, 10, 255);
  o[7] = q(c.smoothLo, 1, 255); o[8] = q(c.smoothHi, 1, 255); o[9] = q(c.tau, 1, 255);
  o[10] = Math.min(Math.trunc(c.freeze), 255);
  o[11] = (c.invertX ? 1 : 0) | (c.invertY ? 2 : 0) | (c.gravity ? 4 : 0);
  o[12] = c.axisSrc[0] | (c.axisSrc[1] << 2) | (c.axisSrc[2] << 4);
  o[13] = c.axisNeg;
  return o;
}

export function decodeCfg(b) {
  return {
    sens: (b[0] | (b[1] << 8)) / 100, accel: (b[2] | (b[3] << 8)) / 100, accelLo: b[4], accelHi: b[5] * 2,
    deadzone: b[6] / 10, smoothLo: b[7], smoothHi: b[8], tau: b[9], freeze: b[10],
    invertX: !!(b[11] & 1), invertY: !!(b[11] & 2), gravity: !!(b[11] & 4),
    axisSrc: [b[12] & 3, (b[12] >> 2) & 3, (b[12] >> 4) & 3], axisNeg: b[13],
  };
}

// 与 ak_pointer_cfg_valid 同范围。只为提前给中文提示，固件仍会再判一次。
export function cfgProblems(c) {
  const p = [];
  if (!(c.sens >= 1 && c.sens <= 200)) p.push('灵敏度需在 1–200');
  if (!(c.accel >= 1 && c.accel <= 4)) p.push('加速倍率需在 1–4');
  if (!(c.accelLo >= 0 && c.accelLo < c.accelHi && c.accelHi <= 510)) p.push('加速起点需小于满点，满点不超过 510');
  if (!(c.deadzone >= 0 && c.deadzone <= 5)) p.push('软死区需在 0–5');
  if (!(c.smoothLo >= 0 && c.smoothLo <= c.smoothHi && c.smoothHi <= 255)) p.push('平滑起点不能大于终点，终点不超过 255');
  if (!(c.tau >= 0 && c.tau <= 200)) p.push('平滑时间常数需在 0–200 ms');
  if (!(c.freeze >= 0 && c.freeze <= 255)) p.push('点击冻结需在 0–255 ms');
  if ([...c.axisSrc].sort().join() !== '0,1,2' || !(c.axisNeg >= 0 && c.axisNeg <= 7)) p.push('轴映射需是 x/y/z 的一个排列');
  return p;
}

export const axesText = (src, neg) => ['X', 'Y', 'Z'].map((n, i) => `${n}=${(neg >> i) & 1 ? '-' : '+'}${'xyz'[src[i]]}`).join(' ');

// 一次只有一帧在途：固件配置队列只有 4 深，回复也是逐条发。
export class ConfigClient {
  constructor({ send, getSession, timeoutMs = 800, onLog }) {
    Object.assign(this, { send, getSession, timeoutMs, onLog });
    this.tx = 0; this.tail = Promise.resolve(); this.waiting = null; this.live = null; this.pumping = false;
  }
  onReply(bytes) {
    const r = parseReply(bytes);
    if (!r) { this.onLog?.('配置回复 CRC 或格式错误，已丢弃', 'e'); return; }
    const w = this.waiting;
    if (w && r.op === w.op && r.tx === w.tx) { this.waiting = null; clearTimeout(w.timer); w.resolve(r); }
  }
  once(op, payload, sessionOverride) {
    const session = sessionOverride ?? this.getSession();
    if (session === null || session === undefined) return Promise.reject(new Error('还没收到设备状态，请稍等'));
    this.tx = (this.tx + 1) >>> 0;
    const tx = this.tx;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.waiting = null; reject(new Error(`${OP_NAME[op] ?? op}：${this.timeoutMs} ms 内没有回复`)); }, this.timeoutMs);
      this.waiting = { op, tx, timer, resolve };
      Promise.resolve(this.send(buildFrame(op, session, tx, payload))).then((sent) => {
        if (sent === false && this.waiting?.tx === tx) { clearTimeout(timer); this.waiting = null; reject(new Error('发送失败，请检查连接')); }
      });
    });
  }
  // USB 重连后 session 会换：用最新状态里的 session 重发一次。
  request(op, payload) {
    const run = async () => {
      const sent = this.getSession();
      let r = await this.once(op, payload);
      // 回复里带设备当前 session；状态报告最多晚 100 ms，不能等它
      if (r.code === 2) r = await this.once(op, payload, r.session !== sent ? r.session : undefined);
      if (r.code) throw new Error(`${OP_NAME[op] ?? op}失败：${RESULT_TEXT[r.code] ?? r.code}`);
      return r;
    };
    const p = this.tail.then(run, run);
    this.tail = p.catch(() => {});
    return p;
  }
  get() { return this.request(OP.GET); }
  set(c) {
    const p = cfgProblems(c);
    return p.length ? Promise.reject(new Error(p.join('；'))) : this.request(OP.SET, encodeCfg(c));
  }
  save() { return this.request(OP.SAVE); }
  calibrate() { return this.request(OP.CAL); }
  telemetry(on) { const p = new Uint8Array(16); p[0] = on ? 1 : 0; return this.request(OP.TEL, p); }
  download() { const p = new Uint8Array(16); p.set([0x44, 0x46, 0x55, 0x21]); return this.request(OP.DFU, p); } // "DFU!"
  audio() { return this.request(OP.AUDIO); }
  micTest() { return this.request(OP.MIC_TEST); }
  tone(hz, ms, attenDb) { return this.request(OP.TONE, encodeTone(hz, ms, attenDb)); }
  // 滑块拖动：只保留最新一份，发完一帧再发下一帧，不排长队。
  setLive(c, done) {
    this.live = { c, done };
    if (this.pumping) return;
    this.pumping = true;
    (async () => {
      while (this.live) {
        const { c: next, done: cb } = this.live; this.live = null;
        try { cb?.(null, await this.set(next)); } catch (err) { cb?.(err); }
      }
      this.pumping = false;
    })();
  }
}
