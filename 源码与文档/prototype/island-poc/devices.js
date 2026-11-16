// 输入通道：AI KEY 实物（WebHID，REV A 协议）与电脑语音识别。键鼠模拟在 main.js 中直接喂给语义层。
import { CMD, EVT, KEY, encodeCommand, decodeReport } from './protocol.js';

export const AIKEY_FILTER = { vendorId: 0xcafe, productId: 0x4031, usagePage: 0xff00, usage: 0x0001 };
const NAMES = Object.fromEntries(Object.entries(CMD).map(([k, v]) => [v, k]));

// 只在主机取得 HOST 归属后接管按键与运动；POINTER 归属时 L/R 仍是系统鼠标，不重复注入。
export class HidLink {
  // autoClaim=false：只读状态、走报告 3 调参，不发 HELLO/CLAIM，系统光标保持可用；需要接管时调 takeHost()。
  constructor({ onKey, onMotion, onState, onLog, onCaps, onConfig, onStatus, transport, autoClaim = true }) {
    Object.assign(this, { onKey, onMotion, onState, onLog, onCaps, onConfig, onStatus });
    this.wantHost = autoClaim;
    this.transport = transport ?? null; // 测试注入：{ sendReport(id, bytes) }
    this.session = null; this.seq = 0; this.owner = 'POINTER'; this.buttons = 0;
    this.pending = new Map(); this.timer = null; this.helloTries = 0;
  }
  static supported() { return typeof navigator !== 'undefined' && 'hid' in navigator; }
  async connect(existing) {
    if (!HidLink.supported()) throw new Error('当前浏览器不支持 WebHID，请用桌面版 Chrome / Edge 打开');
    const dev = existing ?? (await navigator.hid.requestDevice({ filters: [AIKEY_FILTER] }))[0];
    if (!dev) throw new Error('未选择设备');
    if (!dev.opened) await dev.open();
    this.device = dev;
    this.transport = { sendReport: (id, bytes) => dev.sendReport(id, bytes) };
    this.onInput = (e) => {
      const bytes = new Uint8Array(e.data.buffer, e.data.byteOffset, e.data.byteLength);
      if (e.reportId === 2) this.receive(bytes);
      else if (e.reportId === 3) this.onConfig?.(bytes);
    };
    dev.addEventListener('inputreport', this.onInput);
    this.onDisconnect = (e) => { if (e.device === dev) this.lost('设备已断开'); };
    navigator.hid.addEventListener('disconnect', this.onDisconnect);
    this.onState({ phase: 'waiting', text: `已打开 ${dev.productName || 'AI KEY'}，等待设备状态报告…` });
  }
  async send(command, value = 0) {
    if (!this.transport || this.session === null) return false;
    this.seq = (this.seq + 1) >>> 0;
    const bytes = encodeCommand(command, this.session, this.seq, value);
    this.pending.set(this.seq, { command, value, at: Date.now() });
    this.onLog?.(`${NAMES[command]}${command >= 5 ? '=' + value : ''} · seq ${this.seq}`, 'h');
    try { await this.transport.sendReport(2, bytes); return true; }
    catch (err) { this.onLog?.(`发送失败：${err.message}`, 'e'); return false; }
  }
  async sendConfig(bytes) {
    if (!this.transport) return false;
    try { await this.transport.sendReport(3, bytes); return true; }
    catch (err) { this.onLog?.(`发送失败：${err.message}`, 'e'); return false; }
  }
  receive(bytes) {
    const r = decodeReport(bytes);
    if (!r) { this.onLog?.('丢弃：CRC / 版本不符', 'e'); return; }
    if (this.session !== r.session) {
      // 新会话：旧序号、旧按键全部作废，按住的键必须先松开。
      if (this.buttons) this.emitButtons(0);
      this.session = r.session; this.seq = r.commandSequence; this.owner = 'POINTER'; this.pending.clear();
      this.helloTries = 0; if (this.wantHost && !this.suspended) this.hello();
    }
    // hardware_faults bit1 = 音频故障、bit2 = 触觉（联调档未实现）：显示“暂不可用”，不发对应命令、不重试。
    const caps = { audio: !(r.faults & 2), haptic: !(r.faults & 4), calibrated: r.flags.calibrated };
    if (!this.caps || caps.audio !== this.caps.audio || caps.haptic !== this.caps.haptic || caps.calibrated !== this.caps.calibrated) { this.caps = caps; this.onCaps?.(caps); }
    if (r.type === EVT.ACK) this.ack(r);
    if (this.waitRelease && r.type === EVT.STATUS && !(r.buttons & (KEY.L | KEY.R))) { this.waitRelease = false; if (this.wantHost && !this.suspended) { this.helloTries = 0; this.hello(); } }
    if (r.type === EVT.OWNER || r.owner !== this.owner) {
      this.owner = r.owner;
      if (r.owner !== 'HOST' && this.buttons) this.emitButtons(0); // 租约到期等被动交还：按住的键不能悬着
      this.onState({ phase: r.owner === 'HOST' ? 'host' : 'pointer', text: r.owner === 'HOST' ? '已取得输入归属：四键与陀螺仪由灵动岛接管' : '设备为普通鼠标模式' });
      if (r.owner === 'HOST' && !this.suspended) this.startKeepalive(); else this.stopKeepalive();
    }
    if (r.owner === 'HOST' && !this.suspended) {
      this.emitButtons(r.buttons);
      if (r.type === EVT.MOTION && (r.dx || r.dy)) this.onMotion(r.dx, r.dy);
    }
    if (r.type === EVT.RESET_INPUT) this.onLog?.('设备复位在途输入', 'e');
    this.onStatus?.(r);
  }
  emitButtons(mask) {
    const changed = mask ^ this.buttons; this.buttons = mask;
    for (const [name, bit] of Object.entries(KEY)) if (changed & bit) this.onKey(name, !!(mask & bit));
  }
  ack(r) {
    const p = this.pending.get(r.commandSequence); this.pending.delete(r.commandSequence);
    if (!p) return;
    this.onLog?.(`ACK ${NAMES[p.command]} → ${r.result}`, r.result === 'OK' ? 'p' : 'e');
    if (p.command === CMD.HELLO && r.result === 'OK' && this.wantHost && !this.suspended) this.send(CMD.CLAIM);
    if (p.command === CMD.CLAIM && r.result === 'HELD') { clearTimeout(this.helloTimer); this.waitRelease = true; this.onState({ phase: 'pointer', text: '请先松开 L / R，松开后自动接管' }); }
    if (r.result === 'INVALID' && (p.command === CMD.FEEDBACK || p.command === CMD.RECORD)) {
      this.caps = { ...this.caps, [p.command === CMD.FEEDBACK ? 'haptic' : 'audio']: false }; this.onCaps?.(this.caps);
    }
  }
  hello() {
    if (this.helloTries++ >= 3) { this.onState({ phase: 'error', text: '设备未应答 HELLO，请重新插拔后再连接' }); return; }
    this.send(CMD.HELLO);
    clearTimeout(this.helloTimer);
    this.helloTimer = setTimeout(() => { if (this.owner !== 'HOST' && this.wantHost && !this.suspended) this.hello(); }, 600);
  }
  startKeepalive() { this.stopKeepalive(); this.timer = setInterval(() => this.send(CMD.KEEPALIVE), 200); }
  stopKeepalive() { clearInterval(this.timer); this.timer = null; }
  // 页面失焦或隐藏：HOST 期间固件不发系统鼠标报告，主动 RELEASE 把光标交还系统，不等 750ms 租约超时。
  suspend() {
    this.suspended = true; clearTimeout(this.helloTimer);
    if (this.owner !== 'HOST') return false;
    this.stopKeepalive(); if (this.buttons) this.emitButtons(0);
    this.send(CMD.RELEASE); return true;
  }
  // 回到页面：重新 HELLO → CLAIM（L/R 仍按住时设备会回 HELD）。
  resume() {
    if (!this.suspended) return false;
    this.suspended = false;
    if (this.session === null || this.owner === 'HOST' || !this.wantHost) return false;
    this.helloTries = 0; this.hello(); return true;
  }
  // 主动接管 / 交还（autoClaim=false 时由界面调用）。
  takeHost() {
    this.wantHost = true;
    if (this.session === null || this.owner === 'HOST') return false;
    this.helloTries = 0; this.hello(); return true;
  }
  releaseHost() {
    this.wantHost = false; clearTimeout(this.helloTimer);
    if (this.owner !== 'HOST') return false;
    this.stopKeepalive(); if (this.buttons) this.emitButtons(0);
    this.send(CMD.RELEASE); return true;
  }
  draw(on) { return this.owner === 'HOST' && this.send(CMD.DRAW, on ? 1 : 0); }
  record(on) { return this.owner === 'HOST' && this.caps?.audio !== false && this.send(CMD.RECORD, on ? 1 : 0); }
  pulse() { return this.owner === 'HOST' && this.caps?.haptic !== false && this.send(CMD.FEEDBACK, 1); } // 固件 80ms 后自动停止
  recenter() { return this.owner === 'HOST' && this.send(CMD.RECENTER); }
  async close() {
    this.stopKeepalive(); clearTimeout(this.helloTimer);
    if (this.owner === 'HOST') await this.send(CMD.RELEASE);
    if (this.onDisconnect) navigator.hid.removeEventListener('disconnect', this.onDisconnect);
    this.device?.removeEventListener('inputreport', this.onInput);
    try { await this.device?.close(); } catch {}
    this.device = null; this.transport = null; this.session = null; this.owner = 'POINTER';
  }
  lost(text) {
    this.stopKeepalive(); clearTimeout(this.helloTimer); if (this.buttons) this.emitButtons(0);
    this.device?.removeEventListener('inputreport', this.onInput);
    this.session = null; this.owner = 'POINTER'; this.device = null; this.transport = null;
    this.onState({ phase: 'lost', text });
  }
}

// 浏览器语音识别（Chrome 走在线服务）。不可用或失败时由场景使用示例话术。
export class Voice {
  constructor() {
    const SR = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition);
    this.SR = SR || null; this.rec = null; this.text = ''; this.onPartial = null;
  }
  get available() { return !!this.SR; }
  start() {
    if (!this.SR) return false;
    this.text = ''; this.final = '';
    const rec = new this.SR(); rec.lang = 'zh-CN'; rec.interimResults = true; rec.continuous = true;
    rec.onresult = (e) => {
      let fin = '', mid = '';
      for (const r of e.results) (r.isFinal ? (fin += r[0].transcript) : (mid += r[0].transcript));
      this.text = fin + mid; this.onPartial?.(this.text);
    };
    rec.onerror = () => {};
    this.done = new Promise((res) => { rec.onend = () => res(this.text.trim()); });
    try { rec.start(); this.rec = rec; return true; } catch { return false; }
  }
  async stop() {
    if (!this.rec) return '';
    this.rec.stop(); this.rec = null;
    return Promise.race([this.done, new Promise((r) => setTimeout(() => r(this.text.trim()), 1500))]);
  }
}
