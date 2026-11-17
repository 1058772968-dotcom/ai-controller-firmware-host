// PCM 与 WAV 互转。浏览器只送 PCM16，服务端负责封 WAV，ASR 只认完整音频文件。

export const DEFAULT_SAMPLE_RATE = 16000;

function writeAscii(view, offset, text) {
  for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
}

// pcm: Uint8Array（小端 int16 交错）→ 44 字节头 + 数据
export function pcm16ToWav(pcm, { sampleRate = DEFAULT_SAMPLE_RATE, channels = 1 } = {}) {
  if (!(pcm instanceof Uint8Array)) throw new Error('pcm 必须是 Uint8Array');
  if (pcm.byteLength % 2 !== 0) throw new Error('pcm 长度必须是偶数（int16）');
  if (!Number.isInteger(sampleRate) || sampleRate <= 0) throw new Error('采样率无效');
  if (!Number.isInteger(channels) || channels <= 0) throw new Error('声道数无效');
  const blockAlign = channels * 2;
  const view = new DataView(new ArrayBuffer(44 + pcm.byteLength));
  writeAscii(view, 0, 'RIFF');
  view.setUint32(4, 36 + pcm.byteLength, true);
  writeAscii(view, 8, 'WAVE');
  writeAscii(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, 'data');
  view.setUint32(40, pcm.byteLength, true);
  new Uint8Array(view.buffer).set(pcm, 44);
  return new Uint8Array(view.buffer);
}

// 只认 16 bit PCM 的 WAV；其它格式返回原因，交给调用方提示。
export function parseWav(bytes) {
  const buf = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (buf.byteLength < 44) throw new Error('不是完整的 WAV（不足 44 字节）');
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const ascii = (o, n) => String.fromCharCode(...buf.subarray(o, o + n));
  if (ascii(0, 4) !== 'RIFF' || ascii(8, 4) !== 'WAVE') throw new Error('不是 RIFF/WAVE 文件');
  let offset = 12;
  let fmt = null;
  let data = null;
  while (offset + 8 <= buf.byteLength) {
    const id = ascii(offset, 4);
    const size = view.getUint32(offset + 4, true);
    const start = offset + 8;
    if (id === 'fmt ') {
      fmt = {
        format: view.getUint16(start, true),
        channels: view.getUint16(start + 2, true),
        sampleRate: view.getUint32(start + 4, true),
        bitsPerSample: view.getUint16(start + 14, true),
      };
    } else if (id === 'data') {
      data = buf.subarray(start, Math.min(start + size, buf.byteLength));
    }
    offset = start + size + (size % 2); // 块按偶数字节对齐
  }
  if (!fmt) throw new Error('WAV 缺少 fmt 块');
  if (!data || data.byteLength === 0) throw new Error('WAV 没有音频数据');
  if (fmt.format !== 1 || fmt.bitsPerSample !== 16) throw new Error('只支持 16 bit PCM 的 WAV');
  const frames = data.byteLength / (fmt.channels * 2);
  return {
    ...fmt,
    data,
    durationMs: Math.round((frames / fmt.sampleRate) * 1000),
  };
}

// 16 kHz 单声道 16 bit：1 秒 = 32000 字节
export const BYTES_PER_SECOND_16K16B = DEFAULT_SAMPLE_RATE * 2;
