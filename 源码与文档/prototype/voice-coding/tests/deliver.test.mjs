import test from 'node:test';
import assert from 'node:assert/strict';
import { deliver, frontmost, shellQuote, pasteScript, keyScript, launchScript, DeliverError } from '../src/deliver.mjs';

// 假执行器：记录调用了什么，前台状态可改，不发真按键
function fakeExec({ front = { bundleId: 'com.apple.Terminal', name: 'Terminal' }, afterOpen = null, failPaste = false } = {}) {
  const calls = [];
  const state = { front: { ...front } };
  return {
    calls,
    state,
    async osascript(lines, args = []) {
      calls.push({ kind: 'osascript', lines, args });
      if (lines.join(' ').includes('bundle identifier of p')) return `${state.front.bundleId}\t${state.front.name}`;
      if (failPaste && lines.join(' ').includes('keystroke')) throw Object.assign(new Error('not authorized'), { stderr: 'osascript: not authorized to send keystrokes' });
      return '';
    },
    async open(args) {
      calls.push({ kind: 'open', args });
      if (afterOpen) state.front = afterOpen;
    },
    async pbpaste() { return '原来的剪贴板'; },
    async pbcopy(text) { calls.push({ kind: 'pbcopy', text }); },
    async sleep() {},
  };
}

const agent = (patch = {}) => ({
  id: 'a', name: 'A', aliases: [], app: { bundleId: 'com.apple.Terminal', name: 'Terminal' },
  launch: { command: '', workdir: '', newWindow: false }, send: 'return', enabled: true, note: '',
  ...patch,
});

test('跟着前台走：不切应用，只粘贴和回车', async () => {
  const exec = fakeExec();
  const res = await deliver(agent({ app: { bundleId: '', name: '' } }), '改一下颜色', { exec, config: {} });
  assert.deepEqual(res.steps, ['跟着前台走', '粘贴 5 个字', '回车发送']);
  assert.ok(!exec.calls.some((c) => c.kind === 'open'));
  assert.equal(res.send, 'return');
});

test('有目标应用：先 open 再等它到前台，粘贴用 argv 传文本', async () => {
  const exec = fakeExec({ front: { bundleId: 'com.google.Chrome', name: 'Google Chrome' }, afterOpen: { bundleId: 'com.apple.Terminal', name: 'Terminal' } });
  const text = '带「引号」和 $ 符号\n还有换行的文本';
  const res = await deliver(agent(), text, { exec, config: {} });
  const open = exec.calls.find((c) => c.kind === 'open');
  assert.deepEqual(open.args, ['-b', 'com.apple.Terminal']);
  const paste = exec.calls.find((c) => c.kind === 'osascript' && c.lines.join(' ').includes('the clipboard'));
  assert.deepEqual(paste.args, [text]);
  assert.ok(!paste.lines.join('\n').includes('引号'), '文本不能拼进脚本');
  assert.ok(res.steps.includes('切到 Terminal'));
});

test('目标应用不到前台就报错，绝不把文字贴到别的窗口', async () => {
  const exec = fakeExec({ front: { bundleId: 'com.google.Chrome', name: 'Google Chrome' }, afterOpen: { bundleId: 'com.google.Chrome', name: 'Google Chrome' } });
  await assert.rejects(() => deliver(agent(), '危险', { exec, config: {} }), (err) => {
    assert.ok(err instanceof DeliverError);
    assert.equal(err.step, 'activate');
    assert.match(err.message, /没有到前台/);
    return true;
  });
  assert.ok(!exec.calls.some((c) => c.kind === 'osascript' && c.lines.join(' ').includes('the clipboard')));
});

test('dryRun 只出计划，一个动作都不执行', async () => {
  const exec = fakeExec();
  const res = await deliver(agent(), '演练', { exec, config: { deliver: { dryRun: true } } });
  assert.equal(res.dryRun, true);
  assert.equal(exec.calls.length, 0);
  assert.ok(res.plan.some((p) => p.type === 'paste'));
  assert.ok(res.plan.some((p) => p.type === 'key'));
});

