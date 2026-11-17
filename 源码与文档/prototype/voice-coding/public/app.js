// 界面逻辑：选 Agent → 说话 → 转文字 → 填入 / 发送。所有重活（ASR、动键盘）都在本机服务里。
import { Recorder, listMics } from './recorder.js';
import { describeMics, isBoardMic, resolveStartTarget, DEFAULT_BOARD_MIC_NAMES } from './mic-match.js';
import { mapControllerKey } from './controller-keys.js';
import { ControllerSession } from './controller.js';

const $ = (id) => document.getElementById(id);

const state = {
  config: null,
  key: null,
  selected: '',
  transcript: '',
  lastUtterance: null,
  recorder: null,
  recording: false,
  autoMode: false,
  busy: false,
  logSeq: 0,
  micView: { inputs: [], board: [], others: [], labelsVisible: false, state: 'unauthorized', picked: null },
  controller: null,
  controllerOwner: 'POINTER',
};

const SEND_LABEL = { return: '回车发送', 'cmd-return': '⌘回车', none: '只填入' };

async function api(path, { method = 'GET', body } = {}) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    const err = new Error((data.error && data.error.message) || ('HTTP ' + res.status));
    err.kind = data.error && data.error.kind;
    err.detail = data.error && data.error.detail;
    throw err;
  }
  return data;
}

function toast(text, kind) {
  const el = $('toast');
  el.textContent = text;
  el.className = 'toast' + (kind ? ' ' + kind : '');
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 5200);
}

function phase(text) { $('phase').textContent = text; }

function pill(id, text, kind) {
  const el = $(id);
  el.textContent = text;
  el.className = 'pill' + (kind ? ' ' + kind : '');
}

function selectedAgent() {
  return state.agents.find((a) => a.id === state.selected) || state.agents[0] || null;
}

function appLabel(agent) {
  if (!agent) return '';
  if (agent.launch && agent.launch.command && agent.launch.newWindow) return '终端 · ' + agent.launch.command;
  if (agent.app && (agent.app.name || agent.app.bundleId)) return agent.app.name || agent.app.bundleId;
  return '跟着前台走';
}

function renderAgents() {
  const box = $('agent-list');
  box.textContent = '';
  for (const agent of state.agents) {
    const card = document.createElement('button');
    card.className = 'agent-card' + (agent.id === state.selected ? ' sel' : '');
    card.type = 'button';
    const name = document.createElement('div');
    name.className = 'n';
    const n = document.createElement('span');
    n.textContent = agent.name;
    const send = document.createElement('span');
    send.className = 'send';
    send.textContent = SEND_LABEL[agent.send] || agent.send;
    name.append(n, send);
    const sub = document.createElement('div');
    sub.className = 's';
    sub.textContent = appLabel(agent);
    card.append(name, sub);
    card.onclick = () => selectAgent(agent.id, true);
    box.append(card);
  }
  const agent = selectedAgent();
  $('target-name').textContent = agent ? agent.name : '—';
  $('target-note').textContent = agent ? (agent.note || appLabel(agent)) : '';
  $('chk-autosend').checked = !!(state.config && state.config.behavior.autoSend);
}

function selectAgent(id, persist) {
  if (!state.agents.some((a) => a.id === id)) return;
  state.selected = id;
  renderAgents();
  if (persist && state.config) {
    api('/api/settings', { method: 'PUT', body: { ui: { lastAgentId: id } } }).catch(() => {});
  }
}

function renderPills() {
  if (state.key) {
    pill('pill-key', '密钥 ' + (state.key.hasKey ? (state.key.source === 'keychain' ? '钥匙串' : '环境变量') : '缺失'), state.key.hasKey ? 'ok' : 'bad');
  }
  const view = state.micView;
  if (!boardOnly()) {
    const any = view.inputs[0];
    pill('pill-mic', '麦克风 ' + (any ? shortLabel(any.label) : '未选'), any ? '' : 'warn');
  } else if (view.state === 'ready') {
    pill('pill-mic', '麦克风 板载', 'ok');
  } else if (view.state === 'unauthorized') {
    pill('pill-mic', '麦克风 待授权', 'warn');
  } else {
    pill('pill-mic', '麦克风 板子未接', 'bad');
  }
  if (state.config) {
    pill('pill-mode', state.config.deliver.dryRun ? '投递 演练模式' : '投递 真键盘', state.config.deliver.dryRun ? 'warn' : '');
  }
}

function shortLabel(text) {
  const t = String(text || '').replace(/^默认 - /, '').replace(/（.*?）/g, '');
  return t.length > 12 ? t.slice(0, 12) + '…' : t;
}

function base64(u8) {
  let out = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < u8.length; i += CHUNK) {
    out += String.fromCharCode.apply(null, u8.subarray(i, i + CHUNK));
  }
  return btoa(out);
}

