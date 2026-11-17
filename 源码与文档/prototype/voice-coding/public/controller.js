// 手柄连接：默认只「听」。设备每 100 ms 发一帧报告 2（含四键状态），打开设备就能收到，
// 不需要 HELLO/CLAIM，所以接管按键时鼠标照常可用。
// 只有固件要求「按住 V 才放行麦克风」时才需要 claim()：HELLO → CLAIM，之后每 200 ms KEEPALIVE。
import { encodeCommand, parseFrame, buttonEdges, CMD, RESULT, EVT } from './aikey-frames.js';

export const AIKEY_FILTER = { vendorId: 0xcafe, productId: 0x4031, usagePage: 0xff00, usage: 1 };
const ACK_TIMEOUT_MS = 900;
const KEEPALIVE_MS = 200;

export class ControllerSession {
  constructor({ onKey, onState, onStatus, onLog, hid, timers } = {}) {
    Object.assign(this, { onKey, onState, onStatus, onLog, hid, timers });
    this.device = null;
    this.owner = 'POINTER';
    this.session = 0;
    this.buttons = 0;
    this.seq = 0;
    this.claimed = false;
    this.pending = new Map();
    this.keepalive = null;
  }

  static supported(hid = globalThis.navigator?.hid) {
    return !!hid;
  }

  async connect({ device } = {}) {
    const hid = this.hid ?? globalThis.navigator?.hid;
    if (!hid) throw new Error('这个浏览器没有 WebHID，用桌面版 Chrome / Edge 打开');
    let dev = device;
    if (!dev) {
      const picked = await hid.requestDevice({ filters: [AIKEY_FILTER] });
      dev = picked && picked[0];
    }
    if (!dev) throw new Error('没有选择设备');
    if (!dev.opened) await dev.open();
    this.device = dev;
    this.onInput = (e) => this.handleReport(e.reportId ?? e.reportId === 0 ? e.reportId : 2, new Uint8Array(e.data.buffer, e.data.byteOffset, e.data.byteLength));
    this.onDisconnect = (e) => { if (e.device === dev) this.lost('设备已断开'); };
    dev.addEventListener('inputreport', this.onInput);
    hid.addEventListener?.('disconnect', this.onDisconnect);
    this.onState?.({ phase: 'listening', text: `已连接 ${dev.productName || 'AI KEY'}：按键可用，鼠标不受影响` });
    return dev;
  }

  handleReport(reportId, bytes) {
    if (reportId !== 2) return;
    if (!this.loggedFrame) {
      this.loggedFrame = true;
      const hex = Array.from(bytes).slice(0, 12).map((b) => b.toString(16).padStart(2, '0')).join(' ');
      this.onLog?.('首帧 len=' + bytes.length + ' [' + hex + ']');
    }
    const frame = parseFrame(bytes);
    if (!frame) return; // 坏帧不猜
    this.session = frame.session || this.session;
    if (frame.type === EVT.ACK) return this.settleAck(frame);
    if (frame.type === EVT.OWNER) {
      this.owner = frame.owner;
      this.claimed = frame.owner === 'HOST';
      this.onState?.({ phase: this.claimed ? 'host' : 'pointer', text: this.claimed ? '已接管：四键归语音' : '交还指针：手柄恢复鼠标' });
      return;
    }
    this.onStatus?.(frame);
    // 按键状态每帧都带（不区分归属），所以只听也能拿到 V/L/R/S 的按下与松开
    const edges = buttonEdges(this.buttons, frame.buttons);
    this.buttons = frame.buttons;
    for (const { name, down } of edges) this.onKey?.(name, down);
  }

  settleAck(frame) {
    this.ackCount = (this.ackCount || 0) + 1;
    const result = RESULT[frame.value] ?? 'UNKNOWN';
    const waiter = this.pending.get(frame.commandSequence);
    if (waiter) {
      this.pending.delete(frame.commandSequence);
      waiter(result);
    }
    this.onLog?.(this.commandLabel?.(frame.commandSequence) + ' 回执 ' + result);
  }

  commandLabel(seq) {
    const name = this.commandNames?.get(seq);
    return name || ('seq ' + seq);
  }

  async send(command, value = 0) {
    if (!this.device) throw new Error('手柄还没连上');
    this.seq = (this.seq + 1) >>> 0;
    const bytes = encodeCommand(command, this.session, this.seq, value);
    this.commandNames = this.commandNames || new Map();
    this.commandNames.set(this.seq, Object.keys(CMD).find((k) => CMD[k] === command) || String(command));
    // 序号要在闭包里定住：KEEPALIVE 每 200 ms 一条，读 this.seq 会串到别的命令上
    const seq = this.seq;
    const ack = new Promise((resolve) => {
      this.pending.set(seq, resolve);
      setTimeout(() => {
        if (this.pending.delete(seq)) resolve('TIMEOUT');
      }, ACK_TIMEOUT_MS);
    });
    await this.device.sendReport(2, bytes);
    return ack;
  }

