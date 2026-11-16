// 全链路模拟：真实固件 C（经 sim_rt）⇄ 真实上位机 JS，同一条虚拟时钟，1 tick = 1 ms。
// 浏览器部分（WebHID、Web Serial、定时器）是替身，语义写在注释里；替身通过不等于实物通过。
import { execFileSync, spawn } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
export const FW_ROOT = resolve(process.env.SIM_FIRMWARE ?? join(HERE, '../../firmware'));
export const PROTO_ROOT = resolve(process.env.SIM_PROTOTYPE ?? join(HERE, '../../../../prototype'));
const real = { setTimeout, clearTimeout, setInterval, clearInterval, setImmediate, now: Date.now, perf: performance.now.bind(performance) };

export function buildDevice(out) {
  const c = join(FW_ROOT, 'components');
  execFileSync('cc', ['-std=gnu11', '-O1', '-g', '-DCONFIG_E24_IMU_ODR_HZ=200', `-I${join(HERE, 'stubs')}`, `-I${join(FW_ROOT, 'main')}`,
    `-I${join(c, 'aikey_core/include')}`, `-I${join(c, 'bsp_e24/include')}`, `-I${join(c, 'imu_bmi270/include')}`,
    join(HERE, 'sim_rt.c'), join(HERE, 'glue_link.c'), join(FW_ROOT, 'main/usb_link.c'), join(FW_ROOT, 'main/ptr_store.c'),
    ...['controller', 'protocol', 'devcfg', 'pointer'].map((n) => join(c, `aikey_core/${n}.c`)), '-lm', '-lpthread', '-o', out], { stdio: 'inherit' });
  return out;
}
export const load = (rel) => import(pathToFileURL(join(PROTO_ROOT, rel)).href);

class Clock {
  constructor() { this.t = 1_000_000; this.seq = 1; this.q = new Map(); }
  add(fn, ms, every) { const id = this.seq++; this.q.set(id, { fn, at: this.t + Math.max(ms || 0, 1), every }); return id; }
  install() {
    globalThis.setTimeout = (fn, ms, ...a) => this.add(() => fn(...a), ms);
    globalThis.setInterval = (fn, ms, ...a) => this.add(() => fn(...a), ms, Math.max(ms, 1));
    globalThis.clearTimeout = globalThis.clearInterval = (id) => this.q.delete(id);
    Date.now = () => this.t;
    performance.now = () => this.t;
  }
  uninstall() { Object.assign(globalThis, { setTimeout: real.setTimeout, clearTimeout: real.clearTimeout, setInterval: real.setInterval, clearInterval: real.clearInterval }); Date.now = real.now; performance.now = real.perf; }
  advance() {
    this.t++;
    for (const [id, x] of [...this.q]) {
      if (x.at > this.t || !this.q.has(id)) continue;
      if (x.every) x.at += x.every; else this.q.delete(id);
      x.fn();
    }
  }
}

// Chromium 的 HID 服务按 guid 缓存 HIDDevice：同一设备 requestDevice/getDevices 反复返回同一对象，close 后监听器还在。
// 报告 1 在鼠标集合里，属于受保护集合，页面收不到（联调预案第 6 节）。
class FakeHIDDevice extends EventTarget {
  constructor(b) { super(); this.b = b; this.opened = false; this.productName = 'AI KEY E24'; this.vendorId = 0xcafe; this.productId = 0x4031; }
  async open() { this.opened = true; }
  async close() { this.opened = false; }
  async sendReport(id, data) {
    if (!this.opened) throw new Error('device closed');
    const u = data instanceof Uint8Array ? data : new Uint8Array(data);
    this.b.counts[`out${id}:${u[1]}`] = (this.b.counts[`out${id}:${u[1]}`] ?? 0) + 1;
    this.b.outLog.push({ t: this.b.ms, id, cmd: u[1] });
    this.b.cmd(`o ${id} ${Buffer.from(u).toString('hex')}`);
  }
}

// Web Serial 替身：open 时拉高 DTR（macOS 打开 tty 的默认行为），字节流走真实 ReadableStream。
class FakePort {
  constructor(b) { this.b = b; this.readable = null; }
  getInfo() { return { usbVendorId: 0xcafe, usbProductId: 0x4031 }; }
  async open({ baudRate }) {
    this.b.cmd(`b ${baudRate}`); this.b.cmd('d 1');
    this.readable = new ReadableStream({ start: (c) => { this.b.serial = c; } });
  }
  async setSignals({ dataTerminalReady }) { this.b.cmd(`d ${dataTerminalReady ? 1 : 0}`); }
  async close() { this.b.cmd('d 0'); try { this.b.serial?.close(); } catch {} this.b.serial = null; this.readable = null; }
}

