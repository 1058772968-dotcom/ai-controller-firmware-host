import test from 'node:test';
import assert from 'node:assert/strict';
import { crc16, encodeCommand, parseFrame, buttonEdges, KEY_BITS, CMD, maskOf, WIRE_SIZE } from '../public/aikey-frames.js';
// 打包成独立项目时会没有 island-poc 参考实现：能读到就交叉核对，读不到就跳过这几项
let ref = null;
try { ref = await import('../../island-poc/protocol.js'); } catch { ref = null; }
const needRef = ref ? {} : { skip: '没有 island-poc 参考实现，跳过交叉核对' };

const key = (n) => n & 0xff;
function stateFrame({ buttons = 0, owner = 0, session = 1234, mic = false }) {
  const b = new Uint8Array(WIRE_SIZE);
  b[0] = 1; b[1] = 0x80; b[2] = owner; b[3] = buttons;
  for (let i = 0; i < 4; i += 1) b[4 + i] = (session >>> (8 * i)) & 0xff;
  b[16] = mic ? 2 : 0;
  const crc = crc16(b, 30); b[30] = crc & 0xff; b[31] = crc >> 8;
  return b;
}

test('CRC 与工程里的参考实现逐字节一致', needRef, () => {
  for (let i = 0; i < 200; i += 1) {
    const bytes = Uint8Array.from({ length: 30 }, (_, j) => (i * 31 + j * 17) & 0xff);
    assert.equal(crc16(bytes, 30), ref.crc16(bytes, 30), 'seed ' + i);
  }
});

test('命令编码与参考实现完全一致', needRef, () => {
  for (const cmd of Object.values(CMD)) {
    for (const value of [0, 1]) {
      const mine = encodeCommand(cmd, 0xdeadbeef, 7, value);
      const theirs = ref.encodeCommand(cmd, 0xdeadbeef, 7, value);
      assert.deepEqual(Array.from(mine), Array.from(theirs), 'cmd ' + cmd + ' value ' + value);
    }
  }
});

test('状态帧解析出按键、归属、会话和闸门标志', () => {
  const frame = stateFrame({ buttons: KEY_BITS.V | KEY_BITS.L, owner: 1, session: 999, mic: true });
  const r = parseFrame(frame);
  assert.equal(r.type, 0x80);
  assert.equal(r.owner, 'HOST');
  assert.equal(r.buttons, 5);
  assert.equal(r.session, 999);
  assert.equal(r.flags.micPermit, true);
});

test('坏帧不猜：长度、版本、CRC 任一不对都返回 null', () => {
  const good = stateFrame({ buttons: 4 });
  assert.equal(parseFrame(good.subarray(0, 10)), null);
  const badVersion = Uint8Array.from(good); badVersion[0] = 2;
  assert.equal(parseFrame(badVersion), null);
  const badCrc = Uint8Array.from(good); badCrc[31] ^= 0xff;
  assert.equal(parseFrame(badCrc), null);
});

test('按键边沿：按下和松开都只报一次', () => {
  assert.deepEqual(buttonEdges(0, KEY_BITS.V), [{ name: 'V', down: true }]);
  assert.deepEqual(buttonEdges(KEY_BITS.V, 0), [{ name: 'V', down: false }]);
  assert.deepEqual(buttonEdges(KEY_BITS.V, KEY_BITS.V), []);
  const both = buttonEdges(0, KEY_BITS.V | KEY_BITS.L);
  assert.equal(both.length, 2);
  assert.deepEqual(both.map((e) => e.name).sort(), ['L', 'V']);
});

test('按住 V 时又按下 L：只报 L 的边沿', () => {
  const edges = buttonEdges(KEY_BITS.V, KEY_BITS.V | KEY_BITS.L);
  assert.deepEqual(edges, [{ name: 'L', down: true }]);
});

test('按键位掩码与固件一致', () => {
  assert.deepEqual(KEY_BITS, { L: 1, R: 2, V: 4, S: 8 });
  assert.equal(maskOf(['V', 'S']), 12);
  assert.equal(maskOf(['v']), 4);
  assert.equal(maskOf(['X']), 0);
});

test('真板抓到的状态帧能解析（按键全松、指针模式）', () => {
  // 2026-11-16 用 IOKit 从 AI KEY E24 读到的帧头：02 01 80 00 00 cb 0c 39 ...
  const frame = stateFrame({ buttons: 0, owner: 0, session: 0x390ccb });
  const r = parseFrame(frame);
  assert.equal(r.owner, 'POINTER');
  assert.equal(r.buttons, 0);
  assert.equal(r.session, 0x390ccb);
});
