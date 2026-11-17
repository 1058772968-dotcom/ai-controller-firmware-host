// 配置：默认 Agent、校验、原子写盘。默认值写在代码里，用户配置放 ~/.voice-coding/config.json。
import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
import { homedir } from 'node:os';
import path from 'node:path';

export const CONFIG_VERSION = 1;
export const SEND_KEYS = ['return', 'cmd-return', 'none'];

export function homeDir() {
  return process.env.VOICE_CODING_HOME || path.join(homedir(), '.voice-coding');
}
export function configPath() {
  return path.join(homeDir(), 'config.json');
}

// 默认 Agent 只放「常见的代码 Agent + 当前 Mac 自带的终端」。数值都是可以在界面里改的。
export function defaultAgents() {
  return [
    {
      id: 'claude-code',
      name: 'Claude Code',
      aliases: ['claude', '克劳德', 'cc'],
      app: { bundleId: 'com.apple.Terminal', name: '终端' },
      launch: { command: 'claude', workdir: '', newWindow: true },
      send: 'return',
      enabled: true,
      note: '在「终端」新开窗口跑 claude，然后把话贴进去回车',
    },
    {
      id: 'codex',
      name: 'Codex',
      aliases: ['codex', '扣得克斯'],
      app: { bundleId: 'com.apple.Terminal', name: '终端' },
      launch: { command: 'codex', workdir: '', newWindow: true },
      send: 'return',
      enabled: true,
      note: '在「终端」新开窗口跑 codex',
    },
    {
      id: 'cursor',
      name: 'Cursor',
      aliases: ['cursor', '光标'],
      app: { bundleId: 'com.todesktop.230313mzl4w4u92', name: 'Cursor' },
      launch: { command: '', workdir: '', newWindow: false },
      send: 'return',
      enabled: true,
      note: '焦点要落在 Cursor 的 AI 输入框里，否则只别自动回车',
    },
    {
      id: 'vscode',
      name: 'VS Code',
      aliases: ['vscode', 'vs code', '代码'],
      app: { bundleId: 'com.microsoft.VSCode', name: 'Visual Studio Code' },
      launch: { command: '', workdir: '', newWindow: false },
      send: 'none',
      enabled: true,
      note: '默认只填入不发送，免得把话打进编辑器正文',
    },
    {
      id: 'frontmost',
      name: '跟着前台走',
      aliases: ['前台', '当前'],
      app: {},
      launch: { command: '', workdir: '', newWindow: false },
      send: 'none',
      enabled: true,
      note: '不切应用，直接贴到当前最前面的窗口；适合任何没配过的 Agent',
    },
  ];
}

export function defaultConfig() {
  return {
    version: CONFIG_VERSION,
    asr: {
      // 百炼 MaaS（cn-beijing）OpenAI 兼容域名之外，qwen3-asr-flash 走原生多模态接口
      // 默认用百炼的公开域名；自己 workspace 的专属端点用 VOICE_CODING_ASR_BASE 或 ~/.voice-coding/config.json 覆盖
      baseUrl: process.env.VOICE_CODING_ASR_BASE || 'https://dashscope.aliyuncs.com',
      model: 'qwen3-asr-flash',
      language: 'zh',
      hotwords: 'Claude Code, Codex, Cursor, Git, commit, 提交, 回滚, 重构, 单元测试, 接口, 函数',
      timeoutMs: 45000,
    },
    audio: {
      maxSeconds: 90,
      minSeconds: 0.35,
      sampleRate: 16000,
      // 只认板子上的麦克风：没插板子就不录，不退回电脑 / 手机麦克风
      requireBoardMic: true,
      boardMicNames: ['Held-key microphone', 'AI KEY Mic POC'],
    },
    behavior: {
      autoSend: false, // 默认只填入，回车要人来按
      prefixRouting: true, // 「Claude，帮我改一下」→ 自动路由到 Claude Code 并去掉前缀
      pttKey: 'v', // 按住说话的键盘键，配合手柄 V
    },
    deliver: { dryRun: false, settleMs: 260, pasteDelayMs: 160 },
    ui: { lastAgentId: 'claude-code' },
    agents: defaultAgents(),
  };
}

