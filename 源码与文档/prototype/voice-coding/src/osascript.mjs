// 调 osascript：动态文本一律走 argv，不拼进脚本文本，省掉转义这一整类 bug。
import { spawn } from 'node:child_process';

// args: 传给脚本 run handler 的参数；script 里用 item 1 of argv 取
export function runOsaScript(lines, args = [], { timeoutMs = 15000 } = {}) {
  const scriptArgs = Array.isArray(lines) ? lines : [lines];
  for (const a of args) if (typeof a !== 'string') throw new Error('osascript 参数必须是字符串');
  const argv = scriptArgs.flatMap((line) => ['-e', line]);
  return new Promise((resolve, reject) => {
    const child = spawn('/usr/bin/osascript', [...argv, ...(args.length ? ['--', ...args] : [])], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const out = [];
    const err = [];
    let done = false;
    const timer = setTimeout(() => { if (!done) { child.kill('SIGKILL'); reject(new Error('osascript 超时')); } }, timeoutMs);
    child.stdout.on('data', (c) => out.push(c));
    child.stderr.on('data', (c) => err.push(c));
    child.on('error', (e) => { done = true; clearTimeout(timer); reject(e); });
    child.on('close', (code) => {
      done = true;
      clearTimeout(timer);
      const stdout = Buffer.concat(out).toString('utf8').trim();
      const stderr = Buffer.concat(err).toString('utf8').trim();
      if (code !== 0) {
        const e = new Error(stderr || `osascript 退出码 ${code}`);
        e.code = code;
        e.stderr = stderr;
        reject(e);
        return;
      }
      resolve(stdout);
    });
  });
}
