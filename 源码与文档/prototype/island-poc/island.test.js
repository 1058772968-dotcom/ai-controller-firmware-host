import test from 'node:test';
import assert from 'node:assert/strict';
import { KeyGrammar, TIMING } from './grammar.js';
import { crc16, encodeCommand, decodeReport, CMD, EVT } from './protocol.js';
import { PATTERNS, validatePattern } from './haptics.js';
import { HidLink } from './devices.js';

const run = (steps) => { const out = []; const g = new KeyGrammar((e) => e.type !== 'key' && out.push(e.type)); for (const [fn, k, t] of steps) fn === 'tick' ? g.tick(k) : g[fn](k, t); return { out, g }; };

test('S 短按呼出灵动岛，长按圈画', () => {
  assert.deepEqual(run([['press', 'S', 0], ['release', 'S', 100]]).out, ['island']);
  assert.deepEqual(run([['press', 'S', 0], ['tick', TIMING.drawHold], ['release', 'S', 600]]).out, ['drawStart', 'drawEnd']);
});
test('S 长按松开不补发短按', () => {
  assert.ok(!run([['press', 'S', 0], ['release', 'S', 400]]).out.includes('island'));
});
test('V 按下锁定，保持说话，松开结束；双击居中', () => {
  assert.deepEqual(run([['press', 'V', 0], ['release', 'V', 900]]).out, ['lock', 'voiceStart', 'voiceEnd']);
  assert.deepEqual(run([['press', 'V', 0], ['release', 'V', 80], ['press', 'V', 200], ['release', 'V', 280]]).out, ['lock', 'unlock', 'lock', 'recenter']);
  assert.ok(!run([['press', 'V', 0], ['release', 'V', 80], ['press', 'V', 500], ['release', 'V', 560]]).out.includes('recenter'));
});
test('录音与圈画互斥', () => {
  const a = run([['press', 'V', 0], ['tick', 300], ['press', 'S', 400], ['tick', 900], ['release', 'S', 950], ['release', 'V', 1000]]).out;
  assert.ok(!a.includes('drawStart') && !a.includes('island'));
  const b = run([['press', 'S', 0], ['tick', 200], ['press', 'V', 300], ['tick', 900], ['release', 'V', 950], ['release', 'S', 1000]]).out;
  assert.ok(!b.includes('voiceStart') && !b.includes('lock'));
});
test('复位结束在途动作', () => {
  const out = []; const g = new KeyGrammar((e) => out.push(e.type));
  g.press('S', 0); g.tick(300); g.reset(310);
  assert.ok(out.includes('drawCancel')); assert.equal(g.drawing, false); assert.equal(g.down.S, false);
});