function setTranscript(text, note) {
  state.transcript = text || '';
  $('transcript').value = state.transcript;
  const has = !!state.transcript.trim();
  $('btn-send').disabled = !has;
  $('btn-fill').disabled = !has;
  $('btn-clear').disabled = !has;
  $('btn-retry').disabled = !state.lastUtterance;
  if (note) phase(note);
}

async function loadState() {
  const data = await api('/api/state');
  state.config = data.config;
  state.agents = data.config.agents;
  state.key = data.key;
  $('ver').textContent = 'v' + data.version;
  state.selected = data.config.ui.lastAgentId || (state.agents[0] && state.agents[0].id) || '';
  if (!state.agents.some((a) => a.id === state.selected)) state.selected = state.agents[0] ? state.agents[0].id : '';
  renderAgents();
  renderPills();
  fillSettingsInputs();
}

// ---------- 设置面板 ----------
function fillSettingsInputs() {
  const c = state.config;
  if (!c) return;
  $('in-model').value = c.asr.model;
  $('in-language').value = c.asr.language;
  $('in-hotwords').value = c.asr.hotwords;
  $('in-board-mics').value = (c.audio.boardMicNames || []).join('，');
  $('chk-require-board').checked = c.audio.requireBoardMic !== false;
  $('in-settle').value = c.deliver.settleMs;
  $('in-paste-delay').value = c.deliver.pasteDelayMs;
  $('chk-prefix').checked = !!c.behavior.prefixRouting;
  $('chk-dryrun').checked = !!c.deliver.dryRun;
  $('chk-autosend').checked = !!c.behavior.autoSend;
  $('key-hint').textContent = state.key && state.key.hasKey ? state.key.hint + '（' + state.key.source + '）' : '没有';
  $('rng-threshold').value = String(Math.round((Number(localStorage.getItem('vc.threshold')) || 0.012) * 1000));
  $('threshold-val').textContent = (Number($('rng-threshold').value) / 1000).toFixed(3);
  renderAgentEditor();
}

function renderAgentEditor() {
  const box = $('agent-editor');
  box.textContent = '';
  state.agents.forEach((agent, index) => {
    const row = document.createElement('div');
    row.className = 'agent-row';
    row.dataset.index = String(index);
    const field = (label, key, value, full) => {
      const lab = document.createElement('label');
      if (full) lab.className = 'full';
      lab.textContent = label;
      const input = document.createElement('input');
      input.dataset.field = key;
      input.value = value == null ? '' : value;
      lab.append(input);
      return lab;
    };
    row.append(field('名称', 'name', agent.name));
    row.append(field('别名（逗号分隔）', 'aliases', (agent.aliases || []).join('，')));
    row.append(field('Bundle ID', 'bundleId', agent.app.bundleId));
    row.append(field('应用名（没有 Bundle ID 时用）', 'appName', agent.app.name));
    row.append(field('终端命令（填了就开新窗口跑）', 'command', agent.launch.command));
    row.append(field('工作目录（可空）', 'workdir', agent.launch.workdir));
    const sendLab = document.createElement('label');
    sendLab.textContent = '发送方式';
    const sel = document.createElement('select');
    sel.dataset.field = 'send';
    for (const [value, label] of Object.entries(SEND_LABEL)) {
      const opt = document.createElement('option');
      opt.value = value;
      opt.textContent = label;
      if (agent.send === value) opt.selected = true;
      sel.append(opt);
    }
    sendLab.append(sel);
    row.append(sendLab);
    const tools = document.createElement('div');
    tools.className = 'tools';
    const en = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.dataset.field = 'enabled';
    cb.checked = agent.enabled !== false;
    en.append(cb, document.createTextNode('启用'));
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'ghost';
    del.textContent = '删除';
    del.onclick = () => { state.agents.splice(index, 1); renderAgentEditor(); };
    tools.append(en, del);
    row.append(tools);
    box.append(row);
  });
}

function readAgentEditor() {
  const rows = [...$('agent-editor').querySelectorAll('.agent-row')];
  return rows.map((row, index) => {
    const get = (name) => {
      const el = row.querySelector('[data-field="' + name + '"]');
      if (!el) return '';
      if (el.type === 'checkbox') return el.checked;
      return el.value;
    };
    const base = state.agents[index] || { app: {}, launch: {} };
    return {
      id: base.id,
      name: get('name'),
      aliases: String(get('aliases')).split(/[,，、]/).map((s) => s.trim()).filter(Boolean),
      app: { bundleId: get('bundleId'), name: get('appName') },
      launch: { command: get('command'), workdir: get('workdir'), newWindow: !!String(get('command')).trim() },
      send: get('send') || 'return',
      enabled: !!get('enabled'),
      note: base.note || '',
    };
  });
}