export class Bench {
  constructor(bin, { mount = { p: [0, 1, 2], s: [1, 1, 1] }, seed = 1 } = {}) {
    this.bin = bin; this.mount = mount; this.seed = seed; this.clock = new Clock(); this.tx = ''; this.buf = ''; this.waitK = null; this.logs = [];
    this.ms = 0; this.counts = {}; this.outLog = []; this.up = [0, 0, 1]; this.rate = [0, 0, 0]; this.dirty = true;
    this.mouse = { x: 0, y: 0, b: 0, edges: [], reports: 0 }; this.status = []; this.sessions = []; this.restart = null; this.serial = null; this.desc = {}; this.cdc = '';
    this.hidDevice = new FakeHIDDevice(this); this.port = new FakePort(this); this.plugged = true;
  }
  async start() {
    this.clock.install();
    const hidEvents = new EventTarget();
    hidEvents.requestDevice = async () => [this.hidDevice];
    hidEvents.getDevices = async () => [this.hidDevice];
    this.hidEvents = hidEvents;
    Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { hid: hidEvents, serial: { requestPort: async () => this.port, getPorts: async () => [this.port] } } });
    this.p = spawn(this.bin, [], { stdio: ['pipe', 'pipe', 'inherit'] });
    this.p.stdout.setEncoding('utf8');
    this.p.stdout.on('data', (d) => this.onData(d));
    this.cmd(`f seed ${this.seed}`);
  }
  async stop() { this.p.stdin.write('x\n'); this.p.stdin.end(); await new Promise((r) => this.p.once('close', r)); this.clock.uninstall(); }
  cmd(s) { this.tx += s + '\n'; }
  onData(d) {
    this.buf += d;
    let i;
    while ((i = this.buf.indexOf('\n')) >= 0) { const l = this.buf.slice(0, i); this.buf = this.buf.slice(i + 1); this.line(l); }
  }
  line(l) {
    const k = l[0];
    if (k === 'K') { const w = this.waitK; this.waitK = null; w?.(); }
    else if (k === 'I') this.onIn(l);
    else if (k === 'C') { const b = Buffer.from(l.slice(2), 'hex'); this.cdc += b.toString('utf8'); this.counts.cdcBytes = (this.counts.cdcBytes ?? 0) + b.length; try { this.serial?.enqueue(new Uint8Array(b)); } catch {} }
    else if (k === 'L') this.logs.push(l.slice(2));
    else if (k === 'R') this.state = JSON.parse(l.slice(2));
    else if (k === 'P') { const [, n, h] = l.split(' '); this.desc[n] = Buffer.from(h, 'hex'); }
    else if (k === 'X') { this.restart = l; this.hidDevice.opened && this.unplug(); }
  }
  onIn(l) {
    const [, t, id, hex] = l.split(' '); const b = Buffer.from(hex, 'hex');
    if (id === '1') {
      const m = this.mouse; m.reports++;
      m.x += b.readInt8(1); m.y += b.readInt8(2);
      if (b[0] !== m.b) { m.edges.push({ t: this.ms, from: m.b, to: b[0] }); m.b = b[0]; }
      return;
    }
    if (id === '2') {
      const s = b.readUInt32LE(4);
      if (this.sessions.at(-1)?.s !== s) this.sessions.push({ t: this.ms, s });
      if (b[1] === 0x80) this.status.push({ t: this.ms, s, owner: b[2], buttons: b[3], flags: b[16], faults: b[19] });
      this.counts[`in2:${b[1]}`] = (this.counts[`in2:${b[1]}`] ?? 0) + 1;
    }
    if (!this.hidDevice.opened) return;
    const e = new Event('inputreport'); e.reportId = +id; e.device = this.hidDevice; e.data = new DataView(b.buffer, b.byteOffset, b.length);
    this.hidDevice.dispatchEvent(e);
  }
  // 手上的动作：up = 设备坐标里的“上”，rate = 设备轴角速度 °/s
  move(rate) { this.rate = rate; this.dirty = true; }
  pose(up) { this.up = up; this.rate = [0, 0, 0]; this.dirty = true; }
  physics() {
    const [wx, wy, wz] = this.rate.map((v) => v * Math.PI / 180 * 0.001), u = this.up;
    if (wx || wy || wz) {
      const n = [u[0] - (wy * u[2] - wz * u[1]), u[1] - (wz * u[0] - wx * u[2]), u[2] - (wx * u[1] - wy * u[0])], h = Math.hypot(...n);
      this.up = n.map((v) => v / h); this.dirty = true;
    }
    if (!this.dirty) return;
    this.dirty = false;
    const g = [0, 0, 0], a = [0, 0, 0];
    for (let i = 0; i < 3; i++) { g[this.mount.p[i]] = this.mount.s[i] * this.rate[i]; a[this.mount.p[i]] = this.mount.s[i] * this.up[i]; }
    this.cmd(`g ${g.join(' ')} ${a.join(' ')}`);
  }
  async tick(n = 1) {
    for (let i = 0; i < n; i++) {
      this.ms++; this.clock.advance();
      await new Promise((r) => real.setImmediate(r));
      this.physics();
      await this.exchange('t 1');
      await new Promise((r) => real.setImmediate(r));
    }
  }
  exchange(c) { return new Promise((r) => { this.waitK = r; this.p.stdin.write(this.tx + c + '\n'); this.tx = ''; }); }
  async read() { await this.exchange('r'); return this.state; }
  async descriptors() { await this.exchange('p'); return this.desc; }
  async wait(promise, maxMs = 5000) {
    let done = false, val, err;
    promise.then((v) => { done = true; val = v; }, (e) => { done = true; err = e; });
    for (let i = 0; i < maxMs && !done; i++) await this.tick();
    if (!done) throw new Error(`等待超时 ${maxMs} ms`);
    if (err) throw err;
    return val;
  }
  async until(fn, maxMs = 5000) { for (let i = 0; i < maxMs; i++) { if (await fn()) return i; await this.tick(); } return -1; }
  // 上电 → 400 ms 枚举 → 放在桌上到校准完成
  async boot() { await this.tick(400); this.cmd('m 1'); await this.tick(2700); }
  unplug() { this.cmd('m 0'); const e = new Event('disconnect'); e.device = this.hidDevice; this.hidEvents.dispatchEvent(e); }
  key(mask) { this.cmd(`k ${mask}`); }
}
