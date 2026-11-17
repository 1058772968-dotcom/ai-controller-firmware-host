#!/usr/bin/env node
// 端到端自检：真调 ASR（用钥匙串里的密钥）+ 真往 TextEdit 里打字并回车。
// 只碰 TextEdit 一个临时文档，打完读回来核对，然后不保存关掉。别的东西一律不碰。
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from '../src/config.mjs';
import { readApiKey, maskKey } from '../src/secrets.mjs';
import { transcribe } from '../src/asr.mjs';
import { deliver, checkPermissions, defaultExec } from '../src/deliver.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const skipDeliver = process.argv.includes('--no-deliver');
const wavArg = process.argv.find((a) => a.endsWith('.wav'));
const WAV_CANDIDATES = [
  wavArg,
  path.resolve(ROOT, 'tools/sample-5s.wav'),
  path.resolve(ROOT, '../../docs/engineering/项目档案/20261106-音频固件/证据/麦克风闭环/语音样本-电脑扬声器到硬件麦克风.wav'),
].filter(Boolean);
const { existsSync } = await import('node:fs');
const WAV = WAV_CANDIDATES.find((p) => existsSync(p)) || '';

const results = [];
const record = (name, ok, detail) => { results.push({ name, ok, detail }); console.log(`${ok ? '✔' : '✖'} ${name}${detail ? ' · ' + detail : ''}`); };

const { config } = await loadConfig();

// 1) 密钥
const key = await readApiKey();
record('ASR 密钥可用', !!key.key, key.key ? `${key.source} · ${maskKey(key.key)}` : '钥匙串 voice-coding-bailian 或环境变量 DASHSCOPE_API_KEY 都没有');

// 2) ASR（真调网络）
let text = '';
if (!WAV) {
  console.log('· 没有样例音频，跳过 ASR 识别；要看识别可以直接在页面里说一句');
} else if (key.key) {
  try {
    const wav = await readFile(WAV);
    const res = await transcribe(new Uint8Array(wav), { apiKey: key.key, config });
    text = res.text;
    record('ASR 识别', text.length > 0, `${text}（${(res.durationMs / 1000).toFixed(1)} 秒录音 → ${res.elapsedMs} ms）`);
  } catch (err) {
    record('ASR 识别', false, err.message);
  }
} else {
  record('ASR 识别', false, '没有密钥，跳过');
}

// 3) 权限
const exec = defaultExec();
const perms = await checkPermissions(exec);
record('辅助功能 / 自动化', perms.automation, perms.automation ? `当前前台：${perms.frontmost}` : perms.detail);

// 4) 真投递：只往 TextEdit 的新文档里打
if (!skipDeliver && perms.automation) {
  const probe = '语音coding自检 ' + new Date().toISOString().slice(11, 19);
  const agent = { id: 'selftest', name: 'TextEdit', app: { bundleId: 'com.apple.TextEdit', name: '文本编辑' }, launch: {}, send: 'return' };
  try {
    await exec.osascript(['tell application "TextEdit"', 'activate', 'make new document', 'end tell']);
    await exec.sleep(600);
    const res = await deliver(agent, probe, { config, exec });
    await exec.sleep(250);
    // 用标记包住正文，免得 osascript 输出被 trim 掉行尾换行，回车就查不出来了
    const back = await exec.osascript([
      'tell application "TextEdit"',
      'set t to text of document 1',
      'close document 1 saving no',
      'end tell',
      'return "«" & t & "»"',
    ]);
    const landed = back.includes(probe);
    record('投递到 TextEdit', landed, res.steps.join(' → ') + (landed ? ' · 读回一致' : ' · 读回不一致'));
    const newline = back.includes(probe + '\n');
    record('回车已发送', landed && newline, landed && newline ? '正文后面多了一个换行' : '没读到换行，回车可能没发出去');
  } catch (err) {
    record('投递到 TextEdit', false, err.message);
    await exec.osascript(['tell application "TextEdit"', 'close document 1 saving no', 'end tell']).catch(() => {});
  }
} else if (skipDeliver) {
  console.log('· 跳过真投递（--no-deliver）');
}

const failed = results.filter((r) => !r.ok);
console.log('\n' + (failed.length ? `${results.length - failed.length}/${results.length} 通过，${failed.length} 项失败` : `${results.length}/${results.length} 全部通过`));
process.exit(failed.length ? 1 : 0);