async function saveSettings() {
  const body = {
    asr: { model: $('in-model').value.trim(), language: $('in-language').value.trim(), hotwords: $('in-hotwords').value.trim() },
    audio: {
      requireBoardMic: $('chk-require-board').checked,
      boardMicNames: $('in-board-mics').value.split(/[,，、]/).map((s) => s.trim()).filter(Boolean),
    },
    behavior: { prefixRouting: $('chk-prefix').checked, autoSend: $('chk-autosend').checked },
    deliver: { dryRun: $('chk-dryrun').checked, settleMs: Number($('in-settle').value), pasteDelayMs: Number($('in-paste-delay').value) },
  };
  const data = await api('/api/settings', { method: 'PUT', body });
  state.config = data.config;
  state.agents = data.config.agents;
  renderPills();
  await refreshMics({ requestPermission: $('chk-require-board').checked });
  toast('设置已保存', 'ok');
}

async function saveAgents() {
  const agents = readAgentEditor();
  const data = await api('/api/agents', { method: 'PUT', body: { agents } });
  state.agents = data.agents;
  state.config.agents = data.agents;
  if (!state.agents.some((a) => a.id === state.selected)) state.selected = state.agents[0] ? state.agents[0].id : '';
  renderAgents();
  renderAgentEditor();
  toast('Agent 已保存（' + data.agents.length + ' 个）', 'ok');
}

// ---------- 麦克风 ----------
function boardNames() {
  const names = state.config && state.config.audio && state.config.audio.boardMicNames;
  return Array.isArray(names) && names.length ? names : DEFAULT_BOARD_MIC_NAMES;
}

// 默认只认板子上的麦克风；只有显式关掉才允许用电脑 / 手机麦克风
function boardOnly() {
  return !state.config || state.config.audio.requireBoardMic !== false;
}

async function refreshMics({ requestPermission = false } = {}) {
  let all = [];
  try {
    all = await listMics({ requestPermission });
  } catch (err) {
    toast('读不到麦克风：' + (err.name === 'NotAllowedError' ? '麦克风权限被拒绝了，允许后再点「重新读取设备」' : err.message), 'bad');
  }
  state.micView = describeMics(all, { names: boardNames(), preferredDeviceId: state.micId });
  const view = state.micView;

  if (boardOnly()) {
    // 记住的 deviceId 失效（换口、重插）时，按设备名重新挑一个板载麦
    if (!view.board.some((d) => d.deviceId === state.micId)) state.micId = view.picked ? view.picked.deviceId : '';
  }

  const sel = $('sel-mic');
  sel.textContent = '';
  const options = boardOnly() ? view.board : view.inputs;
  if (!options.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = boardOnly() ? '（没有找到板载麦克风）' : '（没有输入设备）';
    sel.append(opt);
  }
  for (const mic of options) {
    const opt = document.createElement('option');
    opt.value = mic.deviceId;
    opt.textContent = (isBoardMic(mic.label, boardNames()) ? '★ ' : '') + (mic.label || '未命名输入设备');
    if (mic.deviceId === state.micId) opt.selected = true;
    sel.append(opt);
  }

  if (boardOnly()) {
    $('mic-hint').textContent = view.state === 'ready'
      ? '用的是板子上的麦克风：联调档固件按住手柄 V 才会放行声音，闸门关着时录到的是全零。'
      : view.state === 'unauthorized'
        ? '还没拿到设备名：点「重新读取设备」允许一次麦克风，才能认出板载麦克风。'
        : '只认板子上的麦克风（' + boardNames().join(' / ') + '）。现在没看到它：把 E24 用 USB 插上、烧带音频的联调档，再点「重新读取设备」。电脑和手机的麦克风不会被使用。';
  } else {
    $('mic-hint').textContent = '已关掉「只允许板载麦克风」：可以选电脑 / 手机麦克风，说话内容会送云端识别。';
  }
  renderPills();
}

// ---------- 手柄 ----------
function controllerPill(text, kind) {
  pill('pill-controller', text, kind);
}

// 授权过一次以后，页面重新打开可以直接拿回设备，不用再点选择器
async function autoConnectController() {
  const hid = navigator.hid;
  if (!hid || !hid.getDevices) return false;
  try {
    const list = await hid.getDevices();
    const dev = list.find((d) => d.vendorId === 0xcafe && d.productId === 0x4031);
    if (!dev) return false;
    await connectController(dev);
    return true;
  } catch {
    return false;
  }
}

