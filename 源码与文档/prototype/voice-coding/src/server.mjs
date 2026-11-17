// 本机服务：静态页面 + ASR + Agent 投递。只监听 127.0.0.1，不做对外服务。
import http from 'node:http';
import path from 'node:path';
import { readFile } from 'node:fs/promises';
import { appendFile, mkdir } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { loadConfig, saveConfig, normalizeConfig, agentById, routeByPrefix, homeDir } from './config.mjs';
import { readApiKey, writeApiKey, maskKey } from './secrets.mjs';
import { transcribe, AsrError } from './asr.mjs';
import { pcm16ToWav } from './wav.mjs';
import { deliver, checkPermissions, frontmost, launchScript, DeliverError, defaultExec } from './deliver.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const APP_ROOT = path.resolve(HERE, '..');
const PUBLIC_DIR = path.join(APP_ROOT, 'public');
const MAX_BODY = 32 * 1024 * 1024;

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
};

// 编译一次、之后复用；失败就把 stderr 说出来，别让界面只看到「失败」
async function resetUsbDevice() {
  const bin = path.join(os.tmpdir(), 'voice-coding-usbreset');
  const src = path.join(APP_ROOT, 'tools', 'usbreset.swift');
  const run = (file, args) => new Promise((resolve, reject) => {
    execFile(file, args, { timeout: 30000 }, (err, stdout, stderr) => (err ? reject(new Error(String(stderr || err.message).trim())) : resolve(String(stdout).trim())));
  });
  try {
    await readFile(bin);
  } catch {
    await run('/usr/bin/swiftc', ['-O', src, '-o', bin]);
  }
  return (await run(bin, [])).replace(/\n/g, ' / ');
}

function jsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > MAX_BODY) { reject(Object.assign(new Error('请求体太大'), { status: 413 })); req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', () => {
      if (!chunks.length) { resolve({}); return; }
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); }
      catch { reject(Object.assign(new Error('请求不是合法 JSON'), { status: 400 })); }
    });
    req.on('error', reject);
  });
}

function rawBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > MAX_BODY) { reject(Object.assign(new Error('请求体太大'), { status: 413 })); req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

export function createApp({ deps = {}, dataDir = homeDir() } = {}) {
  const log = { entries: [], seq: 0 };
  const sink = deps.exec ?? defaultExec();
  const asrFn = deps.transcribe ?? transcribe;
  const deliverFn = deps.deliver ?? deliver;
  const keyReader = deps.readApiKey ?? readApiKey;
  const keyWriter = deps.writeApiKey ?? writeApiKey;
  const configFile = path.join(dataDir, 'config.json');
  const logFile = path.join(dataDir, 'logs', `${new Date().toISOString().slice(0, 10)}.log`);

  function record(level, text, extra = {}) {
    const entry = { seq: ++log.seq, ts: Date.now(), level, text, ...extra };
    log.entries.push(entry);
    if (log.entries.length > 500) log.entries.splice(0, log.entries.length - 500);
    mkdir(path.join(dataDir, 'logs'), { recursive: true })
      .then(() => appendFile(logFile, `${new Date(entry.ts).toISOString()} [${level}] ${text}\n`))
      .catch(() => {});
    return entry;
  }

  const state = { config: normalizeConfig(null).config, issues: [], startedAt: Date.now() };
  let pkgVersion = '0';
  readFile(path.join(APP_ROOT, 'package.json'), 'utf8').then((t) => { pkgVersion = JSON.parse(t).version; }).catch(() => {});

  async function reload() {
    const { config, issues } = await loadConfig(configFile);
    state.config = config;
    state.issues = issues;
    return state.config;
  }

  async function persist(next) {
    const { config, issues } = await saveConfig(next, configFile);
    state.config = config;
    state.issues = issues;
    return { config, issues };
  }

  async function statePayload() {
    const key = await keyReader();
    return {
      ok: true,
      version: pkgVersion,
      config: state.config,
      issues: state.issues,
      key: { hasKey: !!key.key, source: key.source, hint: maskKey(key.key) },
      serverTime: Date.now(),
      logSeq: log.seq,
    };
  }

  async function handleAsr(payload) {
    const key = await keyReader();
    const sampleRate = Number(payload.sampleRate) || state.config.audio.sampleRate;
    let wav;
    if (payload.wavBase64) {
      wav = Buffer.from(String(payload.wavBase64), 'base64');
    } else if (payload.pcmBase64) {
      const pcm = Buffer.from(String(payload.pcmBase64), 'base64');
      if (!pcm.byteLength) throw new AsrError('没有收到音频数据', { kind: 'audio' });
      wav = pcm16ToWav(new Uint8Array(pcm), { sampleRate, channels: 1 });
    } else {
      throw new AsrError('请求里没有 pcmBase64 或 wavBase64', { kind: 'audio' });
    }
    const result = await asrFn(wav, { apiKey: key.key, config: state.config });
    record('asr', `识别 ${result.text.length} 字（${(result.durationMs / 1000).toFixed(1)} 秒录音，用时 ${result.elapsedMs} ms）`);
    return result;
  }

  async function handleDeliver(payload) {
    const agent = payload.agentId ? agentById(state.config, payload.agentId) : null;
    if (payload.agentId && !agent) throw new DeliverError(`没有这个 Agent：${payload.agentId}`, { step: 'plan' });
    const target = agent ?? { id: 'frontmost', name: '前台', app: {}, launch: {}, send: 'none' };
    const send = payload.send === 'return' || payload.send === 'cmd-return' || payload.send === 'none' ? payload.send : undefined;
    const result = await deliverFn(target, payload.text, { send, config: state.config, exec: sink });
    if (result.dryRun) record('plan', `演练：会填进「${target.name}」并 ${result.send === 'none' ? '不发送' : '发送'}`);
    else record('send', `已填进「${target.name}」：${String(payload.text).slice(0, 60)}${String(payload.text).length > 60 ? '…' : ''}`, { steps: result.steps });
    if (payload.agentId && payload.agentId !== state.config.ui.lastAgentId) {
      state.config.ui.lastAgentId = payload.agentId;
      state.config = normalizeConfig(state.config).config;
    }
    return result;
  }

  async function handleActivate(agentId) {
    const agent = agentById(state.config, agentId);
    if (!agent) throw new DeliverError(`没有这个 Agent：${agentId}`, { step: 'plan' });
    const exec = sink;
    if (agent.launch?.command && agent.launch?.newWindow) {
      const script = launchScript(agent, agent.launch.command);
      await exec.osascript(script.lines, script.args);
      record('app', `开终端窗口：${agent.launch.command}`);
      await exec.sleep((state.config.deliver.settleMs ?? 260) + 400);
    } else if (agent.app?.bundleId || agent.app?.name) {
      await exec.open(agent.app.bundleId ? ['-b', agent.app.bundleId] : ['-a', agent.app.name]);
      await exec.sleep(state.config.deliver.settleMs ?? 260);
      record('app', `打开 ${agent.app.name || agent.app.bundleId}`);
    } else {
      record('app', '这个 Agent 是「跟着前台走」，不用切应用');
    }
    const who = await frontmost(exec).catch(() => ({ bundleId: '', name: '' }));
    return { ok: true, frontmost: who };
  }

  async function route(method, url, req, res) {
    const u = new URL(url, 'http://127.0.0.1');
    const p = u.pathname;

    if (p === '/api/health') return [200, { ok: true, pid: process.pid }];
    if (p === '/api/state' && method === 'GET') return [200, await statePayload()];
    if (p === '/api/log' && method === 'GET') {
      const since = Number(u.searchParams.get('since') || 0);
      return [200, { ok: true, entries: log.entries.filter((e) => e.seq > since), seq: log.seq }];
    }
    if (p === '/api/permissions' && method === 'POST') {
      const perms = await checkPermissions(sink);
      record('perm', perms.automation ? `辅助功能/自动化可用（当前前台：${perms.frontmost}）` : `自动化不可用：${perms.detail.slice(0, 120)}`);
      return [200, { ok: true, ...perms }];
    }
    if (p === '/api/agents' && method === 'GET') return [200, { ok: true, agents: state.config.agents }];
    if (p === '/api/agents' && method === 'PUT') {
      const body = await jsonBody(req);
      const next = { ...state.config, agents: body.agents ?? [] };
      const { config, issues } = await persist(next);
      record('cfg', `保存 Agent 列表：${config.agents.length} 个`);
      return [200, { ok: true, agents: config.agents, issues }];
    }
    if (p === '/api/settings' && method === 'PUT') {
      const body = await jsonBody(req);
      const next = { ...state.config };
      for (const section of ['asr', 'audio', 'behavior', 'deliver', 'ui']) {
        if (body[section] && typeof body[section] === 'object') next[section] = { ...next[section], ...body[section] };
      }
      const { config, issues } = await persist(next);
      record('cfg', '保存设置');
      return [200, { ok: true, config, issues }];
    }
    if (p === '/api/key' && method === 'POST') {
      const body = await jsonBody(req);
      await keyWriter(String(body.key ?? ''));
      record('key', 'ASR 密钥已写入钥匙串');
      const key = await keyReader();
      return [200, { ok: true, key: { hasKey: !!key.key, source: key.source, hint: maskKey(key.key) } }];
    }
    if (p === '/api/controller/reset' && method === 'POST') {
      // 写通道会卡死，USB 重枚举是现场最有效的恢复手段（等于拔插一次）
      const out = await resetUsbDevice();
      record('app', '手柄 USB 重枚举：' + out);
      return [200, { ok: true, output: out }];
    }
    if (p === '/api/clientlog' && method === 'POST') {
      const body = await jsonBody(req);
      const level = ['ui', 'asr', 'send', 'warn', 'error'].includes(body.level) ? body.level : 'ui';
      record(level, '页面 · ' + String(body.text ?? '').slice(0, 300));
      return [200, { ok: true }];
    }
    if (p === '/api/asr' && method === 'POST') return [200, { ok: true, ...(await handleAsr(await jsonBody(req))) }];
    if (p === '/api/asr/raw' && method === 'POST') {
      const wav = await rawBody(req);
      const key = await keyReader();
      const result = await asrFn(wav, { apiKey: key.key, config: state.config });
      record('asr', `原始 WAV 识别：${result.text}`);
      return [200, { ok: true, ...result }];
    }
    if (p === '/api/route' && method === 'POST') {
      const body = await jsonBody(req);
      return [200, { ok: true, ...routeByPrefix(state.config, String(body.text ?? '')) }];
    }
    if (p === '/api/deliver' && method === 'POST') return [200, { ok: true, ...(await handleDeliver(await jsonBody(req))) }];
    const activate = p.match(/^\/api\/agents\/([^/]+)\/activate$/);
    if (activate && method === 'POST') return [200, await handleActivate(decodeURIComponent(activate[1]))];
    return null;
  }

  async function serveStatic(res, pathname) {
    const rel = pathname === '/' ? 'index.html' : decodeURIComponent(pathname).replace(/^\/+/, '');
    const root = PUBLIC_DIR;
    const target = path.resolve(root, rel);
    if (!target.startsWith(root + path.sep)) return false;
    try {
      const data = await readFile(target);
      res.writeHead(200, { 'Content-Type': MIME[path.extname(target)] ?? 'application/octet-stream', 'Cache-Control': 'no-store' });
      res.end(data);
      return true;
    } catch {
      return false;
    }
  }

  const server = http.createServer(async (req, res) => {
    const url = req.url ?? '/';
    try {
      const handled = await route(req.method ?? 'GET', url, req, res);
      if (handled) {
        const [status, payload] = handled;
        res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
        res.end(JSON.stringify(payload));
        return;
      }
      if ((req.method === 'GET' || req.method === 'HEAD') && (await serveStatic(res, new URL(url, 'http://127.0.0.1').pathname))) return;
      res.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ ok: false, error: { message: '没有这个接口或文件' } }));
    } catch (err) {
      const raw = err.status
        ?? (err instanceof AsrError ? (['auth', 'audio', 'request', 'config'].includes(err.kind) ? 400 : 502) : null)
        ?? (err instanceof DeliverError ? 409 : 500);
      const status = Number.isInteger(raw) && raw >= 200 && raw <= 599 ? raw : 500;
      const payload = { ok: false, error: { message: err.message, kind: err.kind || err.step || '', detail: err.detail || err.stderr || '' } };
      if (status >= 500) record('error', `${req.method} ${url} → ${err.message}`);
      else record('warn', `${req.method} ${url} → ${err.message}`);
      res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(payload));
    }
  });

  return { server, record, reload, persist, state, log, configFile };
}