  // 只有需要固件开麦克风闸门时才用：HELLO → CLAIM
  async claim() {
    if (!this.device) throw new Error('手柄还没连上');
    if (this.claimed) return true;
    // 会话号从状态帧里来；一帧都还没收到就发命令，固件会按 BAD_SESSION 静默丢掉
    await this.waitForSession(2000);
    this.onLog?.('claim 开始：session=' + this.session + ' seq=' + this.seq);
    // 刚打开设备后的第一包有可能丢（实测过），给三次机会
    let hello = 'TIMEOUT';
    for (let attempt = 0; attempt < 4 && hello !== 'OK'; attempt += 1) {
      if (attempt) {
        await new Promise((r) => setTimeout(r, 400));
        if (!this.session) await this.waitForSession(800); // 会话可能刚被租约过期顶掉
      }
      hello = await this.send(CMD.HELLO);
      this.onLog?.('HELLO 结果：' + hello + '（seq ' + this.seq + '）');
    }
    if (hello !== 'OK') throw new Error('HELLO 没有回 OK（' + hello + '）');
    const claim = await this.send(CMD.CLAIM);
    if (claim !== 'OK') throw new Error('CLAIM 没有回 OK（' + claim + '）' + (claim === 'HELD' ? '：先松开 L/R 再试' : ''));
    this.claimed = true;
    this.owner = 'HOST';
    this.keepalive = (this.timers?.setInterval ?? setInterval)(() => { this.send(CMD.KEEPALIVE).catch(() => {}); }, KEEPALIVE_MS);
    this.onState?.({ phase: 'host', text: '已接管：四键归语音，手柄暂时当不了鼠标' });
    return true;
  }

  async release() {
    if (this.keepalive) {
      (this.timers?.clearInterval ?? clearInterval)(this.keepalive);
      this.keepalive = null;
    }
    if (!this.device || !this.claimed) return false;
    this.claimed = false;
    this.owner = 'POINTER';
    await this.send(CMD.RELEASE).catch(() => {});
    this.onState?.({ phase: 'pointer', text: '交还指针：手柄恢复鼠标' });
    return true;
  }

  async record(on) {
    if (!this.device) return false;
    if (!this.claimed) return false; // 没接管时固件不理 RECORD
    let ack = await this.send(CMD.RECORD, on ? 1 : 0);
    if (on && ack === 'HELD') {
      // 按键事件比固件采样晚一拍时会被回 HELD，等一下再要一次
      await new Promise((r) => setTimeout(r, 80));
      ack = await this.send(CMD.RECORD, 1);
    }
    if (ack !== 'OK') this.onLog?.('RECORD=' + (on ? 1 : 0) + ' 回执 ' + ack);
    return ack === 'OK';
  }

  async waitForSession(timeoutMs = 2000) {
    const deadline = Date.now() + timeoutMs;
    while (!this.session && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 50));
    }
    return this.session;
  }

  // 诊断用：不同主机的写通道对「报告号怎么带」处理不一样，逐个试一遍谁有回执
  async probeWrites() {
    const results = [];
    const variants = [
      { name: 'id=2 + 32 字节', id: 2, bytes: () => encodeCommand(CMD.HELLO, this.session, ++this.seq) },
      { name: 'id=2 + [02]+32 字节', id: 2, bytes: () => new Uint8Array([2, ...encodeCommand(CMD.HELLO, this.session, ++this.seq)]) },
      { name: 'id=0 + 32 字节', id: 0, bytes: () => encodeCommand(CMD.HELLO, this.session, ++this.seq) },
    ];
    for (const v of variants) {
      const before = this.ackCount || 0;
      const bytes = v.bytes();
      try {
        await this.device.sendReport(v.id, bytes);
      } catch (err) {
        results.push(v.name + ' → 发送报错：' + err.message);
        continue;
      }
      await new Promise((r) => setTimeout(r, 700));
      const got = (this.ackCount || 0) > before;
      results.push(v.name + ' → ' + (got ? '收到回执 ✓' : '没有回执'));
      if (got) break;
    }
    return results;
  }

  lost(text) {
    this.keepalive && (this.timers?.clearInterval ?? clearInterval)(this.keepalive);
    this.keepalive = null;
    this.claimed = false;
    this.owner = 'POINTER';
    this.device?.removeEventListener?.('inputreport', this.onInput);
    this.device = null;
    this.onState?.({ phase: 'lost', text });
  }

  async close() {
    if (!this.device) return;
    const dev = this.device;
    await this.release().catch(() => {});
    dev.removeEventListener?.('inputreport', this.onInput);
    try { await dev.close(); } catch { /* 拔掉了 */ }
    this.device = null;
  }
}
