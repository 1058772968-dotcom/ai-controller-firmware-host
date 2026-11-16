// AI KEY 版本 1 控制协议（32 字节，小端，CRC16-CCITT）。
// 与 engineering/rev-a/firmware/core/protocol.c 逐字节对应；本文件只做编解码，不含任何传输。
export const WIRE_SIZE = 32;
export const CMD = { HELLO: 1, CLAIM: 2, KEEPALIVE: 3, RELEASE: 4, RECORD: 5, DRAW: 6, FEEDBACK: 7, RECENTER: 8 };
export const EVT = { EDGE: 1, OWNER: 2, MIC: 3, DRAW_STATE: 4, HAPTIC: 5, RESET_INPUT: 6, CENTER: 7, ACK: 8, FAULT: 9, STATUS: 0x80, MOTION: 0x81 };
export const RESULT = ['OK', 'BAD_SESSION', 'STALE', 'NOT_CONNECTED', 'HELD', 'CONFLICT', 'INVALID'];
export const KEY = { L: 1, R: 2, V: 4, S: 8 };

export function crc16(bytes, n = bytes.length) {
  let crc = 0xffff;
  for (let i = 0; i < n; i++) {
    crc ^= bytes[i] << 8;
    for (let bit = 0; bit < 8; bit++) crc = crc & 0x8000 ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
  }
  return crc;
}

const put32 = (b, o, v) => { for (let i = 0; i < 4; i++) b[o + i] = (v >>> (8 * i)) & 0xff; };
const get32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;
const get16s = (b, o) => { const v = b[o] | (b[o + 1] << 8); return v & 0x8000 ? v - 0x10000 : v; };

export function encodeCommand(command, session, sequence, value = 0) {
  if (!Number.isInteger(command) || command < 1 || command > 8) throw new Error('无效命令');
  if (value !== 0 && value !== 1) throw new Error('value 只能是 0 或 1');
  const b = new Uint8Array(WIRE_SIZE);
  b[0] = 1; b[1] = command;
  put32(b, 4, session >>> 0); put32(b, 8, sequence >>> 0);
  b[16] = value;
  const crc = crc16(b, 30); b[30] = crc & 0xff; b[31] = crc >> 8;
  return b;
}

// 设备到主机：状态 / 事件 / 运动。CRC 或版本错误时返回 null，不猜测内容。
export function decodeReport(bytes) {
  const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (b.length !== WIRE_SIZE || b[0] !== 1) return null;
  const crc = crc16(b, 30);
  if (b[30] !== (crc & 0xff) || b[31] !== crc >> 8) return null;
  const flags = b[16];
  const out = {
    type: b[1], owner: b[2] ? 'HOST' : 'POINTER', buttons: b[3],
    session: get32(b, 4), sequence: get32(b, 8), timeMs: get32(b, 12),
    flags: { host: !!(flags & 1), micPermit: !!(flags & 2), micReady: !!(flags & 4), drawing: !!(flags & 8), haptic: !!(flags & 16), calibrated: !!(flags & 32) },
    value: b[17], hidButtons: b[18], faults: b[19], commandSequence: get32(b, 24),
    batteryValid: !!(b[28] & 1),
  };
  if (b[1] === EVT.MOTION) { out.dx = get16s(b, 20); out.dy = get16s(b, 22); }
  if (b[1] === EVT.ACK) out.result = RESULT[b[17]] ?? 'UNKNOWN';
  return out;
}
