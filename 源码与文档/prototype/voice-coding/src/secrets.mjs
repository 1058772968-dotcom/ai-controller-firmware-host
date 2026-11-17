// ASR 密钥只从 macOS 钥匙串或环境变量读，绝不落进源码、配置文件和日志。
import { execFile } from 'node:child_process';

export const KEYCHAIN_SERVICE = 'voice-coding-bailian';
export const KEYCHAIN_ACCOUNT = 'DASHSCOPE_API_KEY';
const ENV_NAME = 'DASHSCOPE_API_KEY';

function run(file, args, { timeoutMs = 5000 } = {}) {
  return new Promise((resolve, reject) => {
    execFile(file, args, { timeout: timeoutMs }, (err, stdout, stderr) => {
      if (err) {
        err.stderr = String(stderr || '');
        reject(err);
        return;
      }
      resolve(String(stdout));
    });
  });
}

// 返回 { key, source }；source 便于界面上说清楚「从哪拿到的钥匙」
export async function readApiKey({ exec = run, env = process.env } = {}) {
  try {
    const out = await exec('/usr/bin/security', ['find-generic-password', '-s', KEYCHAIN_SERVICE, '-a', KEYCHAIN_ACCOUNT, '-w']);
    const key = out.trim();
    if (key) return { key, source: 'keychain' };
  } catch {
    // 钥匙串里没有就往下走，不当成错误
  }
  const fromEnv = (env[ENV_NAME] || '').trim();
  if (fromEnv) return { key: fromEnv, source: 'env' };
  return { key: '', source: 'missing' };
}

export async function writeApiKey(key, { exec = run } = {}) {
  const value = String(key || '').trim();
  if (!value) throw new Error('密钥为空');
  try {
    await exec('/usr/bin/security', ['add-generic-password', '-a', KEYCHAIN_ACCOUNT, '-s', KEYCHAIN_SERVICE, '-w', value, '-U']);
    return { ok: true };
  } catch (err) {
    throw new Error(`写钥匙串失败：${err.stderr?.trim() || err.message}`);
  }
}

export function maskKey(key) {
  if (!key) return '';
  if (key.length <= 10) return '*'.repeat(key.length);
  return `${key.slice(0, 6)}…${key.slice(-4)}`;
}
