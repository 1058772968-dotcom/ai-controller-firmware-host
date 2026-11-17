import test from 'node:test';
import assert from 'node:assert/strict';
import { ControllerSession, AIKEY_FILTER } from '../public/controller.js';
import { encodeCommand, crc16, CMD, KEY_BITS, WIRE_SIZE } from '../public/aikey-frames.js';

// 假设备：能收 inputreport 事件，记录发出去的报文，并能按需回 ACK
function fakeHid() {
  const listeners = new Map();
  const sent = [];
  const dev = {
    opened: false,
    productName: 'AI KEY E24',
    async open() { dev.opened = true; },
    async close() { dev.opened = false; },
    addEventListener(type, fn) { listeners.set(type, fn); },
    removeEventListener(type) { listeners.delete(type); },
    async sendReport(id, bytes) { sent.push({ id, bytes: Array.from(bytes) }); },
    emit(frame) {
      const data = new DataView(frame.buffer, frame.byteOffset, frame.byteLength);
      listeners.get('inputreport')?.({ reportId: 2, data });
    },
    emitAck(requestSeq, result) {
      const b = new Uint8Array(WIRE_SIZE);
      b[0] = 1; b[1] = 8; b[17] = result;
      b[24] = requestSeq & 0xff; b[25] = (requestSeq >> 8) & 0xff;
      const crc = crc16(b, 30); b[30] = crc & 0xff; b[31] = crc >> 8;
      dev.emit(b);
    },
  };
  const hid = {
    requestDevice: async () => [dev],
    addEventListener() {},
    removeEventListener() {},
  };
  return { hid, dev, sent };
}

function frameWith({ buttons = 0, owner = 0, session = 77, mic = false }) {
  const b = new Uint8Array(WIRE_SIZE);
  b[0] = 1; b[1] = 0x80; b[2] = owner; b[3] = buttons;
  for (let i = 0; i < 4; i += 1) b[4 + i] = (session >>> (8 * i)) & 0xff;
  b[16] = mic ? 2 : 0;
  const crc = crc16(b, 30); b[30] = crc & 0xff; b[31] = crc >> 8;
  return b;
}

async function connected() {
  const { hid, dev, sent } = fakeHid();
  const keys = [];
  const states = [];
  const s = new ControllerSession({ hid, onKey: (n, d) => keys.push(n + (d ? '+' : '-')), onState: (s) => states.push(s.phase) });
  await s.connect();
  dev.emit(frameWith({ buttons: 0 }));
  return { s, dev, sent, keys, states };
}

test('连接后只听：不发 HELLO/CLAIM，按键边沿照常上报', async () => {
  const { s, dev, sent, keys, states } = await connected();
  assert.equal(sent.length, 0, '只监听时不该发任何命令');
  dev.emit(frameWith({ buttons: KEY_BITS.V }));
  dev.emit(frameWith({ buttons: KEY_BITS.V }));
  dev.emit(frameWith({ buttons: 0 }));
  assert.deepEqual(keys, ['V+', 'V-']);
  assert.ok(states.includes('listening'));
});

test('坏帧不下发按键（CRC 不对就当没收到）', async () => {
  const { dev, keys } = await connected();
  const bad = frameWith({ buttons: KEY_BITS.V });
  bad[31] ^= 0xff;
  dev.emit(bad);
  assert.deepEqual(keys, []);
});

test('接管：HELLO 回 OK 才发 CLAIM，拿到 HOST 后开 KEEPALIVE', async () => {
  const { s, dev, sent, states } = await connected();
  const claiming = s.claim();
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(sent[0].bytes[1], CMD.HELLO);
  dev.emitAck(1, 0); // HELLO → OK
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(sent[1].bytes[1], CMD.CLAIM);
  dev.emitAck(2, 0); // CLAIM → OK
  assert.equal(await claiming, true);
  assert.equal(s.claimed, true);
  const before = sent.length;
  await new Promise((r) => setTimeout(r, 260));
  const keepalives = sent.slice(before).filter((m) => m.bytes[1] === CMD.KEEPALIVE);
  assert.ok(keepalives.length >= 1, '应该已经发过 KEEPALIVE');
  assert.ok(states.includes('host'));
  await s.close();
});

test('CLAIM 回 HELD 时说清楚要先松开 L/R', async () => {
  const { s, dev } = await connected();
  const claiming = s.claim();
  await new Promise((r) => setTimeout(r, 20));
  dev.emitAck(1, 0);
  await new Promise((r) => setTimeout(r, 20));
  dev.emitAck(2, 4); // HELD
  await assert.rejects(() => claiming, /先松开 L\/R/);
  assert.equal(s.claimed, false);
});

test('没接管时 RECORD 不发（固件会回 NOT_CONNECTED）', async () => {
  const { s, sent } = await connected();
  assert.equal(await s.record(true), false);
  assert.equal(sent.filter((m) => m.bytes[1] === CMD.RECORD).length, 0);
});

test('接管后 RECORD 带 value，回 OK 才算成功', async () => {
  const { s, dev, sent } = await connected();
  const claiming = s.claim();
  await new Promise((r) => setTimeout(r, 20));
  dev.emitAck(1, 0);
  await new Promise((r) => setTimeout(r, 20));
  dev.emitAck(2, 0);
  await claiming;
  const rec = s.record(true);
  await new Promise((r) => setTimeout(r, 20));
  const cmd = sent.filter((m) => m.bytes[1] === CMD.RECORD).pop();
  assert.equal(cmd.bytes[16], 1);
  dev.emitAck(3, 0);
  assert.equal(await rec, true);
  await s.close();
});

test('设备断开后状态归零，不再发命令', async () => {
  const { s, dev, states } = await connected();
  s.lost('设备已断开');
  assert.equal(s.claimed, false);
  assert.equal(s.device, null);
  assert.ok(states.includes('lost'));
  await assert.rejects(() => s.send(CMD.HELLO), /还没连上/);
  void dev;
});

test('过滤器指向 AI KEY 的 VID/PID', () => {
  assert.deepEqual(AIKEY_FILTER, { vendorId: 0xcafe, productId: 0x4031, usagePage: 0xff00, usage: 1 });
});