const isPlainObject = (v) => !!v && typeof v === 'object' && !Array.isArray(v);
const str = (v, fallback = '') => (typeof v === 'string' ? v.trim() : fallback);
const bool = (v, fallback) => (typeof v === 'boolean' ? v : fallback);
const num = (v, fallback, { min = -Infinity, max = Infinity } = {}) =>
  Number.isFinite(v) ? Math.min(max, Math.max(min, v)) : fallback;

function normalizeAgent(raw, index) {
  const issues = [];
  if (!isPlainObject(raw)) return { agent: null, issues: [{ path: `agents[${index}]`, message: '不是对象' }] };
  const name = str(raw.name);
  let id = str(raw.id).toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '');
  if (!id) id = `agent-${index + 1}`;
  if (!name) issues.push({ path: `agents[${index}].name`, message: '缺名称' });
  const app = isPlainObject(raw.app) ? raw.app : {};
  const bundleId = str(app.bundleId);
  const appName = str(app.name);
  // 两个都空不是错：表示「跟着前台走」，不切应用

  const launch = isPlainObject(raw.launch) ? raw.launch : {};
  const send = SEND_KEYS.includes(raw.send) ? raw.send : 'return';
  const aliases = Array.isArray(raw.aliases)
    ? raw.aliases.map((a) => str(a)).filter((a) => a && a !== name)
    : [];
  return {
    agent: {
      id,
      name: name || id,
      aliases: [...new Set(aliases)],
      app: { bundleId, name: appName },
      launch: {
        command: str(launch.command),
        workdir: str(launch.workdir),
        newWindow: bool(launch.newWindow, false),
      },
      send,
      enabled: bool(raw.enabled, true),
      note: str(raw.note),
    },
    issues,
  };
}

// 任何读盘/接口输入都先过这里：非法项丢掉并回报，不让坏配置拖垮服务。
export function normalizeConfig(raw) {
  const base = defaultConfig();
  if (!isPlainObject(raw)) return { config: base, issues: [{ path: '', message: '配置不是对象，已用默认值' }] };
  const issues = [];
  const cfg = { ...base };
  cfg.version = CONFIG_VERSION;
  for (const section of ['asr', 'audio', 'behavior', 'deliver', 'ui']) {
    if (isPlainObject(raw[section])) cfg[section] = { ...base[section], ...raw[section] };
    else if (raw[section] !== undefined) issues.push({ path: section, message: '不是对象，已忽略' });
  }
  cfg.asr.baseUrl = str(cfg.asr.baseUrl, base.asr.baseUrl).replace(/\/+$/, '') || base.asr.baseUrl;
  cfg.asr.model = str(cfg.asr.model, base.asr.model) || base.asr.model;
  cfg.asr.language = str(cfg.asr.language, base.asr.language);
  cfg.asr.hotwords = str(cfg.asr.hotwords);
  cfg.asr.timeoutMs = num(cfg.asr.timeoutMs, base.asr.timeoutMs, { min: 3000, max: 180000 });
  cfg.audio.sampleRate = num(cfg.audio.sampleRate, base.audio.sampleRate, { min: 8000, max: 48000 });
  cfg.audio.maxSeconds = num(cfg.audio.maxSeconds, base.audio.maxSeconds, { min: 3, max: 600 });
  cfg.audio.minSeconds = num(cfg.audio.minSeconds, base.audio.minSeconds, { min: 0, max: 10 });
  cfg.audio.requireBoardMic = bool(cfg.audio.requireBoardMic, base.audio.requireBoardMic);
  const rawNames = Array.isArray(cfg.audio.boardMicNames) ? cfg.audio.boardMicNames : null;
  const names = (rawNames ?? base.audio.boardMicNames).map((n) => str(n)).filter(Boolean);
  cfg.audio.boardMicNames = names.length ? names : base.audio.boardMicNames;
  cfg.behavior.autoSend = bool(cfg.behavior.autoSend, base.behavior.autoSend);
  cfg.behavior.prefixRouting = bool(cfg.behavior.prefixRouting, base.behavior.prefixRouting);
  cfg.behavior.pttKey = (str(cfg.behavior.pttKey, base.behavior.pttKey) || 'v').toLowerCase();
  cfg.deliver.dryRun = bool(cfg.deliver.dryRun, base.deliver.dryRun);
  cfg.deliver.settleMs = num(cfg.deliver.settleMs, base.deliver.settleMs, { min: 0, max: 3000 });
  cfg.deliver.pasteDelayMs = num(cfg.deliver.pasteDelayMs, base.deliver.pasteDelayMs, { min: 0, max: 3000 });
  cfg.ui.lastAgentId = str(cfg.ui.lastAgentId, base.ui.lastAgentId);

  const list = Array.isArray(raw.agents) ? raw.agents : null;
  if (!list) {
    if (raw.agents !== undefined) issues.push({ path: 'agents', message: '不是数组，已用默认 Agent' });
    cfg.agents = base.agents;
  } else {
    const out = [];
    const seen = new Set();
    list.forEach((item, i) => {
      const { agent, issues: sub } = normalizeAgent(item, i);
      issues.push(...sub);
      if (!agent) return;
      let id = agent.id;
      let bump = 2;
      while (seen.has(id)) id = `${agent.id}-${bump++}`;
      seen.add(id);
      out.push({ ...agent, id });
    });
    cfg.agents = out;
  }
  return { config: cfg, issues };
}

