// 把文字送进目标 Agent 的应用：切前台 → 剪贴板粘贴 → 可选回车。
// 动态内容全部走 osascript argv，不拼进脚本文本。
import { execFile, spawn } from 'node:child_process';
import { runOsaScript } from './osascript.mjs';

export class DeliverError extends Error {
  constructor(message, { step = '', detail = '' } = {}) {
    super(message);
    this.name = 'DeliverError';
    this.step = step;
    this.detail = detail;
  }
}

const FRESH = 100;

export function defaultExec() {
  return {
    osascript: (lines, args, opts) => runOsaScript(lines, args, opts),
    open: (args) => new Promise((resolve, reject) => {
      const child = spawn('/usr/bin/open', args, { stdio: ['ignore', 'pipe', 'pipe'] });
      const err = [];
      child.stderr.on('data', (c) => err.push(c));
      child.on('error', reject);
      child.on('close', (code) => (code === 0 ? resolve('') : reject(new DeliverError(`open 失败：${Buffer.concat(err).toString().trim()}`, { step: 'open' }))));
    }),
    pbpaste: () => new Promise((resolve) => {
      execFile('/usr/bin/pbpaste', [], { timeout: 3000 }, (err, stdout) => resolve(err ? '' : String(stdout)));
    }),
    pbcopy: (text) => new Promise((resolve) => {
      const child = spawn('/usr/bin/pbcopy', [], { stdio: ['pipe', 'ignore', 'ignore'] });
      child.on('error', () => resolve(false));
      child.on('close', () => resolve(true));
      child.stdin.end(text);
    }),
    sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  };
}

// 前台是谁：bundle id 和进程名都给，任一能对上就算激活成功
export async function frontmost(exec) {
  const out = await exec.osascript([
    'tell application "System Events"',
    'set p to first application process whose frontmost is true',
    'return (bundle identifier of p as text) & "\\t" & (name of p as text)',
    'end tell',
  ]);
  const [bundleId = '', name = ''] = String(out).split('\t');
  return { bundleId: bundleId.trim(), name: name.trim() };
}

export function matchesTarget(agent, { bundleId, name }) {
  const want = agent.app ?? {};
  if (want.bundleId) return bundleId === want.bundleId;
  if (want.name) return name.toLowerCase() === want.name.toLowerCase();
  return true; // 跟前台走：不用切
}

async function waitFrontmost(agent, exec, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let last = { bundleId: '', name: '' };
  do {
    last = await frontmost(exec);
    if (matchesTarget(agent, last)) return last;
    await exec.sleep(FRESH);
  } while (Date.now() < deadline);
  const want = agent.app?.bundleId || agent.app?.name || '目标应用';
  throw new DeliverError(`${want} 没有到前台（现在是 ${last.name || '未知'}）`, { step: 'activate', detail: JSON.stringify(last) });
}

export function launchScript(agent, command) {
  const cmd = agent.launch?.workdir ? `cd ${shellQuote(agent.launch.workdir)} && ${command}` : command;
  return {
    lines: [
      'on run argv',
      'tell application "Terminal"',
      'activate',
      'do script (item 1 of argv) in (make new window)',
      'end tell',
      'end run',
    ],
    args: [cmd],
  };
}