async function connectController(existingDevice) {
  if (!(await ControllerSession.supported())) {
    toast('这个浏览器没有 WebHID：用桌面版 Chrome / Edge 打开', 'bad');
    return;
  }
  controllerPill('手柄 连接中…', 'warn');
  try {
    const session = new ControllerSession({
      onKey: (name, down) => handleControllerKey(name, down),
      onState: (s) => handleControllerState(s),
      onLog: (text) => pushLog('手柄 · ' + text),
      onStatus: (r) => {
        state.lastControllerFrame = r;
        if (r.type === 8) state.lastRecordAck = (r.value === 0 ? 'OK' : r.value === 4 ? 'HELD' : 'ERR');
        state.frameCount = (state.frameCount || 0) + 1;
        if (state.frameCount % 10 === 0) {
          setKeyLive('收到 ' + state.frameCount + ' 帧 · 按键 ' + (r.buttons || 0), false);
        }
      },
    });
    await session.connect({ device: existingDevice });
    state.controller = session;
    $('connect-banner').hidden = true;
    $('btn-controller-connect').hidden = true;
    $('btn-controller-claim').hidden = false;
    $('btn-hid-probe').hidden = false;
    $('btn-controller-disconnect').hidden = false;
    $('controller-hint').textContent = '已连接，正在接管（固件的麦克风闸门要求主机拿 HOST）…';
    pushLog('手柄 · 已连接，准备接管');
    // 麦闸门 ak_mic_permitted() 要求 owner==HOST，所以必须接管，否则录到的是全零
    try {
      await session.claim();
      $('controller-hint').textContent = '已接管：按住 V 录音、松开结束；L 发送、R 清空。接管期间手柄暂时当不了鼠标。';
    } catch (err) {
      pushLog('手柄 · 接管失败：' + err.message, 'error');
      $('controller-hint').textContent = '按键能收到，但接管没成功：' + err.message
        + '。接管不了麦克风就不会开（固件要求 HOST），先把这条日志发我。';
      toast('手柄接管失败：' + err.message, 'bad');
    }
  } catch (err) {
    state.controller = null;
    controllerPill('手柄 连接失败', 'bad');
    const tips = String(err && err.message || err);
    pushLog('手柄 · 连接失败：' + tips, 'error');
    $('controller-hint').textContent = tips.includes('TCC') || tips.includes('denied')
      ? '打不开设备：系统设置 → 隐私与安全性 → 输入监控，把 Chrome 勾上，然后重连'
      : '连接失败：' + tips;
    toast('手柄连接失败：' + tips, 'bad');
  }
}

function handleControllerState(s) {
  if (!s) return;
  if (s.text) pushLog('手柄 · ' + s.text);
  if (s.phase === 'listening') {
    state.controllerOwner = 'POINTER';
    controllerPill('手柄 按键可用', 'ok');
  } else if (s.phase === 'host') {
    state.controllerOwner = 'HOST';
    controllerPill('手柄 已接管', 'ok');
    $('btn-controller-release').hidden = false;
    $('btn-controller-claim').hidden = true;
    $('controller-hint').textContent = '已接管：四键归语音，手柄暂时当不了鼠标。点「交还指针」恢复。';
  } else if (s.phase === 'pointer') {
    state.controllerOwner = 'POINTER';
    controllerPill('手柄 按键可用', 'ok');
    $('btn-controller-release').hidden = true;
    $('btn-controller-claim').hidden = false;
    $('controller-hint').textContent = '已交还指针：手柄恢复鼠标，按键仍然可读。';
  } else if (s.phase === 'error' || s.phase === 'lost') {
    state.controllerOwner = 'POINTER';
    controllerPill(s.phase === 'lost' ? '手柄 已断开' : '手柄 异常', 'bad');
    if (s.phase === 'lost') resetControllerUi();
  }
}

function resetControllerUi() {
  state.controller = null;
  state.controllerOwner = 'POINTER';
  $('connect-banner').hidden = false;
  setKeyLive('还没收到的按动', false);
  $('btn-controller-connect').hidden = false;
  $('btn-controller-claim').hidden = true;
  $('btn-controller-release').hidden = true;
  $('btn-controller-disconnect').hidden = true;
}

async function handleControllerKey(name, down) {
  const mapped = mapControllerKey(name, down, {
    recording: state.recording,
    hasTranscript: !!$('transcript').value.trim(),
  });
  setKeyLive(name + (down ? ' 按下' : ' 松开'), down);
  pushLog('手柄按键 ' + name + (down ? ' 按下' : ' 松开') + (mapped.reason ? '（' + mapped.reason + '）' : ''));
  if (mapped.action === 'record-start') {
    if (state.controller && state.controllerOwner !== 'HOST') {
      toast('手柄还没接管：固件要求主机拿 HOST 才放行麦克风，接管失败时按 V 只会录到全零', 'bad');
    }
    await startRecording('ptt');
  }
  else if (mapped.action === 'record-stop') await stopRecording();
  else if (mapped.action === 'send') await deliver('send');
  else if (mapped.action === 'clear') setTranscript('', '已清空');
}