export function agentById(config, id) {
  const key = str(id);
  return config.agents.find((a) => a.id === key) ?? null;
}

// 语音前缀路由：只有别名后面跟着分隔符才算，避免「终端里跑一下」被吃掉「终端里」。
const SEPARATORS = new Set(['：', ':', '，', ',', '、', ' ', '\u3000', '。']);

export function routeByPrefix(config, text) {
  const source = typeof text === 'string' ? text : '';
  if (!config?.behavior?.prefixRouting) return { agentId: null, text: source, alias: '' };
  const entries = [];
  for (const agent of config.agents) {
    if (!agent.enabled) continue;
    for (const alias of [agent.name, ...agent.aliases]) {
      const a = alias.trim();
      if (a) entries.push({ agentId: agent.id, alias: a });
    }
  }
  entries.sort((x, y) => y.alias.length - x.alias.length);
  const trimmed = source.replace(/^\s+/, '');
  const lower = trimmed.toLowerCase();
  for (const { agentId, alias } of entries) {
    const lowerAlias = alias.toLowerCase();
    if (!lower.startsWith(lowerAlias)) continue;
    const rest = trimmed.slice(alias.length);
    if (!rest) continue;
    if (!SEPARATORS.has(rest[0])) continue;
    const body = rest.replace(/^[\s\u3000]+/, '').replace(/^[：:，,、。]+/, '').trim();
    if (!body) continue;
    return { agentId, text: body, alias };
  }
  return { agentId: null, text: source, alias: '' };
}

export async function loadConfig(file = configPath()) {
  try {
    const raw = JSON.parse(await readFile(file, 'utf8'));
    const { config, issues } = normalizeConfig(raw);
    return { config, issues, existed: true };
  } catch (err) {
    const missing = err.code === 'ENOENT';
    const { config } = normalizeConfig(null);
    return { config, issues: missing ? [] : [{ path: '', message: `配置读取失败：${err.message}` }], existed: false };
  }
}

export async function saveConfig(config, file = configPath()) {
  const { config: clean, issues } = normalizeConfig(config);
  const dir = path.dirname(file);
  await mkdir(dir, { recursive: true });
  const tmp = path.join(dir, `.config.${process.pid}.json`);
  await writeFile(tmp, JSON.stringify(clean, null, 2) + '\n', { mode: 0o600 });
  await rename(tmp, file);
  return { config: clean, issues };
}
