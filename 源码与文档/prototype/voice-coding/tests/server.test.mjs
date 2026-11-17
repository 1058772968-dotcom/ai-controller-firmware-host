import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import { mkdtemp, readFile } from 'node:fs/promises';
import { createApp } from '../src/server.mjs';
import { pcm16ToWav, parseWav } from '../src/wav.mjs';

const fakeExec = () => ({
  async osascript(lines) {
    if (lines.join(' ').includes('bundle identifier of p')) return 'com.apple.Terminal\tTerminal';
    return '';
  },
  async open() {},
  async pbpaste() { return ''; },
  async pbcopy() { return true; },
  async sleep() {},
});

async function boot(overrides = {}) {
  const dataDir = await mkdtemp(path.join(os.tmpdir(), 'vc-srv-'));
  const seen = { asr: [], deliver: [] };
  const app = createApp({
    dataDir,
    deps: {
      readApiKey: async () => ({ key: 'sk-fake', source: 'env' }),
      writeApiKey: async () => ({ ok: true }),
      transcribe: async (wav, opts) => {
        const info = parseWav(wav);
        seen.asr.push({ sampleRate: info.sampleRate, durationMs: info.durationMs, hasKey: !!opts.apiKey });
        return { text: '把按钮改成蓝色', durationMs: info.durationMs, elapsedMs: 11, model: opts.config.asr.model };
      },
      deliver: async (agent, text, opts) => {
        seen.deliver.push({ agent: agent.id, text, send: opts.send });
        return { ok: true, dryRun: false, send: opts.send ?? agent.send, steps: ['切到 ' + agent.name, '粘贴 ' + text.length + ' 个字'], plan: [] };
      },
      exec: fakeExec(),
      ...overrides,
    },
  });
  await app.reload();
  await new Promise((resolve) => app.server.listen(0, '127.0.0.1', resolve));
  const base = 'http://127.0.0.1:' + app.server.address().port;
  return { app, base, seen, dataDir, close: () => new Promise((r) => { app.server.closeAllConnections?.(); app.server.close(r); }) };
}

const call = async (base, url, init) => {
  const res = await fetch(base + url, init);
  const body = await res.json().catch(() => ({}));
  return { status: res.status, body };
};
const postJson = (base, url, body) => call(base, url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

test('健康检查与初始状态', async () => {
  const s = await boot();
  try {
    assert.equal((await call(s.base, '/api/health')).body.ok, true);
    const { body } = await call(s.base, '/api/state');
    assert.equal(body.ok, true);
    assert.equal(body.key.hasKey, true);
    assert.equal(body.key.source, 'env');
    assert.equal(body.config.agents.length, 5);
    assert.ok(body.config.asr.model);
  } finally { await s.close(); }
});

test('PCM 进来被包成 16k WAV 再送去识别', async () => {
  const s = await boot();
  try {
    const pcm = Buffer.alloc(32000); // 1 秒
    const { status, body } = await postJson(s.base, '/api/asr', { pcmBase64: pcm.toString('base64'), sampleRate: 16000 });
    assert.equal(status, 200);
    assert.equal(body.text, '把按钮改成蓝色');
    assert.equal(s.seen.asr.length, 1);
    assert.equal(s.seen.asr[0].sampleRate, 16000);
    assert.equal(s.seen.asr[0].durationMs, 1000);
    assert.equal(s.seen.asr[0].hasKey, true);
    const log = (await call(s.base, '/api/log?since=0')).body;
    assert.ok(log.entries.some((e) => e.level === 'asr'));
  } finally { await s.close(); }
});

test('没有音频的请求被拒，说明缺什么', async () => {
  const s = await boot();
  try {
    const { status, body } = await postJson(s.base, '/api/asr', {});
    assert.equal(status, 400);
    assert.equal(body.ok, false);
    assert.match(body.error.message, /pcmBase64/);
  } finally { await s.close(); }
});

test('原始 WAV 上传也能识别', async () => {
  const s = await boot();
  try {
    const wav = pcm16ToWav(new Uint8Array(16000));
    const res = await fetch(s.base + '/api/asr/raw', { method: 'POST', body: wav });
    const body = await res.json();
    assert.equal(res.status, 200);
    assert.equal(body.text, '把按钮改成蓝色');
    assert.equal(s.seen.asr[0].durationMs, 500);
  } finally { await s.close(); }
});

test('投递会照着请求里的 send 走，日志有记录', async () => {
  const s = await boot();
  try {
    const { status, body } = await postJson(s.base, '/api/deliver', { agentId: 'claude-code', text: '跑一下测试', send: 'none' });
    assert.equal(status, 200);
    assert.equal(body.send, 'none');
    assert.deepEqual(s.seen.deliver[0], { agent: 'claude-code', text: '跑一下测试', send: 'none' });
    const log = (await call(s.base, '/api/log?since=0')).body;
    assert.ok(log.entries.some((e) => e.level === 'send' && e.text.includes('Claude Code')));
  } finally { await s.close(); }
});

test('投递到不存在的 Agent 返回冲突，不会乱贴', async () => {
  const s = await boot();
  try {
    const { status, body } = await postJson(s.base, '/api/deliver', { agentId: 'ghost', text: 'x' });
    assert.equal(status, 409);
    assert.match(body.error.message, /ghost/);
    assert.equal(s.seen.deliver.length, 0);
  } finally { await s.close(); }
});

test('Agent 列表能存能读，落盘到 config.json', async () => {
  const s = await boot();
  try {
    const agents = [{ id: 'solo', name: '独苗', app: { bundleId: 'com.apple.TextEdit' }, send: 'none', launch: {} }];
    const put = await call(s.base, '/api/agents', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agents }) });
    assert.equal(put.status, 200);
    assert.equal(put.body.agents.length, 1);
    const again = await call(s.base, '/api/agents');
    assert.deepEqual(again.body.agents.map((a) => a.id), ['solo']);
    const raw = JSON.parse(await readFile(path.join(s.dataDir, 'config.json'), 'utf8'));
    assert.equal(raw.agents[0].name, '独苗');
  } finally { await s.close(); }
});