async function testMic() {
  if (state.recording) { toast('正在录音，先松开', 'bad'); return; }
  const target = resolveStartTarget({ requireBoardMic: boardOnly(), micView: state.micView, micId: state.micId });
  if (!target.ok) { await refreshMics({ requestPermission: true }); toast('先让板载麦克风出现：点「重新读取设备」并允许麦克风', 'bad'); return; }
  const rec = ensureRecorder();
  rec.threshold = 0.004;
  phase('试音 4 秒：现在对着板子说话（或按住 V）');
  let peak = 0;
  rec.onLevel = (level) => { if (level > peak) peak = level; $('meter-fill').style.width = Math.min(100, Math.round(level * 400)) + '%'; };
  try {
    await rec.start({ deviceId: target.deviceId, mode: 'ptt', expectedNames: boardOnly() ? boardNames() : [] });
    await new Promise((r) => setTimeout(r, 4000));
    const utterance = await rec.stop();
    const raw = utterance ? peakOfPcm(utterance.pcm) : 0;
    if (raw >= 24) {
      phase('试音结果：有声音（峰值 ' + raw + '/32767）');
      toast('板载麦克风有声音，峰值 ' + raw + '。按住 V 就能录音。', 'ok');
    } else {
      phase('试音结果：全是零（峰值 ' + raw + '）');
      toast('4 秒里一个非零采样都没有：可能是麦克风闸门没开（固件要求按住 V），或选错了设备。', 'bad');
    }
    pushLog('试音：峰值 ' + raw + (raw >= 24 ? '（有声音）' : '（全零）'), raw >= 24 ? 'asr' : 'warn');
  } catch (err) {
    const where = (err && err.stack ? String(err.stack).split('\n').slice(0, 3).join(' ') : '');
    phase('试音失败：' + err.message);
    toast('试音失败：' + err.message, 'bad');
    pushLog('试音异常：' + err.message + ' | ' + where, 'error');
  } finally {
    rec.onLevel = (level) => {
      const pct = Math.min(100, Math.round((level / Math.max(0.02, thresholdValue() * 4)) * 100));
      $('meter-fill').style.width = pct + '%';
    };
  }
}

async function disconnectController() {
  clearTimeout(connectController.watchdog);
  const bridge = state.controller;
  resetControllerUi();
  controllerPill('手柄 未连接');
  $('controller-hint').textContent = '已断开。手柄回到普通鼠标模式。';
  if (bridge) await bridge.close();
  pushLog('手柄 · 已断开');
}

// ---------- 录音 ----------
function thresholdValue() {
  return Number($('rng-threshold').value) / 1000;
}

function ensureRecorder() {
  if (state.recorder) return state.recorder;
  state.recorder = new Recorder({
    threshold: thresholdValue(),
    onLevel: (level) => {
      const pct = Math.min(100, Math.round((level / Math.max(0.02, thresholdValue() * 4)) * 100));
      $('meter-fill').style.width = pct + '%';
    },
    onUtterance: (utterance) => {
      state.lastUtterance = utterance;
      const peak = peakOfPcm(utterance.pcm);
      if (peak < 24) {
        // 板子闸门关着时固件输出全零：这时候送 ASR 只会得到一句「没识别出内容」
        const held = state.lastRecordAck === 'HELD';
        phase(held
          ? '固件没确认「V 按住」：RECORD 回了 HELD，这一段是静音'
          : '录到的是全零：闸门没开。确认已接管，并按住 V 再说话');
        toast(held
          ? '固件回 HELD：它认为 V 没被按住。按住 V 再按一次说话（别在刚按下就松手），整段要一直按着。'
          : '全零录音，没有送识别。确认手柄已接管（右上角「已接管」），并按住板子上的 V 说话。', 'bad');
        return;
      }
      transcribe(utterance);
    },
  });
  return state.recorder;
}

function peakOfPcm(pcm) {
  let peak = 0;
  for (let i = 0; i + 1 < pcm.length; i += 2) {
    const v = pcm[i] | (pcm[i + 1] << 8);
    const abs = v & 0x8000 ? 65536 - v : v;
    if (abs > peak) peak = abs;
  }
  return peak;
}

async function startRecording(mode) {
  if (state.recording) return;
  // 没板载麦克风就先去要一次权限 / 重新枚举；还是没有就拒绝录音，绝不退回电脑麦克风
  if (boardOnly() && !state.micView.board.length) await refreshMics({ requestPermission: true });
  const target = resolveStartTarget({ requireBoardMic: boardOnly(), micView: state.micView, micId: state.micId });
  if (!target.ok) {
    const why = target.reason === 'unauthorized'
      ? '还没允许麦克风：点一下「重新读取设备」并在弹窗里点允许'
      : '没找到板子上的麦克风（' + boardNames().join(' / ') + '）：USB 插上 E24、烧带音频的联调档，再点「重新读取设备」';
    toast(why, 'bad');
    phase('没有板载麦克风，不录音');
    return;
  }
  const deviceId = target.deviceId || undefined;
  try {
    const rec = ensureRecorder();
    rec.threshold = thresholdValue();
    // 固件只认「V 按住 + HOST + 已请求录音」：先请求录音，闸门才开
    if (state.controller && state.controllerOwner === 'HOST') await state.controller.record(true);
    const info = await rec.start({
      deviceId,
      mode,
      expectedNames: boardOnly() ? boardNames() : [],
    });
    state.recording = true;
    $('ptt').classList.add('rec');
    $('ptt').querySelector('.ptt-main').textContent = mode === 'auto' ? '正在听' : '松开发送';
    pill('pill-mic', '麦克风 ' + (isBoardMic(info.label, boardNames()) ? '板载 · 在录' : shortLabel(info.label)), 'ok');
    phase(mode === 'auto' ? '自动监听中：说话就自动切段' : '录音中…松开就识别');
  } catch (err) {
    state.recording = false;
    if (state.controller) await state.controller.record(false).catch(() => {});
    const tips = err.code === 'BOARD_MIC_MISMATCH'
      ? err.message + '（只允许板载麦克风）'
      : err.name === 'NotAllowedError'
        ? '麦克风权限被拒绝了：点地址栏左边的图标允许麦克风'
        : err.name === 'NotFoundError' || err.name === 'OverconstrainedError'
          ? '这块麦克风现在打不开：板子可能被拔了，重新读取设备再试'
          : err.message;
    toast(tips, 'bad');
    phase('录音没开起来：' + tips);
  }
}