// 只给「终端里跑命令」用；不经过 shell 的路径不做引号处理，这里必须自己来
export function shellQuote(text) {
  return `'${String(text).replace(/'/g, `'\\''`)}'`;
}

export function pasteScript(text) {
  return {
    lines: [
      'on run argv',
      'set the clipboard to (item 1 of argv)',
      'tell application "System Events" to keystroke "v" using command down',
      'end run',
    ],
    args: [text],
  };
}

export function keyScript(send) {
  if (send === 'return') return { lines: ['tell application "System Events" to key code 36'], args: [] };
  if (send === 'cmd-return') return { lines: ['tell application "System Events" to key code 36 using command down'], args: [] };
  return null;
}

// 返回执行了哪些步骤，界面据此显示「已填进 Cursor，还没发送」这类实话。
export async function deliver(agent, text, {
  send,
  config = {},
  exec = defaultExec(),
  dryRun = config?.deliver?.dryRun ?? false,
} = {}) {
  const body = String(text ?? '');
  if (!agent) throw new DeliverError('没有指定 Agent', { step: 'plan' });
  if (!body.trim()) throw new DeliverError('文字是空的，没什么可填', { step: 'plan' });
  const effectiveSend = send ?? agent.send ?? 'return';
  const settleMs = config?.deliver?.settleMs ?? 260;
  const pasteDelayMs = config?.deliver?.pasteDelayMs ?? 160;
  const steps = [];
  const plan = [];

  // 1) 需要时先开应用窗口跑命令（调取应用）
  if (agent.launch?.command && agent.launch?.newWindow) {
    const script = launchScript(agent, agent.launch.command);
    plan.push({ type: 'launch', ...script });
    if (!dryRun) {
      try { await exec.osascript(script.lines, script.args); } catch (err) {
        throw new DeliverError(`开终端窗口失败：${err.message}`, { step: 'launch', detail: err.stderr || '' });
      }
      steps.push(`开终端窗口：${agent.launch.command}`);
      await exec.sleep(settleMs + 400);
    }
  }

  // 2) 切前台
  const hasTarget = !!(agent.app?.bundleId || agent.app?.name);
  if (hasTarget) {
    plan.push({ type: 'activate', bundleId: agent.app.bundleId, name: agent.app.name });
    if (!dryRun) {
      try {
        await exec.open(agent.app.bundleId ? ['-b', agent.app.bundleId] : ['-a', agent.app.name]);
      } catch (err) {
        throw new DeliverError(`打不开 ${agent.app.bundleId || agent.app.name}：${agent.app.bundleId ? 'Bundle ID 可能写错了' : '应用名可能写错了'}`, { step: 'open', detail: err.message });
      }
      await exec.sleep(settleMs);
      await waitFrontmost(agent, exec, 2500);
      steps.push(`切到 ${agent.app.name || agent.app.bundleId}`);
    }
  } else {
    steps.push('跟着前台走');
  }

  // 3) 粘贴。粘完把原来的剪贴板文字放回去（非文本内容会丢，README 里有写）
  const paste = pasteScript(body);
  plan.push({ type: 'paste', ...paste });
  let previous = '';
  if (!dryRun) {
    previous = await exec.pbpaste();
    try {
      await exec.osascript(paste.lines, paste.args);
    } catch (err) {
      throw new DeliverError(`粘贴失败：${err.message}`, { step: 'paste', detail: err.stderr || '' });
    }
    steps.push(`粘贴 ${body.length} 个字`);
    // 剪贴板要等目标应用真的读走以后再还原：keystroke 返回时粘贴还没处理完
    if (pasteDelayMs) await exec.sleep(pasteDelayMs);
  }

  // 4) 发送
  const key = keyScript(effectiveSend);
  if (key) {
    plan.push({ type: 'key', ...key });
    if (!dryRun) {
      try { await exec.osascript(key.lines, key.args); } catch (err) {
        throw new DeliverError(`回车失败：${err.message}`, { step: 'key', detail: err.stderr || '' });
      }
      steps.push(effectiveSend === 'cmd-return' ? '⌘回车发送' : '回车发送');
    }
  } else {
    steps.push('按设置不自动发送');
  }

  // 最后才把原来的剪贴板文字放回去，早了会把刚粘贴的内容冲掉
  if (!dryRun && previous) {
    await exec.sleep(80);
    await exec.pbcopy(previous);
  }

  return { ok: true, dryRun, send: effectiveSend, steps, plan };
}

// 权限自检：辅助功能/自动化通不通，直接拿 System Events 试一下
export async function checkPermissions(exec = defaultExec()) {
  const result = { automation: false, frontmost: '', detail: '' };
  try {
    const who = await frontmost(exec);
    result.automation = !!who.name;
    result.frontmost = who.name;
  } catch (err) {
    result.detail = err.stderr || err.message;
  }
  return result;
}