function findPort(start, attempts = 20) {
  return new Promise((resolve, reject) => {
    let port = start;
    const tryPort = () => {
      if (port >= start + attempts) { reject(new Error('找不到空闲端口')); return; }
      const probe = http.createServer();
      probe.once('error', (err) => {
        if (err.code === 'EADDRINUSE') { port += 1; tryBind(); return; }
        reject(err);
      });
      const tryBind = () => probe.listen(port, '127.0.0.1', () => probe.close(() => resolve(port)));
      tryBind();
    };
    tryPort();
  });
}

export async function startServer({ port = Number(process.env.PORT) || 8899, host = '127.0.0.1' } = {}) {
  const app = createApp();
  await app.reload();
  app.record('app', `服务启动（配置：${app.configFile}）`);
  const actual = port === 0 ? 0 : await findPort(port);
  await new Promise((resolve, reject) => {
    app.server.once('error', reject);
    app.server.listen(actual, host, resolve);
  });
  const bound = app.server.address().port;
  return { ...app, port: bound, url: `http://${host}:${bound}` };
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  const started = await startServer();
  process.stdout.write(`VOICE_CODING_READY ${started.url}\n`);
  process.stdout.write(`配置：${started.configFile}\n`);
  const shutdown = () => { started.record('app', '服务退出'); started.server.close(() => process.exit(0)); setTimeout(() => process.exit(0), 500); };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}