async function stopRecording() {
  if (!state.recording || !state.recorder) return;
  state.recording = false;
  if (state.controller) await state.controller.record(false).catch(() => {});
  $('ptt').classList.remove('rec');
  $('ptt').querySelector('.ptt-main').textContent = '按住说话';
  const utterance = await state.recorder.stop();
  if (!utterance) { phase('这段太短，没送识别'); return; }
  if (state.autoMode) {
    setTimeout(() => { if (state.autoMode && !state.recording) startRecording('auto'); }, 120);
  }
}

async function transcribe(utterance) {
  // 自动监听时前后两段可能挨得很近：忙就排一个，不要整段丢掉
  if (state.busy) { state.pending = utterance; return; }
  state.busy = true;
  phase('识别中…（' + (utterance.durationMs / 1000).toFixed(1) + ' 秒录音）');
  try {
    const data = await api('/api/asr', {
      method: 'POST',
      body: { pcmBase64: base64(utterance.pcm), sampleRate: utterance.sampleRate },
    });
    let text = data.text;
    let note = '已识别（' + data.elapsedMs + ' ms）';
    if (state.config.behavior.prefixRouting) {
      const route = await api('/api/route', { method: 'POST', body: { text } });
      if (route.agentId) {
        const target = state.agents.find((a) => a.id === route.agentId);
        text = route.text;
        selectAgent(route.agentId, true);
        note = '已识别，按「' + route.alias + '」切到 ' + (target ? target.name : route.agentId);
      }
    }
    setTranscript(text, note);
    if (state.config.behavior.autoSend && text.trim()) await deliver('send');
  } catch (err) {
    phase('识别失败：' + err.message);
    toast('识别失败：' + err.message, 'bad');
  } finally {
    state.busy = false;
    if (state.pending) {
      const next = state.pending;
      state.pending = null;
      transcribe(next);
    }
  }
}

// ---------- 投递 ----------
async function deliver(mode) {
  const text = $('transcript').value;
  if (!text.trim()) return;
  const agent = selectedAgent();
  if (!agent) { toast('先选一个 Agent', 'bad'); return; }
  const send = mode === 'fill' ? 'none' : (agent.send === 'none' ? 'return' : agent.send);
  phase(mode === 'fill' ? '正在填入 ' + agent.name + '…' : '正在填入并发送…');
  try {
    const data = await api('/api/deliver', { method: 'POST', body: { agentId: agent.id, text, send } });
    const done = data.dryRun ? '演练完成（没动键盘）：' : '完成：';
    phase(done + data.steps.join(' → '));
    toast(done + data.steps.join(' → '), 'ok');
  } catch (err) {
    phase('投递失败：' + err.message);
    toast('投递失败：' + err.message, 'bad');
  }
}

// ---------- 日志 ----------
const LEVEL_LABEL = { asr: '识别', send: '投递', plan: '演练', cfg: '配置', app: '应用', error: '错误', warn: '注意', perm: '权限', key: '密钥' };

function appendLog(entry) {
  const box = $('log');
  const row = document.createElement('div');
  row.className = 'row ' + (entry.level || '');
  const t = document.createElement('span');
  t.className = 't';
  t.textContent = new Date(entry.ts).toLocaleTimeString('zh-CN', { hour12: false });
  const m = document.createElement('span');
  m.className = 'm';
  m.textContent = (LEVEL_LABEL[entry.level] || entry.level) + ' · ' + entry.text;
  row.append(t, m);
  box.append(row);
  while (box.childElementCount > 300) box.firstElementChild.remove();
  box.scrollTop = box.scrollHeight;
}

function pushLog(text, level = 'app') {
  appendLog({ ts: Date.now(), level, text });
  // 同一份也进服务端日志：页面关掉以后还能事后查「手柄到底连没连、按键有没有到」
  api('/api/clientlog', { method: 'POST', body: { level: level === 'error' ? 'error' : level === 'warn' ? 'warn' : 'ui', text } }).catch(() => {});
}

