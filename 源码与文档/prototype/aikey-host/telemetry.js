// CDC 遥测（Web Serial）。日志和遥测混在同一个口，高频时可能在行中间交错，所以逐行容错解析。
// 设备发来的文字只显示，绝不当命令执行。
export const CDC_BAUD = 115200; // 绝不能用 1200：固件把 1200 bps 当作“重启进下载模式”
export const CDC_FILTER = { usbVendorId: 0xcafe, usbProductId: 0x4031 };
const MAX_LINE = 2048;
const nums = (v) => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite);

export function parseLine(raw) {
  const line = raw.replace(/\r$/, '').replace(/\x1b\[[0-9;]*m/g, ''); // ESP_LOG 的颜色码
  if (!line) return { kind: 'empty' };
  if (line[0] !== '{') return { kind: 'log', text: line };
  let d;
  try { d = JSON.parse(line); } catch { return { kind: 'drop' }; }
  if (d?.v !== 1 || d.type !== 'imu' || !nums(d.g) || !nums(d.a) || !Number.isFinite(d.t) || !Number.isFinite(d.h) || !Number.isFinite(d.vv)) return { kind: 'drop' };
  return { kind: 'imu', data: d };
}

export class LineSplitter {
  constructor(onLine) { this.onLine = onLine; this.buf = ''; }
  push(text) {
    this.buf += text;
    let i;
    while ((i = this.buf.indexOf('\n')) >= 0) { this.onLine(this.buf.slice(0, i)); this.buf = this.buf.slice(i + 1); }
    if (this.buf.length > MAX_LINE) this.buf = '';
  }
}

export class Telemetry {
  constructor({ onSample, onLog, onState }) {
    Object.assign(this, { onSample, onLog, onState });
    this.dropped = 0; this.collectors = new Set(); this.port = null; this.reader = null;
    this.splitter = new LineSplitter((l) => this.line(l));
  }
  static supported() { return typeof navigator !== 'undefined' && 'serial' in navigator; }
  line(raw) {
    const p = parseLine(raw);
    if (p.kind === 'imu') { this.onSample?.(p.data); for (const c of this.collectors) c.push(p.data); }
    else if (p.kind === 'log') this.onLog?.(p.text);
    else if (p.kind === 'drop') this.dropped++;
  }
  // 收集一段时间的样本（向导用）。
  async collect(ms) {
    const out = [];
    this.collectors.add(out);
    await new Promise((r) => setTimeout(r, ms));
    this.collectors.delete(out);
    return out;
  }
  async connect(existing) {
    if (!Telemetry.supported()) throw new Error('当前浏览器不支持 Web Serial，请用桌面版 Chrome 或 Edge');
    const port = existing ?? await navigator.serial.requestPort({ filters: [CDC_FILTER] });
    try { await port.open({ baudRate: CDC_BAUD }); }
    catch (err) { throw new Error(`串口打不开：可能被 screen 或 e24ctl 占用，关掉后再试（${err.message}）`); }
    await port.setSignals({ dataTerminalReady: true }); // 固件只在 DTR 打开时才写遥测
    this.port = port; this.onState?.(true);
    this.loop(port);
  }
  async loop(port) {
    const dec = new TextDecoder();
    try {
      // 读取出错但可恢复时 port.readable 会换一条新流；流正常结束就不再重开，否则会空转。
      let ended = false;
      while (!ended && port.readable && this.port === port) {
        this.reader = port.readable.getReader();
        try {
          for (;;) {
            const { value, done } = await this.reader.read();
            if (done) { ended = true; break; }
            this.splitter.push(dec.decode(value, { stream: true }));
          }
        } finally { this.reader.releaseLock(); this.reader = null; }
      }
    } catch (err) { this.onLog?.(`串口读取中断：${err.message}`); }
    if (this.port === port) { this.port = null; this.onState?.(false); try { await port.close(); } catch {} }
  }
  async close() {
    const port = this.port; this.port = null;
    try { await this.reader?.cancel(); } catch {}
    try { await port?.close(); } catch {}
    this.onState?.(false);
  }
}