test('send 为 none 时只填入不回车', async () => {
  const exec = fakeExec();
  const res = await deliver(agent({ send: 'none' }), '只看不送', { exec, config: {} });
  assert.equal(res.send, 'none');
  assert.ok(res.steps.includes('按设置不自动发送'));
  assert.ok(!exec.calls.some((c) => c.kind === 'osascript' && c.lines.join(' ').includes('key code 36')));
});

test('可以临时覆盖发送方式（界面上按 L 强制发送）', async () => {
  const exec = fakeExec();
  const res = await deliver(agent({ send: 'none' }), '现在发', { exec, config: {}, send: 'cmd-return' });
  assert.equal(res.send, 'cmd-return');
  assert.ok(exec.calls.some((c) => c.lines?.join(' ').includes('key code 36 using command down')));
});

test('空文字直接拒绝，不碰剪贴板', async () => {
  const exec = fakeExec();
  await assert.rejects(() => deliver(agent(), '   ', { exec, config: {} }), (err) => err.step === 'plan');
  assert.equal(exec.calls.length, 0);
});

test('粘不进去时明确说是粘贴这一步失败', async () => {
  const exec = fakeExec({ failPaste: true });
  await assert.rejects(() => deliver(agent({ app: { bundleId: '', name: '' } }), '文字', { exec, config: {} }), (err) => {
    assert.equal(err.step, 'paste');
    assert.match(err.message, /粘贴失败/);
    return true;
  });
});

test('开终端窗口跑命令：工作目录被正确引用，命令走 argv', () => {
  const script = launchScript(agent({ launch: { command: 'claude', workdir: "~/my code/it's", newWindow: true } }), 'claude');
  assert.equal(script.args[0], "cd '~/my code/it'\\''s' && claude");
  assert.ok(script.lines.join(' ').includes('make new window'));
  assert.ok(!script.lines.join(' ').includes('claude'), '命令不能拼进脚本');
});

test('带 newWindow 的 Agent 会先开窗口再粘贴', async () => {
  const exec = fakeExec();
  const res = await deliver(agent({ launch: { command: 'claude', workdir: '', newWindow: true } }), '跑测试', { exec, config: {} });
  assert.ok(res.steps.some((s) => s.includes('开终端窗口')));
  const launchCall = exec.calls.find((c) => c.kind === 'osascript' && c.lines.join(' ').includes('do script'));
  assert.deepEqual(launchCall.args, ['claude']);
});

test('粘贴后把原来的剪贴板文字放回去', async () => {
  const exec = fakeExec();
  await deliver(agent({ app: { bundleId: '', name: '' } }), '新内容', { exec, config: {} });
  const restore = exec.calls.find((c) => c.kind === 'pbcopy');
  assert.equal(restore.text, '原来的剪贴板');
});

test('前台探测：解析 bundle id 与进程名', async () => {
  const who = await frontmost(fakeExec());
  assert.deepEqual(who, { bundleId: 'com.apple.Terminal', name: 'Terminal' });
});

test('按键脚本按发送方式区分', () => {
  assert.match(keyScript('return').lines[0], /key code 36$/);
  assert.match(keyScript('cmd-return').lines[0], /using command down/);
  assert.equal(keyScript('none'), null);
});

test('单引号引用规则', () => {
  assert.equal(shellQuote("a b"), "'a b'");
  assert.equal(shellQuote("it's"), "'it'\\''s'");
  assert.equal(shellQuote(''), "''");
});

test('粘贴脚本的文本只出现在 argv 里', () => {
  const script = pasteScript("a'b\"c");
  assert.deepEqual(script.args, ["a'b\"c"]);
  assert.ok(script.lines.every((l) => !l.includes("a'b")));
});