function setKeyLive(text, hit) {
  const el = $('key-live');
  if (!el) return;
  el.textContent = '按键：' + text;
  el.className = 'key-live' + (hit ? ' hit' : '');
  if (hit) {
    clearTimeout(setKeyLive.timer);
    setKeyLive.timer = setTimeout(() => { el.className = 'key-live'; }, 900);
  }
}

async function pollLog() {
  try {
    const data = await api('/api/log?since=' + state.logSeq);
    for (const entry of data.entries) {
      if (entry.seq > state.logSeq) { state.logSeq = entry.seq; appendLog(entry); }
    }
    state.logSeq = Math.max(state.logSeq, data.seq || 0);
  } catch {
    // 服务重启期间轮询失败是正常的，下一轮会补上
  }
}

// ---------- 事件 ----------
function isTyping(target) {
  const tag = target && target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}

function bind() {
  $('btn-settings').onclick = () => { $('drawer').hidden = false; fillSettingsInputs(); };
  $('btn-drawer-close').onclick = () => { $('drawer').hidden = true; };
  $('drawer').onclick = (e) => { if (e.target === $('drawer')) $('drawer').hidden = true; };

  $('btn-save-settings').onclick = () => saveSettings().catch((err) => toast('保存失败：' + err.message, 'bad'));
  $('btn-save-agents').onclick = () => saveAgents().catch((err) => toast('保存 Agent 失败：' + err.message, 'bad'));
  $('btn-add-agent').onclick = () => addAgent();
  $('btn-add-agent-2').onclick = () => addAgent();
  $('btn-perm').onclick = async () => {
    try {
      const data = await api('/api/permissions', { method: 'POST' });
      pill('pill-perm', data.automation ? '权限 可用' : '权限 不可用', data.automation ? 'ok' : 'bad');
      toast(data.automation ? '辅助功能/自动化可用（当前前台：' + data.frontmost + '）' : '自动化不可用：' + (data.detail || '未知'), data.automation ? 'ok' : 'bad');
    } catch (err) {
      toast('检查权限失败：' + err.message, 'bad');
    }
  };
  $('btn-save-key').onclick = async () => {
    const value = $('in-key').value.trim();
    if (!value) { toast('先粘贴密钥再保存', 'bad'); return; }
    try {
      const data = await api('/api/key', { method: 'POST', body: { key: value } });
      state.key = data.key;
      $('in-key').value = '';
      renderPills();
      fillSettingsInputs();
      toast('密钥已存进钥匙串', 'ok');
    } catch (err) {
      toast('存密钥失败：' + err.message, 'bad');
    }
  };
  $('btn-refresh-mic').onclick = () => refreshMics({ requestPermission: true });
  $('btn-connect-banner').onclick = () => connectController();
  $('btn-mic-test').onclick = () => testMic();
  $('btn-controller-reset').onclick = async () => {
    try {
      const data = await api('/api/controller/reset', { method: 'POST', body: {} });
      toast('手柄 USB 已重枚举：' + (data.output || 'ok') + '，页面会自动重连', 'ok');
      pushLog('手柄 · USB 重枚举：' + (data.output || 'ok'));
      setTimeout(() => location.reload(), 2500);
    } catch (err) {
      toast('重置失败：' + err.message, 'bad');
      pushLog('手柄 · 重置失败：' + err.message, 'error');
    }
  };
  $('btn-hid-probe').onclick = async () => {
    if (!state.controller) return;
    toast('正在试三种写通道…', 'ok');
    const results = await state.controller.probeWrites();
    pushLog('HID 自检：' + results.join('；'), results.some((r) => r.includes('✓')) ? 'asr' : 'warn');
    toast(results.join('；'), results.some((r) => r.includes('✓')) ? 'ok' : 'bad');
  };
  $('btn-controller-connect').onclick = () => connectController();
  $('btn-controller-disconnect').onclick = () => disconnectController();
  $('btn-controller-claim').onclick = async () => {
    if (!state.controller) return;
    controllerPill('手柄 接管中…', 'warn');
    try {
      await state.controller.claim();
    } catch (err) {
      controllerPill('手柄 按键可用', 'ok');
      $('controller-hint').textContent = '接管失败：' + err.message
        + '。如果一直不行，检查 系统设置 → 隐私与安全性 → 输入监控 里有没有 Chrome。';
      pushLog('手柄 · 接管失败：' + err.message, 'error');
    }
  };
  $('btn-controller-release').onclick = async () => {
    if (!state.controller) return;
    await state.controller.release();
  };
  window.addEventListener('pagehide', () => { if (state.controller) state.controller.release(); });
  $('sel-mic').onchange = (e) => {
    state.micId = e.target.value;
    localStorage.setItem('vc.mic', state.micId);
    renderPills();
  };
  $('rng-threshold').oninput = (e) => {
    $('threshold-val').textContent = (Number(e.target.value) / 1000).toFixed(3);
    localStorage.setItem('vc.threshold', String(Number(e.target.value) / 1000));
    if (state.recorder) state.recorder.threshold = thresholdValue();
  };
  $('chk-autosend').onchange = () => {
    api('/api/settings', { method: 'PUT', body: { behavior: { autoSend: $('chk-autosend').checked } } })
      .then((data) => { state.config = data.config; })
      .catch((err) => toast('保存失败：' + err.message, 'bad'));
  };
  $('chk-auto').onchange = async (e) => {
    state.autoMode = e.target.checked;
    if (state.autoMode) {
      await refreshMics({ requestPermission: true });
      await startRecording('auto');
    } else {
      await stopRecording();
      if (state.recorder) await state.recorder.cancel();
      phase('自动监听已关');
    }
  };

  const ptt = $('ptt');
  ptt.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    // 指针捕获失败不影响说话：合成事件、指针已抬起都会抛 NotFoundError
    try { ptt.setPointerCapture(e.pointerId); } catch { /* 忽略 */ }
    startRecording('ptt');
  });
  ptt.addEventListener('pointerup', () => stopRecording());
  ptt.addEventListener('pointercancel', () => stopRecording());
  ptt.addEventListener('lostpointercapture', () => { if (state.recording) stopRecording(); });

  document.addEventListener('keydown', (e) => {
    if (isTyping(e.target)) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); deliver('send'); }
      return;
    }
    if (e.key === 'Escape' && !$('drawer').hidden) { $('drawer').hidden = true; return; }
    const key = e.key.toLowerCase();
    const pttKey = (state.config && state.config.behavior.pttKey) || 'v';
    if (key === pttKey && !e.repeat && !state.autoMode) { e.preventDefault(); startRecording('ptt'); return; }
    if (key === 'l' && !e.repeat) { e.preventDefault(); deliver('send'); return; }
    if (key === 'r' && !e.repeat) { e.preventDefault(); setTranscript('', '已清空'); return; }
  }, true);

  document.addEventListener('keyup', (e) => {
    if (isTyping(e.target)) return;
    const pttKey = (state.config && state.config.behavior.pttKey) || 'v';
    if (e.key.toLowerCase() === pttKey && state.recording && !state.autoMode) { e.preventDefault(); stopRecording(); }
  }, true);

  window.addEventListener('beforeunload', () => { if (state.recorder) state.recorder.cancel(); });

  $('btn-retry').onclick = () => { if (state.lastUtterance) transcribe(state.lastUtterance); };
  $('btn-fill').onclick = () => deliver('fill');
  $('btn-send').onclick = () => deliver('send');
  $('btn-clear').onclick = () => setTranscript('', '已清空');
  $('transcript').oninput = (e) => {
    state.transcript = e.target.value;
    const has = !!state.transcript.trim();
    $('btn-send').disabled = !has;
    $('btn-fill').disabled = !has;
    $('btn-clear').disabled = !has;
  };
  $('btn-clear-log').onclick = () => { $('log').textContent = ''; };
}

