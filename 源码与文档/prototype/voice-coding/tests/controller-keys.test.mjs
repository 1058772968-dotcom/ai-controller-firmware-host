import test from 'node:test';
import assert from 'node:assert/strict';
import { mapControllerKey, BUTTONS, RECORD_KEY, KEY_ROLES } from '../public/controller-keys.js';

test('按键位与固件一致（L=1 R=2 V=4 S=8）', () => {
  assert.deepEqual(BUTTONS, { L: 1, R: 2, V: 4, S: 8 });
  assert.equal(RECORD_KEY, 'V');
  assert.deepEqual(Object.keys(KEY_ROLES), ['V', 'L', 'R', 'S']);
});

test('V 按住开始录音，松开结束', () => {
  assert.deepEqual(mapControllerKey('V', true, { recording: false }), { action: 'record-start', reason: '' });
  assert.deepEqual(mapControllerKey('V', false, { recording: true }), { action: 'record-stop', reason: '' });
});

test('V 重复事件不会重复开始或结束', () => {
  assert.equal(mapControllerKey('V', true, { recording: true }).action, 'none');
  assert.equal(mapControllerKey('V', false, { recording: false }).action, 'none');
});

test('L 有文字才发送，没文字只提示', () => {
  assert.equal(mapControllerKey('L', true, { hasTranscript: true }).action, 'send');
  const empty = mapControllerKey('L', true, { hasTranscript: false });
  assert.equal(empty.action, 'none');
  assert.match(empty.reason, /没有文字/);
});

test('R 清空，S 暂时不绑功能', () => {
  assert.equal(mapControllerKey('R', true).action, 'clear');
  const s = mapControllerKey('S', true);
  assert.equal(s.action, 'none');
  assert.match(s.reason, /还没绑/);
});

test('L/R/S 松开不触发动作', () => {
  for (const key of ['L', 'R', 'S']) assert.equal(mapControllerKey(key, false, { hasTranscript: true }).action, 'none');
});

test('大小写和未知键都稳妥', () => {
  assert.equal(mapControllerKey('v', true).action, 'record-start');
  assert.equal(mapControllerKey('X', true).action, 'none');
  assert.equal(mapControllerKey(null, true).action, 'none');
});