test('设置分区合并保存，不动其它字段', async () => {
  const s = await boot();
  try {
    const { body } = await call(s.base, '/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ behavior: { autoSend: true } }) });
    assert.equal(body.config.behavior.autoSend, true);
    assert.equal(body.config.behavior.prefixRouting, true);
    assert.equal(body.config.agents.length, 5);
  } finally { await s.close(); }
});

test('前缀路由接口按配置返回目标', async () => {
  const s = await boot();
  try {
    const { body } = await postJson(s.base, '/api/route', { text: 'Cursor，把这段抽成函数' });
    assert.equal(body.agentId, 'cursor');
    assert.equal(body.text, '把这段抽成函数');
    const none = await postJson(s.base, '/api/route', { text: '随便说点什么' });
    assert.equal(none.body.agentId, null);
  } finally { await s.close(); }
});

test('权限检查走执行器并回报前台应用', async () => {
  const s = await boot();
  try {
    const { body } = await postJson(s.base, '/api/permissions', {});
    assert.equal(body.automation, true);
    assert.equal(body.frontmost, 'Terminal');
  } finally { await s.close(); }
});

test('静态页面能打开，跳出目录的路径拿不到文件', async () => {
  const s = await boot();
  try {
    const page = await fetch(s.base + '/');
    assert.equal(page.status, 200);
    assert.match(page.headers.get('content-type'), /text\/html/);
    assert.match(await page.text(), /呆毛语音 Coding/);
    const css = await fetch(s.base + '/style.css');
    assert.equal(css.status, 200);
    const escape = await fetch(s.base + '/..%2Fpackage.json');
    assert.equal(escape.status, 404);
  } finally { await s.close(); }
});

test('未知接口一律 404 JSON', async () => {
  const s = await boot();
  try {
    const { status, body } = await call(s.base, '/api/nope');
    assert.equal(status, 404);
    assert.equal(body.ok, false);
  } finally { await s.close(); }
});

test('识别失败时状态码和原因能看懂', async () => {
  const s = await boot({
    transcribe: async () => { const { AsrError } = await import('../src/asr.mjs'); throw new AsrError('ASR 密钥无效或没有这个模型的权限', { kind: 'auth' }); },
  });
  try {
    const { status, body } = await postJson(s.base, '/api/asr', { pcmBase64: Buffer.alloc(3200).toString('base64') });
    assert.equal(status, 400);
    assert.equal(body.error.kind, 'auth');
    assert.match(body.error.message, /密钥/);
  } finally { await s.close(); }
});