function addAgent() {
  const id = 'agent-' + Date.now().toString(36).slice(-4);
  state.agents.push({
    id,
    name: '新 Agent',
    aliases: [],
    app: { bundleId: '', name: '' },
    launch: { command: '', workdir: '', newWindow: false },
    send: 'none',
    enabled: true,
    note: '',
  });
  renderAgentEditor();
  renderAgents();
}

// 页面上的错误也进日志：出问题时不至于只有一个红字，什么都没有
function installErrorLogging() {
  window.addEventListener('error', (e) => {
    pushLog('JS 错误：' + (e.message || '') + ' @ ' + (e.filename || '').split('/').pop() + ':' + (e.lineno || 0), 'error');
  });
  window.addEventListener('unhandledrejection', (e) => {
    const r = e.reason;
    pushLog('未处理的 Promise：' + (r && r.message ? r.message : String(r)), 'error');
  });
}

async function main() {
  bind();
  installErrorLogging();
  state.micId = localStorage.getItem('vc.mic') || '';
  try {
    await loadState();
  } catch (err) {
    toast('连不上本机服务：' + err.message, 'bad');
    return;
  }
  setTranscript('', '待机 · 按住 V 或上面的按钮');
  pollLog();
  setInterval(pollLog, 2500);
  // 设备列表不挡页面：没授权就先显示未命名设备，按「按住说话」时再要权限
  refreshMics();
  // 之前授权过手柄就直接接上（只听按键，不抢指针）
  autoConnectController().then((ok) => { if (ok) pushLog('手柄 · 自动接上上次授权的设备'); });
  // 板子插上 / 拔掉时自动重新认一次，不用手动点
  if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) {
    navigator.mediaDevices.addEventListener('devicechange', () => { refreshMics(); });
  }
}

main();