test('CRC16 与固件一致（CCITT-FALSE 标准校验值）', () => {
  assert.equal(crc16(new TextEncoder().encode('123456789')), 0x29b1);
});
test('命令编码：版本、保留字节为零、CRC 低字节在前', () => {
  const b = encodeCommand(CMD.FEEDBACK, 0x11223344, 7, 1);
  assert.equal(b.length, 32); assert.equal(b[0], 1); assert.equal(b[1], 7); assert.equal(b[16], 1);
  assert.deepEqual([...b.slice(4, 8)], [0x44, 0x33, 0x22, 0x11]);
  for (const i of [2, 3, 12, 13, 14, 15, ...Array.from({ length: 13 }, (_, k) => 17 + k)]) assert.equal(b[i], 0);
  const c = crc16(b, 30); assert.equal(b[30], c & 0xff); assert.equal(b[31], c >> 8);
  assert.throws(() => encodeCommand(9, 1, 1)); assert.throws(() => encodeCommand(7, 1, 1, 2));
});
function report(type, { owner = 1, buttons = 0, session = 5, cmdSeq = 0, value = 0, dx = 0, dy = 0 } = {}) {
  const b = new Uint8Array(32); b[0] = 1; b[1] = type; b[2] = owner; b[3] = buttons; b[4] = session; b[17] = value; b[24] = cmdSeq;
  if (type === EVT.MOTION) { b[20] = dx & 0xff; b[21] = (dx >> 8) & 0xff; b[22] = dy & 0xff; b[23] = (dy >> 8) & 0xff; }
  const c = crc16(b, 30); b[30] = c & 0xff; b[31] = c >> 8; return b;
}
test('状态解码：运动有符号、CRC 错误丢弃', () => {
  const r = decodeReport(report(EVT.MOTION, { dx: -12, dy: 300 }));
  assert.equal(r.dx, -12); assert.equal(r.dy, 300); assert.equal(r.owner, 'HOST');
  const bad = report(EVT.STATUS); bad[5] ^= 1; assert.equal(decodeReport(bad), null);
});
test('HID 握手：新会话发 HELLO，ACK 后 CLAIM，HOST 后才转发按键', async () => {
  const sent = [], keys = [];
  const link = new HidLink({ onKey: (k, d) => keys.push(k + (d ? '↓' : '↑')), onMotion() {}, onState() {}, onLog() {}, transport: { sendReport: async (id, b) => sent.push([id, b[1], b[8]]) } });
  link.receive(report(EVT.STATUS, { owner: 0, buttons: 1, cmdSeq: 41 }));
  assert.deepEqual(sent[0], [2, CMD.HELLO, 42]);
  assert.deepEqual(keys, [], 'POINTER 归属时不接管 L');
  link.receive(report(EVT.ACK, { owner: 0, cmdSeq: 42, value: 0 }));
  assert.equal(sent[1][1], CMD.CLAIM);
  link.receive(report(EVT.OWNER, { owner: 1, buttons: 8, cmdSeq: 43 }));
  assert.deepEqual(keys, ['S↓']);
  link.receive(report(EVT.STATUS, { owner: 1, buttons: 0, cmdSeq: 43 }));
  assert.deepEqual(keys, ['S↓', 'S↑']);
  link.receive(report(EVT.STATUS, { owner: 1, buttons: 4, session: 6, cmdSeq: 0 }));
  assert.equal(sent.at(-1)[1], CMD.HELLO, '会话变化后重新握手');
  link.stopKeepalive(); clearTimeout(link.helloTimer);
});
test('E24 固件档：faults bit1/bit2 → 音频、触觉暂不可用，不再发送 RECORD / FEEDBACK', () => {
  const sent = [], caps = [];
  const link = new HidLink({ onKey() {}, onMotion() {}, onState() {}, onLog() {}, onCaps: (c) => caps.push(c), transport: { sendReport: async (id, b) => sent.push(b[1]) } });
  const r = report(EVT.STATUS, { owner: 1, cmdSeq: 0 }); r[19] = 6; const c = crc16(r, 30); r[30] = c & 0xff; r[31] = c >> 8;
  link.receive(r);
  assert.equal(caps.at(-1).audio, false); assert.equal(caps.at(-1).haptic, false);
  const before = sent.length; link.pulse(); link.record(true);
  assert.ok(!sent.slice(before).includes(CMD.FEEDBACK) && !sent.slice(before).includes(CMD.RECORD));
  link.stopKeepalive(); clearTimeout(link.helloTimer);
});
test('页面失焦发 RELEASE 并停止转发；回到页面重新 HELLO → CLAIM', () => {
  const sent = [], keys = [];
  const link = new HidLink({ onKey: (k, d) => keys.push(k + (d ? '↓' : '↑')), onMotion() {}, onState() {}, onLog() {}, transport: { sendReport: async (id, b) => sent.push(b[1]) } });
  link.receive(report(EVT.OWNER, { owner: 1, buttons: 4, cmdSeq: 10 }));
  assert.deepEqual(keys, ['V↓']);
  assert.equal(link.suspend(), true);
  assert.equal(sent.at(-1), CMD.RELEASE); assert.deepEqual(keys, ['V↓', 'V↑'], '失焦时松开在途按键');
  assert.equal(link.timer, null, '停止 KEEPALIVE');
  link.receive(report(EVT.STATUS, { owner: 1, buttons: 8, cmdSeq: 11 }));
  assert.deepEqual(keys, ['V↓', 'V↑'], '挂起期间不转发');
  link.receive(report(EVT.OWNER, { owner: 0, cmdSeq: 11 }));
  assert.equal(link.resume(), true); assert.equal(sent.at(-1), CMD.HELLO);
  link.receive(report(EVT.ACK, { owner: 0, cmdSeq: link.seq, value: 0 }));
  assert.equal(sent.at(-1), CMD.CLAIM);
  link.stopKeepalive(); clearTimeout(link.helloTimer);
});
test('触觉单个脉冲不超过 80ms', () => { for (const p of Object.values(PATTERNS)) assert.ok(validatePattern(p), p.name); });
