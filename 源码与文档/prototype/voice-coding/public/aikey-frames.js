// AI KEY v1 线协议的最小子集：32 字节帧、CRC16-CCITT、按键位。
// 与 engineering/e24/firmware/components/aikey_core/protocol.c 一致；
// tests/aikey-frames.test.mjs 里会拿 island-poc/protocol.js 做交叉核对。
export const WIRE_SIZE = 32;
export const KEY_BITS = { L: 1, R: 2, V: 4, S: 8 };
export const EVT = { EDGE: 1, OWNER: 2, MIC: 3, DRAW: 4, HAPTIC: 5, RESET: 6, CENTER: 7, ACK: 8, FAULT: 9, STATUS: 0x80, MOTION: 0x81 };
export const CMD = { HELLO: 1, CLAIM: 2, KEEPALIVE: 3, RELEASE: 4, RECORD: 5 };
export const RESULT = ['OK', 'BAD_SESSION', 'STALE', 'NOT_CONNECTED', 'HELD', 'CONFLICT', 'INVALID'];

export function crc16(bytes, n = bytes.length) {
  let crc = 0xffff;
  for (let i = 0; i < n; i += 1) {
    crc ^= bytes[i] << 8;
    for (let bit = 0; bit < 8; bit += 1) crc = crc & 0x8000 ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
  }
  return crc;
}

const u32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;
const put32 = (b, o, v) => { for (let i = 0; i < 4; i += 1) b[o + i] = (v >>> (8 * i)) & 0xff; };

export function encodeCommand(command, session, sequence, value = 0) {
  const bytes = new Uint8Array(WIRE_SIZE);
  bytes[0] = 1;
  bytes[1] = command;
  put32(bytes, 4, session);
  put32(bytes, 8, sequence);
  bytes[16] = value;
  const crc = crc16(bytes, 30);
  bytes[30] = crc & 0xff;
  bytes[31] = crc >> 8;
  return bytes;
}

// 设备 → 主机。返回 null 表示不是可用的状态帧（版本/长度/CRC 不对），不猜内容。
export function parseFrame(input) {
  const b = input instanceof Uint8Array ? input : new Uint8Array(input);
  if (b.length < WIRE_SIZE || b[0] !== 1) return null;
  const crc = crc16(b, 30);
  if (b[30] !== (crc & 0xff) || b[31] !== crc >> 8) return null;
  const flags = b[16];
  return {
    type: b[1],
    owner: b[2] ? 'HOST' : 'POINTER',
    buttons: b[3],
    session: u32(b, 4),
    sequence: u32(b, 8),
    value: b[17],
    hidButtons: b[18],
    faults: b[19],
    commandSequence: u32(b, 24),
    flags: {
      micPermit: !!(flags & 2),
      micReady: !!(flags & 4),
      calibrated: !!(flags & 32),
    },
  };
}

// 前后两帧的按键差，返回 [{name, down}]
export function buttonEdges(previous, next) {
  const changed = (previous ^ next) & 0xff;
  const out = [];
  for (const [name, bit] of Object.entries(KEY_BITS)) {
    if (changed & bit) out.push({ name, down: !!(next & bit) });
  }
  return out;
}

export function maskOf(names) {
  return names.reduce((mask, name) => mask | (KEY_BITS[String(name).toUpperCase()] || 0), 0);
}
