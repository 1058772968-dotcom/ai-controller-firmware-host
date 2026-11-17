import test from 'node:test';
import assert from 'node:assert/strict';
import { isBoardMic, pickBoardMic, describeMics, resolveStartTarget, DEFAULT_BOARD_MIC_NAMES } from '../public/mic-match.js';

const mic = (label, deviceId = label) => ({ kind: 'audioinput', label, deviceId });

test('认板载麦克风的两种固件命名', () => {
  assert.equal(isBoardMic('Held-key microphone'), true);
  assert.equal(isBoardMic('AI KEY Mic POC'), true);
  assert.equal(isBoardMic('held-key MICROPHONE'), true);
  assert.equal(isBoardMic('默认 - Held-key microphone'), true);
});

test('电脑麦、手机麦、聚合设备一律不认', () => {
  for (const label of [
    'MacBook Pro麦克风',
    'MacBook Pro Microphone',
    '默认 - 内置麦克风',
    'iPhone 麦克风',
    '外接麦克风',
    'AirPods Pro',
    'BlackHole 2ch',
    'MacBook Pro麦克风（聚合）',
    'keyboard microphone stand',
    '',
    null,
  ]) {
    assert.equal(isBoardMic(label), false, '不该认成板载麦：' + label);
  }
});

test('没授权时 label 为空，不能猜成板载麦', () => {
  assert.equal(isBoardMic(''), false);
  assert.equal(describeMics([{ kind: 'audioinput', label: '', deviceId: 'x' }]).state, 'unauthorized');
});

test('板载麦在列表里就选它，哪怕不是第一个', () => {
  const list = [mic('MacBook Pro麦克风'), mic('iPhone 麦克风'), mic('Held-key microphone')];
  assert.equal(pickBoardMic(list).label, 'Held-key microphone');
  const d = describeMics(list);
  assert.equal(d.state, 'ready');
  assert.equal(d.board.length, 1);
  assert.equal(d.others.length, 2);
});

test('只有电脑麦时明确是 missing，不静默退回内置麦', () => {
  const list = [mic('MacBook Pro麦克风'), mic('BlackHole 2ch')];
  const d = describeMics(list);
  assert.equal(d.state, 'missing');
  assert.equal(d.picked, null);
});

test('记住的 deviceId 只在它仍是板载麦时生效', () => {
  const list = [mic('Held-key microphone', 'dev-1'), mic('Held-key microphone', 'dev-2')];
  assert.equal(pickBoardMic(list, { preferredDeviceId: 'dev-2' }).deviceId, 'dev-2');
  const stale = [mic('MacBook Pro麦克风', 'dev-old'), mic('Held-key microphone', 'dev-1')];
  assert.equal(pickBoardMic(stale, { preferredDeviceId: 'dev-old' }).deviceId, 'dev-1');
});

test('可以自定义板载麦名字（换固件自己改），默认值两个', () => {
  assert.deepEqual(DEFAULT_BOARD_MIC_NAMES, ['Held-key microphone', 'AI KEY Mic POC']);
  assert.equal(isBoardMic('呆毛麦克风', ['呆毛麦克风']), true);
  assert.equal(isBoardMic('Held-key microphone', ['呆毛麦克风']), false);
});

test('只认板子时：没有板载麦克风就拒绝开始录音', () => {
  const missing = describeMics([mic('MacBook Pro麦克风'), mic('iPhone 麦克风')]);
  const blocked = resolveStartTarget({ requireBoardMic: true, micView: missing, micId: 'MacBook Pro麦克风' });
  assert.equal(blocked.ok, false);
  assert.equal(blocked.reason, 'missing');
  assert.equal(blocked.deviceId, '');
  const unauthorized = resolveStartTarget({ requireBoardMic: true, micView: describeMics([mic('')]) });
  assert.equal(unauthorized.reason, 'unauthorized');
});

test('只认板子时：有板载麦克风就用它，记住的 id 失效则用第一个', () => {
  const view = describeMics([mic('MacBook Pro麦克风'), mic('Held-key microphone', 'board-1'), mic('AI KEY Mic POC', 'board-2')]);
  assert.deepEqual(resolveStartTarget({ micView: view, micId: 'board-2' }), { ok: true, deviceId: 'board-2', reason: '' });
  assert.deepEqual(resolveStartTarget({ micView: view, micId: 'MacBook Pro麦克风' }), { ok: true, deviceId: 'board-1', reason: '' });
  assert.equal(resolveStartTarget({ micView: view, micId: '' }).deviceId, 'board-1');
});

test('关掉「只允许板载麦克风」才放行电脑麦克风', () => {
  const view = describeMics([mic('MacBook Pro麦克风', 'pc-1')]);
  const allowed = resolveStartTarget({ requireBoardMic: false, micView: view, micId: 'pc-1' });
  assert.deepEqual(allowed, { ok: true, deviceId: 'pc-1', reason: '' });
});

test('非 audioinput 的设备不参与挑选', () => {
  const list = [{ kind: 'videoinput', label: 'FaceTime 高清摄像头' }, { kind: 'audiooutput', label: 'Held-key microphone' }];
  assert.equal(pickBoardMic(list), null);
  assert.equal(describeMics(list).state, 'unauthorized');
});
