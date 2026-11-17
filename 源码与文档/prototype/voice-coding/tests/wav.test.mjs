import test from 'node:test';
import assert from 'node:assert/strict';
import { pcm16ToWav, parseWav } from '../src/wav.mjs';

const pcm = (ms, rate = 16000) => new Uint8Array(Math.round((rate * ms) / 1000) * 2);

test('PCM 封成 16k 单声道 WAV 头字段正确', () => {
  const wav = pcm16ToWav(pcm(1000));
  assert.equal(wav.byteLength, 32044);
  const text = (o, n) => String.fromCharCode(...wav.subarray(o, o + n));
  assert.equal(text(0, 4), 'RIFF');
  assert.equal(text(8, 4), 'WAVE');
  const view = new DataView(wav.buffer);
  assert.equal(view.getUint32(4, true), 32036);
  assert.equal(view.getUint16(20, true), 1);
  assert.equal(view.getUint16(22, true), 1);
  assert.equal(view.getUint32(24, true), 16000);
  assert.equal(view.getUint32(28, true), 32000);
  assert.equal(view.getUint16(34, true), 16);
  assert.equal(view.getUint32(40, true), 32000);
});

test('封了再解，时长和采样率对得上', () => {
  const wav = pcm16ToWav(pcm(2500, 16000));
  const info = parseWav(wav);
  assert.equal(info.sampleRate, 16000);
  assert.equal(info.channels, 1);
  assert.equal(info.bitsPerSample, 16);
  assert.equal(info.durationMs, 2500);
  assert.equal(info.data.byteLength, 80000);
});

test('偶数字节之外的长度直接拒绝', () => {
  assert.throws(() => pcm16ToWav(new Uint8Array(3)), /偶数/);
  assert.throws(() => pcm16ToWav(new Uint8Array(4), { sampleRate: 0 }), /采样率/);
  assert.throws(() => pcm16ToWav(new Uint8Array(4), { channels: 0 }), /声道/);
});

test('解析器对非 WAV、缺块、8 bit 都给明确原因', () => {
  assert.throws(() => parseWav(new Uint8Array(10)), /不足 44/);
  assert.throws(() => parseWav(new Uint8Array(60)), /RIFF/);
  const noData = pcm16ToWav(pcm(10)).slice(0, 44);
  const dv = new DataView(noData.buffer);
  dv.setUint32(40, 0, true);
  assert.throws(() => parseWav(new Uint8Array(noData.buffer)), /没有音频数据/);
  const eightBit = pcm16ToWav(pcm(10));
  new DataView(eightBit.buffer).setUint16(34, 8, true);
  assert.throws(() => parseWav(eightBit), /16 bit PCM/);
});
