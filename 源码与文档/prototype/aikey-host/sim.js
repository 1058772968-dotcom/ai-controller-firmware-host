// 虚拟手柄：只用于没有实物时看界面、走流程，行为按联调预案模拟。
// 协议和参数的正确性由 host.test.js 对固件 C 代码验证，这里不算证据。
import { CMD, EVT, KEY, crc16 } from '../island-poc/protocol.js';
import { OP, DEFAULT_CFG, encodeCfg, decodeCfg, parseReply, cfgProblems } from './devcfg.js';

const put32 = (b, o, v) => { for (let i = 0; i < 4; i++) b[o + i] = (v >>> (8 * i)) & 0xff; };
const get32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;

export class SimDevice {
  // mount：设备第 i 轴 = 传感器第 p[i] 轴 × s[i]。默认故意装歪，好让向导有事可做。
  constructor({ mount = { p: [1, 2, 0], s: [1, -1, -1] }, speed = 1 } = {}) {
    this.mount = mount ?? { p: [0, 1, 2], s: [1, 1, 1] }; this.speed = speed;
    this.session = 0x5a17e24; this.owner = 0; this.buttons = 0; this.cmdSeq = 0; this.evSeq = 0; this.connected = false;
    this.cfg = { ...DEFAULT_CFG }; this.state = 2; this.calUntil = 0; this.tel = false; this.lease = 0;
    this.up = [0, 0, 1]; this.rate = [0, 0, 0]; this.rateUntil = 0; this.residual = [0, 0]; this.accum = [0, 0]; this.lastTel = 0;
    this.onReport = null; this.onLine = null; this.timers = [];
    this.rec = false; this.readyAt = 0; this.wasReady = false; this.streaming = false; this.testUntil = 0; this.testValid = false; this.testRms = -58; this.loud = false; this.toneUntil = 0; this.keysDead = '';
  }
  get micReady() { return this.rec && this.now() >= this.readyAt; }
  now() { return Math.round(performance.now()); }
  toSensor(d) { const v = [0, 0, 0]; for (let i = 0; i < 3; i++) v[this.mount.p[i]] = this.mount.s[i] * d[i]; return v; }
  estimate(g) { return [0, 1, 2].map((i) => ((this.cfg.axisNeg >> i) & 1 ? -1 : 1) * g[this.cfg.axisSrc[i]]); }
  frame(type, value = 0, extra) {
    const b = new Uint8Array(32);
    b[0] = 1; b[1] = type; b[2] = this.owner; b[3] = this.buttons; put32(b, 4, this.session); put32(b, 8, ++this.evSeq); put32(b, 12, this.now());
    b[16] = (this.owner ? 1 : 0) | (this.rec ? 2 : 0) | (this.micReady ? 4 : 0) | (this.state === 2 ? 32 : 0); b[17] = value; b[19] = 4; put32(b, 24, this.cmdSeq);
    extra?.(b);
    const c = crc16(b, 30); b[30] = c & 0xff; b[31] = c >> 8;
    return b;
  }
  status() { this.onReport?.(2, this.frame(EVT.STATUS)); }
  press(k, down) {
    if (this.keysDead.includes(k)) return;
    this.buttons = down ? this.buttons | KEY[k] : this.buttons & ~KEY[k];
    if (k === 'V' && !down) this.rec = false; // 同固件：松键不等去抖
    this.onReport?.(2, this.frame(EVT.EDGE));
  }
  leaseActive() { return this.connected && this.owner === 1; }
  sendReport(id, bytes) {
    queueMicrotask(() => (id === 2 ? this.command(bytes) : id === 3 ? this.config(bytes) : null));
  }
  command(b) {
    const cmd = b[1], seq = get32(b, 8), value = b[16];
    let r = 0;
    if (get32(b, 4) !== this.session) r = 1;
    else if (cmd !== CMD.HELLO && !this.connected) r = 3;
    else {
      this.cmdSeq = seq; this.lease = this.now();
      if (cmd === CMD.HELLO) this.connected = true;
      else if (cmd === CMD.CLAIM) { if (this.buttons & 3) r = 4; else { this.owner = 1; this.onReport?.(2, this.frame(EVT.OWNER, 1)); } }
      else if (cmd === CMD.RELEASE) { this.owner = 0; this.rec = false; this.onReport?.(2, this.frame(EVT.OWNER, 0)); }
      else if (cmd === CMD.RECORD) {
        if (!value) this.rec = false;
        else if (this.owner !== 1) r = 5;
        else if (!(this.buttons & KEY.V)) r = 4;
        else if (!this.rec) { this.rec = true; this.readyAt = this.now() + 50 / this.speed; }
      } else if (cmd === CMD.FEEDBACK && value) r = 6;
    }
    this.onReport?.(2, this.frame(EVT.ACK, r));
  }
  config(b) {
    const op = b[1]; let code = 0;
    if (get32(b, 4) !== this.session) code = 2;
    else if (op === OP.SET) {
      const next = decodeCfg(b.slice(12, 28));
      if (cfgProblems(next).length) code = 3;
      else {
        const moved = next.axisSrc.join() !== this.cfg.axisSrc.join() || next.axisNeg !== this.cfg.axisNeg;
        this.cfg = next; if (moved) this.calibrate();
      }
    } else if (op === OP.DEFAULTS) this.cfg = { ...DEFAULT_CFG };
    else if (op === OP.CAL) this.calibrate();
    else if (op === OP.TEL) { this.tel = b[12] === 1; this.onLine?.(`I (${this.now()}) e24: 遥测 ${this.tel ? '开' : '关'}`); }
    else if (op === OP.MIC_TEST || op === OP.TONE) code = this.audioOp(op, b);
    const o = new Uint8Array(32);
    o[0] = 1; o[1] = op | 0x80; o[2] = code; o[3] = this.state; put32(o, 4, this.session); o.set(b.slice(8, 12), 8); o.set(op >= OP.AUDIO && op <= OP.TONE ? this.audioStatus() : encodeCfg(this.cfg), 12); o[28] = this.tel ? 1 : 0;
    const c = crc16(o, 30); o[30] = c & 0xff; o[31] = c >> 8;
    this.onReport?.(3, o);
    if (parseReply(o) === null) throw new Error('sim 回复自检失败');
  }
  audioOp(op, b) {
    const t = this.now();
    if (this.rec || t < this.testUntil || t < this.toneUntil) return 5;
    if (op === OP.MIC_TEST) { this.testRms = this.loud ? -32 : -58; this.loud = false; this.testValid = false; this.testUntil = t + 1100 / this.speed; return 0; }
    this.toneUntil = t + (b[18] | (b[19] << 8)) / this.speed;
    return 0;
  }
  audioStatus() {
    const t = this.now(), testing = t < this.testUntil, tone = t < this.toneUntil;
    if (!testing && this.testUntil) this.testValid = true;
    const o = new Uint8Array(16), rms = this.testRms, c = (v) => Math.round(v * 100) & 0xffff;
    o[0] = (testing || tone || this.rec ? 1 : 0) | (this.micReady ? 2 : 0) | (testing ? 4 : 0) | (this.testValid ? 8 : 0) | (tone ? 16 : 0) | (tone ? 32 : 0) | (this.streaming ? 64 : 0);
    if (this.testValid) { o[1] = 99; o[4] = c(rms) & 0xff; o[5] = c(rms) >> 8; o[6] = c(rms + 14) & 0xff; o[7] = c(rms + 14) >> 8; put32(o, 8, 32000); }
    return o;
  }
  clap() { this.loud = true; } // 下一次自检当作有人拍手
  // 替代浏览器取流：闸门关时全零，开时给一段信号。
  capture() {
    const cap = { onBlock: null, close: async () => { clearInterval(timer); this.streaming = false; } };
    this.streaming = true;
    let ph = 0;
    const timer = setInterval(() => {
      const b = new Float32Array(800);
      if (this.micReady) for (let i = 0; i < b.length; i++) b[i] = 0.1 * Math.sin((ph += 0.3));
      cap.onBlock?.(b);
    }, 50 / this.speed);
    return cap;
  }
  calibrate() { this.state = 1; this.calUntil = this.now() + 1200 / this.speed; }
  // 向导每一步对应的手上动作
  act(id) {
    const hold = 2000 / this.speed;
    if (id === 'flat' || id === 'rest') { this.up = [0, 0, 1]; this.rate = [0, 0, 0]; }
    if (id === 'noseUp') { this.up = [0, 1, 0]; this.rate = [0, 0, 0]; }
    if (id === 'right') { this.up = [0, 0, 1]; this.spin([0, 0, -30 * this.speed], hold / 2); }
    if (id === 'up') { this.up = [0, 0, 1]; this.spin([30 * this.speed, 0, 0], hold / 2); }
  }
  spin(rate, ms) { this.rate = rate; this.rateUntil = this.now() + ms; }
  // 把屏幕上的拖动当作手腕转动：右拖 = 向右转，下拖 = 向下压。
  drag(dx, dy) { this.spin([-dy * 6, 0, -dx * 6], 60); }
  tick() {
    const t = this.now(), dt = 0.01;
    if (this.state === 1 && t >= this.calUntil) { this.state = 2; this.onLine?.(`I (${t}) e24: 陀螺仪已校准`); }
    if (this.rateUntil && t >= this.rateUntil) { this.rate = [0, 0, 0]; this.rateUntil = 0; }
    if (this.owner === 1 && t - this.lease > 750) { this.owner = 0; this.connected = false; this.rec = false; this.onReport?.(2, this.frame(EVT.OWNER, 0)); }
    if (this.micReady !== this.wasReady) { this.wasReady = this.micReady; this.onReport?.(2, this.frame(EVT.MIC, this.wasReady ? 2 : 0)); }
    const g = this.toSensor(this.rate).map((v, i) => v + [0.4, -0.3, 0.2][i] + (Math.random() - 0.5) * 0.3);
    const a = this.toSensor(this.up).map((v) => v + (Math.random() - 0.5) * 0.01);
    const w = this.estimate(this.toSensor(this.rate));
    const active = this.state === 2, h = active ? -w[2] : 0, vv = active ? -w[0] : 0;
    const dead = Math.hypot(h, vv) < this.cfg.deadzone;
    const k = dead ? 0 : this.cfg.sens * dt;
    this.residual[0] += h * k * (this.cfg.invertX ? -1 : 1); this.residual[1] += vv * k * (this.cfg.invertY ? -1 : 1);
    const dx = Math.trunc(this.residual[0]), dy = Math.trunc(this.residual[1]);
    this.residual[0] -= dx; this.residual[1] -= dy;
    if ((dx || dy) && this.owner === 1) this.onReport?.(2, this.frame(EVT.MOTION, 0, (b) => { b[20] = dx & 0xff; b[21] = (dx >> 8) & 0xff; b[22] = dy & 0xff; b[23] = (dy >> 8) & 0xff; }));
    if (this.tel) {
      const f = (v) => v.map((x) => x.toFixed(2)).join(','), fa = (v) => v.map((x) => x.toFixed(3)).join(',');
      this.onLine?.(`{"v":1,"type":"imu","t":${Math.round(this.simT = (this.simT ?? 0) + 10)},"dt":0.0050,"g":[${f(g)}],"a":[${fa(a)}],"h":${h.toFixed(2)},"vv":${vv.toFixed(2)},"dx":${dx},"dy":${dy},"bias":[0.40,-0.30,0.20],"cal":${this.state},"still":${this.rate.some(Boolean) ? 0 : 1}}`);
    }
  }
  start() {
    this.timers = [setInterval(() => this.status(), 100), setInterval(() => this.tick(), 10 / this.speed)];
  }
  stop() { this.timers.forEach(clearInterval); this.timers = []; }
}
