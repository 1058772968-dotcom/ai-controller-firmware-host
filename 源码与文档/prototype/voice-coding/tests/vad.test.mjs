import test from 'node:test';
import assert from 'node:assert/strict';
import { VadSegmenter, floatToPcm16 } from '../public/vad.js';

const RATE = 16000;
const BLOCK = 512; // 32 ms
const silent = (n = BLOCK) => new Float32Array(n);
const loud = (n = BLOCK, amp = 0.2) => Float32Array.from({ length: n }, (_, i) => (i % 2 ? amp : -amp));

test('一直安静就不会切出任何话', () => {
  const vad = new VadSegmenter({ sampleRate: RATE });
  let t = 0;
  let utterances = 0;
  for (let i = 0; i < 100; i += 1) {
    t += 32;
    const r = vad.push(silent(), t);
    if (r.utterance) utterances += 1;
  }
  assert.equal(utterances, 0);
  assert.equal(vad.state, 'idle');
});

test('说一句再停，切出一段话，长度包含预录和拖尾', () => {
  const vad = new VadSegmenter({ sampleRate: RATE, hangoverMs: 300 });
  let t = 0;
  let started = 0;
  let utterance = null;
  // 300 ms 安静铺底
  for (let i = 0; i < 10; i += 1) { t += 32; vad.push(silent(), t); }
  // 600 ms 说话
  for (let i = 0; i < 19; i += 1) { t += 32; const r = vad.push(loud(), t); if (r.started) started += 1; }
  // 600 ms 安静
  for (let i = 0; i < 19; i += 1) { t += 32; const r = vad.push(silent(), t); if (r.utterance) utterance = r.utterance; }
  assert.equal(started, 1);
  assert.ok(utterance, '应该切出一段话');
  assert.ok(utterance.durationMs >= 600, `录音太短：${utterance.durationMs}`);
  assert.ok(utterance.durationMs <= 1600, `录音太长：${utterance.durationMs}`);
  assert.ok(utterance.peak > 0.15);
  assert.equal(vad.state, 'idle');
});

test('单击一下（一块）不算说话，避免每点一下都识别', () => {
  const vad = new VadSegmenter({ sampleRate: RATE, startHoldMs: 120 });
  vad.push(silent(), 10);
  const r = vad.push(loud(), 42);
  assert.equal(r.started, false);
  assert.equal(vad.state, 'idle');
  const after = vad.push(silent(), 74);
  assert.equal(after.utterance, null);
});

test('声音一直不断时按最长时长强制断开', () => {
  const vad = new VadSegmenter({ sampleRate: RATE, maxUtteranceMs: 200 });
  let t = 0;
  let utterance = null;
  for (let i = 0; i < 40; i += 1) {
    t += 32;
    const r = vad.push(loud(), t);
    if (r.utterance) { utterance = r.utterance; break; }
  }
  assert.ok(utterance);
  assert.ok(utterance.durationMs >= 200 && utterance.durationMs <= 400);
});

test('flush 能把正在说的这段收上来', () => {
  const vad = new VadSegmenter({ sampleRate: RATE });
  let t = 0;
  for (let i = 0; i < 10; i += 1) { t += 32; vad.push(silent(), t); }
  for (let i = 0; i < 12; i += 1) { t += 32; vad.push(loud(), t); }
  assert.equal(vad.state, 'active');
  const utterance = vad.flush();
  assert.ok(utterance && utterance.durationMs > 0);
  assert.equal(vad.state, 'idle');
  assert.equal(vad.flush(), null);
});

test('每块都给出电平，安静和说话区分得开', () => {
  const vad = new VadSegmenter({ sampleRate: RATE });
  const quiet = vad.push(silent(), 32).level;
  const noisy = vad.push(loud(), 64).level;
  assert.ok(quiet < 0.001);
  assert.ok(noisy > 0.15);
});

test('Float32 转 PCM16 会限幅、字节序是小端', () => {
  const pcm = floatToPcm16(new Float32Array([0, 0.5, -0.5, 2, -2]));
  assert.equal(pcm.byteLength, 10);
  const view = new DataView(pcm.buffer);
  assert.equal(view.getInt16(0, true), 0);
  assert.equal(view.getInt16(2, true), Math.round(0.5 * 0x7fff));
  assert.equal(view.getInt16(4, true), -0x4000);
  assert.equal(view.getInt16(6, true), 0x7fff);
  assert.equal(view.getInt16(8, true), -0x8000);
});
