// 实机上位机：连接、状态、调参、轴向向导、遥测、试手板。默认不接管，系统光标保持可用。
import { HidLink, AIKEY_FILTER } from '../island-poc/devices.js';
import { KEY } from '../island-poc/protocol.js';
import { ConfigClient, DEFAULT_CFG, axesText } from './devcfg.js';
import { Telemetry } from './telemetry.js';
import { runWizard, WIZARD_STEPS } from './wizard.js';
import { SimDevice } from './sim.js';
import { TESTS, TONE_LIMITS, report } from './bench.js';
import { openMic } from './miccap.js';

const $ = (s) => document.querySelector(s);
const FAULTS = [[1, 'IMU 故障'], [2, '音频故障'], [4, '触觉：本固件档暂不可用']];
const SLIDERS = [
  ['sens', '灵敏度（每度计数）', 1, 120, 0.5, 1], ['accel', '加速倍率', 1, 4, 0.05, 2],
  ['accelLo', '加速起点 °/s', 0, 120, 1, 0], ['accelHi', '加速满点 °/s', 60, 510, 2, 0],
  ['deadzone', '软死区 °/s', 0, 5, 0.1, 1], ['smoothLo', '平滑起点 °/s', 0, 30, 1, 0],
  ['smoothHi', '平滑终点 °/s', 1, 60, 1, 0], ['tau', '平滑时间常数 ms', 0, 200, 5, 0],
  ['freeze', '点击冻结 ms', 0, 255, 5, 0],
];
const BOOLS = ['invertX', 'invertY', 'gravity'];

let hid = null, sim = null, client = null, cfg = null, saved = null, session = null, last = null, dragging = null;
const samples = [];

// ---------- 日志与提示 ----------
const logEl = $('#log');
function log(text, cls = '') {
  const d = document.createElement('div');
  d.textContent = text; if (cls) d.className = cls;
  logEl.append(d);
  while (logEl.childElementCount > 400) logEl.firstChild.remove();
  logEl.scrollTop = logEl.scrollHeight;
}
function banner(text, cls = '') { const b = $('#banner'); b.textContent = text; b.className = 'banner ' + cls; }
function setText(id, text, cls = '') { const e = $(id); e.textContent = text; e.className = (e.classList.contains('mono') ? 'mono ' : '') + cls; }

// ---------- 参数面板 ----------
const sliderBox = $('#sliders'), inputs = {};
for (const [key, label, min, max, step] of SLIDERS) {
  const w = document.createElement('div'); w.className = 'sl';
  const l = document.createElement('label'); l.htmlFor = 'p-' + key; l.textContent = label;
  const o = document.createElement('output'); o.textContent = '—';
  const i = Object.assign(document.createElement('input'), { type: 'range', id: 'p-' + key, min, max, step, disabled: true });
  i.addEventListener('input', () => edit(key, +i.value));
  i.addEventListener('pointerdown', () => { dragging = key; });
  i.addEventListener('change', () => { dragging = null; render(); });
  w.append(l, o, i); sliderBox.append(w); inputs[key] = { i, o };
}
for (const k of BOOLS) $('#' + k).addEventListener('change', (e) => edit(k, e.target.checked));

// 互相牵制的字段顺手推开，免得写入被固件拒绝。
function edit(key, value) {
  if (!cfg || !client) return;
  const next = { ...cfg, [key]: value };
  if (key === 'accelLo' && next.accelHi <= value) next.accelHi = value + 2;
  if (key === 'accelHi' && next.accelLo >= value) next.accelLo = value - 2;
  if (key === 'smoothLo' && next.smoothHi < value) next.smoothHi = value;
  if (key === 'smoothHi' && next.smoothLo > value) next.smoothLo = value;
  cfg = next; render();
  client.setLive(next, (err, r) => {
    if (err) { showErr(err.message); return; }
    showErr(''); adopt(r); // 以设备回显为准：量化后的值才是真正生效的值
  });
}
function adopt(r) { if (!client.live) cfg = r.cfg; render(); }
function showErr(t) { const e = $('#cfgErr'); e.textContent = t; e.hidden = !t; }
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
function render() {
  const on = !!cfg;
  for (const [key, , , , , digits] of SLIDERS) {
    const { i, o } = inputs[key];
    i.disabled = !on;
    if (!on) { o.textContent = '—'; continue; }
    if (dragging !== key) i.value = cfg[key];
    o.textContent = cfg[key].toFixed(digits);
  }
  for (const k of BOOLS) { $('#' + k).disabled = !on; if (on) $('#' + k).checked = cfg[k]; }
  $('#axes').textContent = on ? '轴映射 ' + axesText(cfg.axisSrc, cfg.axisNeg) : '轴映射 —';
  $('#dirty').hidden = !on || same(cfg, saved);
  for (const id of ['#save', '#reload', '#defaults', '#recal', '#dfu']) $(id).disabled = !on;
  $('#wizardOpen').disabled = !on || !telOn();
  $('#wizardOpen').title = telOn() ? '' : '向导要读遥测，请先连接遥测串口';
}
const telOn = () => sim ? true : !!tel.port;

async function act(fn, ok) {
  try { const r = await fn(); showErr(''); if (ok) log(ok, 'p'); return r; }
  catch (err) { showErr(err.message); log(err.message, 'e'); return null; }
}
$('#save').onclick = async () => { const r = await act(() => client.save(), '已保存到手柄'); if (r) { saved = r.cfg; cfg = r.cfg; render(); } };
$('#reload').onclick = async () => { const r = await act(() => client.get()); if (r) { cfg = r.cfg; render(); } };
// 不用 0x16：它会连轴映射一起清掉。轴向是装配事实，不是手感，这里保留。
$('#defaults').onclick = async () => { const r = await act(() => client.set({ ...DEFAULT_CFG, axisSrc: cfg.axisSrc, axisNeg: cfg.axisNeg }), '手感参数已恢复默认（轴向保留），还没保存'); if (r) { cfg = r.cfg; render(); } };
$('#recal').onclick = () => act(() => client.calibrate(), '开始校准：请静置约 1.2 秒');
const dfu = $('#dfu');
dfu.onclick = async () => {
  if (dfu.dataset.arm !== '1') { dfu.dataset.arm = '1'; dfu.textContent = '再点一次确认'; setTimeout(() => { dfu.dataset.arm = ''; dfu.textContent = '进下载模式'; }, 3000); return; }
  dfu.dataset.arm = ''; dfu.textContent = '进下载模式';
  if (await act(() => client.download(), '手柄正在重启进下载模式，USB 会断开')) banner('手柄已进下载模式。烧录完成后重新连接。', 'warn');
};

// ---------- 连接 ----------
function hooks() {
  return {
    autoClaim: false,
    onKey() {}, onCaps() {},
    onMotion: (dx, dy) => moveDot(dx, dy),
    onLog: (t, c) => { if (!t.includes('KEEPALIVE')) log(t, c); }, // 每 200 ms 一条，留着只会淹没有用的日志
    onConfig: (b) => client?.onReply(b),
    onStatus: status,
    onState: ({ phase, text }) => {
      log(text, phase === 'error' || phase === 'lost' ? 'e' : '');
      if (phase === 'lost') { disconnected(text); return; }
      if (phase === 'error') banner(text, 'bad');
      else if (phase === 'pointer' && text.includes('松开')) banner(text, 'warn');
    },
  };
}
function attach(link, name) {
  hid = link; session = null; cfg = null; saved = null; last = null;
  client = new ConfigClient({ send: (b) => hid.sendConfig(b), getSession: () => session, onLog: log });
  setText('#kvLink', name, 'ok');
  $('#connHid').textContent = '断开'; $('#connHid').classList.remove('primary');
  banner('等待设备状态…');
}
function disconnected(reason) {
  hid = null; client = null; cfg = null; saved = null; session = null; last = null;
  setText('#kvLink', '未连接'); setText('#kvSession', '—'); setText('#kvOwner', '—'); setText('#kvCal', '—');
  $('#faults').replaceChildren(); $('#calHint').hidden = true;
  $('#connHid').textContent = '连接手柄'; $('#connHid').classList.add('primary');
  $('#host').disabled = $('#recenter').disabled = true; $('#host').textContent = '接管指针'; $('#host').classList.remove('on');
  document.querySelectorAll('#keys button').forEach((b) => b.classList.remove('down'));
  banner(reason || '已断开。', reason ? 'warn' : ''); render();
}
function status(r) {
  benchReport(r);
  const first = session === null;
  session = r.session;
  if (!last || last.owner !== r.owner) {
    const host = r.owner === 'HOST';
    setText('#kvOwner', host ? '上位机接管（HOST）' : '普通鼠标（POINTER）', host ? 'warn' : '');
    $('#host').textContent = host ? '交还系统鼠标' : '接管指针'; $('#host').classList.toggle('on', host);
    $('#recenter').disabled = !host;
    $('#boardHint').textContent = host ? '接管中：转动手柄移动圆点。系统光标停住，切走页面会自动交还。' : '普通鼠标模式：系统光标划过这里留下轨迹。';
  }
  if (!last || last.flags.calibrated !== r.flags.calibrated) {
    setText('#kvCal', r.flags.calibrated ? '已校准' : '未校准', r.flags.calibrated ? 'ok' : 'warn');
    $('#calHint').hidden = r.flags.calibrated;
  }
  if (!last || last.faults !== r.faults) {
    $('#faults').replaceChildren(...FAULTS.filter(([bit]) => r.faults & bit).map(([bit, t]) => {
      const s = document.createElement('span'); s.textContent = t; if (bit === 1) s.className = 'bad'; return s;
    }));
  }
  if (!last || last.buttons !== r.buttons) for (const [k, bit] of Object.entries(KEY)) document.querySelector(`#keys [data-k="${k}"]`).classList.toggle('down', !!(r.buttons & bit));
  last = r;
  if (first) {
    setText('#kvSession', r.session.toString(16).padStart(8, '0'));
    $('#host').disabled = false;
    banner(sim ? '虚拟手柄：数据是模拟的，不代表实物。试手板里拖动等于转动手腕，四键可点按。' : '已连接。调参时系统光标照常可用，改动立即生效，点「保存到手柄」才断电不丢。', sim ? 'warn' : '');
    act(() => client.get()).then((g) => { if (g) { cfg = g.cfg; saved = g.cfg; render(); if ((sim || tel.port) && !g.telemetry) enableTel(); } });
  }
}
async function connectReal(existing) {
  const link = new HidLink(hooks());
  attach(link, '连接中…');
  try { await link.connect(existing); setText('#kvLink', link.device?.productName || 'AI KEY', 'ok'); }
  catch (err) { disconnected(); banner('未连接：' + err.message, 'warn'); log(err.message, 'e'); }
}
function stopSim() {
  if (!sim) return;
  sim.stop(); sim = null; samples.length = 0; $('#useSim').classList.remove('on'); setText('#kvTel', '未连接');
  document.querySelectorAll('#keys button').forEach((b) => { b.disabled = true; });
}
$('#connHid').onclick = async () => {
  if (hid) { const was = hid; stopSim(); disconnected(); await was.close?.(); return; }
  if (!HidLink.supported()) { banner('这个浏览器不支持 WebHID。请用桌面版 Chrome 或 Edge，从 http://127.0.0.1 打开。', 'bad'); return; }
  await connectReal();
};
$('#useSim').onclick = async () => {
  if (sim) { stopSim(); disconnected(); return; }
  if (hid) { const was = hid; disconnected(); await was.close?.(); }
  sim = new SimDevice();
  $('#useSim').classList.add('on');
  const link = new HidLink({ ...hooks(), transport: sim });
  sim.onReport = (id, b) => (id === 2 ? link.receive(b) : client?.onReply(b));
  sim.onLine = (l) => tel.line(l);
  attach(link, '虚拟手柄（模拟数据）');
  setText('#kvTel', '虚拟', 'warn');
  sim.start();
  document.querySelectorAll('#keys button').forEach((b) => { b.disabled = false; });
};
document.querySelectorAll('#keys button').forEach((b) => {
  b.addEventListener('pointerdown', () => sim?.press(b.dataset.k, true));
  b.addEventListener('pointerup', () => sim?.press(b.dataset.k, false));
});
$('#toIsland').addEventListener('click', async (e) => {
  if (!hid || sim) return;
  e.preventDefault(); await hid.close(); location.href = e.currentTarget.href;
});

// ---------- 接管与失焦 ----------
$('#host').onclick = () => {
  if (!hid) return;
  if (hid.owner === 'HOST') hid.releaseHost(); else { hid.takeHost(); dot.x = board.width / 2; dot.y = board.height / 2; }
};
$('#recenter').onclick = () => { if (hid?.recenter()) { dot.x = board.width / 2; dot.y = board.height / 2; trail.length = 0; } };
// HOST 期间系统光标停住：切走页面就交还，回来再接管。
const away = () => { if (hid && !sim) hid.suspend(); };
const back = () => { if (hid && !sim && !document.hidden) hid.resume(); };
addEventListener('blur', away); addEventListener('focus', back);
document.addEventListener('visibilitychange', () => (document.hidden ? away() : back()));
addEventListener('pagehide', () => { if (hid && !sim) hid.close(); });

// ---------- 遥测 ----------
const tel = new Telemetry({
  onSample(d) { samples.push(d); if (samples.length > 700) samples.shift(); },
  onLog: (t) => log(t, 'd'),
  onState: (on) => { setText('#kvTel', on ? '已连接串口' : '未连接', on ? 'ok' : ''); $('#connTel').textContent = on ? '断开串口' : '连接遥测串口'; if (on) enableTel(); render(); },
});
function enableTel() { if (client && session !== null) act(() => client.telemetry(true)); }
$('#connTel').onclick = async () => {
  if (sim) { banner('虚拟手柄不需要串口，点「虚拟手柄」关掉后再连。', 'warn'); return; }
  if (tel.port) { if (client) await act(() => client.telemetry(false)); await tel.close(); return; }
  try { await tel.connect(); } catch (err) { if (err.name !== 'NotFoundError') { banner(err.message, 'bad'); log(err.message, 'e'); } }
};

// ---------- 曲线 ----------
const chart = $('#chart'), cx = chart.getContext('2d');
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const GOLD = css('--gold'), MINT = css('--mint'), LINE = css('--line'), INK3 = css('--ink3');
function fit(c) { const r = c.getBoundingClientRect(), s = devicePixelRatio || 1, w = Math.round(r.width * s), h = Math.round(r.height * s); if (w && (c.width !== w || c.height !== h)) { c.width = w; c.height = h; } }
function drawChart() {
  fit(chart);
  const W = chart.width, H = chart.height, s = devicePixelRatio || 1;
  cx.clearRect(0, 0, W, H);
  const peak = Math.max(30, ...samples.slice(-600).map((d) => Math.max(Math.abs(d.h), Math.abs(d.vv))));
  const scale = Math.pow(2, Math.ceil(Math.log2(peak))), mid = H / 2, y = (v) => mid - (v / scale) * (H / 2 - 6 * s);
  cx.strokeStyle = LINE; cx.lineWidth = 1; cx.beginPath(); cx.moveTo(0, mid); cx.lineTo(W, mid); cx.stroke();
  cx.fillStyle = INK3; cx.font = `${11 * s}px ${css('--mono')}`;
  cx.fillText(`+${scale} °/s`, 6 * s, 14 * s); cx.fillText(`-${scale} °/s`, 6 * s, H - 6 * s);
  const n = Math.min(samples.length, 600), off = samples.length - n;
  for (const [key, color] of [['h', GOLD], ['vv', MINT]]) {
    cx.strokeStyle = color; cx.lineWidth = 1.5 * s; cx.beginPath();
    for (let i = 0; i < n; i++) { const X = W - ((n - 1 - i) / 599) * W, Y = y(samples[off + i][key]); i ? cx.lineTo(X, Y) : cx.moveTo(X, Y); }
    cx.stroke();
  }
  const d = samples.at(-1);
  if (d) {
    const a = samples.at(-101);
    $('#rate').textContent = a && d.t > a.t ? `${Math.round(100000 / (d.t - a.t))} Hz` : '— Hz';
    if (d.bias) $('#stBias').textContent = d.bias.map((v) => v.toFixed(2)).join('  ');
    $('#stStill').textContent = d.still ? '是' : '否';
    $('#stDrop').textContent = tel.dropped;
  }
}

// ---------- 试手板 ----------
const board = $('#board'), bx = board.getContext('2d'), dot = { x: 0, y: 0 }, trail = [];
function moveDot(dx, dy) {
  const s = devicePixelRatio || 1;
  dot.x = Math.min(board.width, Math.max(0, dot.x + dx * s)); dot.y = Math.min(board.height, Math.max(0, dot.y + dy * s)); // 0x81 已平滑，逐帧直接用
  trail.push({ x: dot.x, y: dot.y, t: performance.now() });
}
let dragLast = null;
board.addEventListener('pointerdown', (e) => { if (sim) { dragLast = [e.clientX, e.clientY]; board.setPointerCapture(e.pointerId); } });
board.addEventListener('pointerup', () => { dragLast = null; });
board.addEventListener('pointermove', (e) => {
  const r = board.getBoundingClientRect(), s = board.width / r.width;
  if (sim && dragLast) { sim.drag(e.clientX - dragLast[0], e.clientY - dragLast[1]); dragLast = [e.clientX, e.clientY]; return; }
  if (hid?.owner === 'HOST') return;
  dot.x = (e.clientX - r.left) * s; dot.y = (e.clientY - r.top) * s;
  trail.push({ x: dot.x, y: dot.y, t: performance.now() });
});
function drawBoard() {
  fit(board);
  const W = board.width, H = board.height, s = devicePixelRatio || 1, t = performance.now();
  bx.clearRect(0, 0, W, H);
  bx.strokeStyle = LINE; bx.lineWidth = 1;
  bx.beginPath();
  for (let x = W / 8; x < W; x += W / 8) { bx.moveTo(x, 0); bx.lineTo(x, H); }
  for (let y = H / 4; y < H; y += H / 4) { bx.moveTo(0, y); bx.lineTo(W, y); }
  bx.stroke();
  while (trail.length && t - trail[0].t > 1500) trail.shift();
  bx.strokeStyle = GOLD; bx.lineWidth = 2 * s; bx.lineJoin = 'round'; bx.beginPath();
  trail.forEach((p, i) => (i ? bx.lineTo(p.x, p.y) : bx.moveTo(p.x, p.y)));
  bx.stroke();
  if (hid?.owner === 'HOST') { bx.fillStyle = GOLD; bx.beginPath(); bx.arc(dot.x, dot.y, 6 * s, 0, 7); bx.fill(); }
}
(function frame() { drawChart(); drawBoard(); requestAnimationFrame(frame); })();

// ---------- 轴向向导 ----------
const wz = { el: $('#wizard'), run: 0, resolve: null };
function wzPaint(id) {
  const at = WIZARD_STEPS.findIndex((s) => s.id === id);
  $('#wzSteps').replaceChildren(...WIZARD_STEPS.map((s, i) => { const li = document.createElement('li'); li.textContent = s.title; li.className = i === at ? 'now' : i < at || at < 0 ? 'done' : ''; return li; }));
}
function wzNote(text, cls = '') { const li = document.createElement('li'); li.textContent = text; li.className = cls; $('#wzNotes').append(li); }
$('#wizardOpen').onclick = async () => {
  const run = ++wz.run, go = $('#wzGo');
  wz.el.hidden = false; $('#wzNotes').replaceChildren();
  const ui = {
    note: (t) => wzNote(t, t.endsWith('正确') ? 'ok' : t.endsWith('不对') ? 'bad' : ''),
    step: (s) => new Promise((resolve, reject) => {
      if (run !== wz.run) { reject(new Error('已关闭')); return; }
      wzPaint(s.id); $('#wzTitle').textContent = s.title; $('#wzBody').textContent = s.body;
      go.hidden = false; go.disabled = false; go.textContent = s.action;
      wz.abort = reject;
      go.onclick = () => { go.disabled = true; go.textContent = '读取中…'; sim?.act(s.id); resolve(); };
    }),
  };
  try {
    const res = await runWizard({ cfg, client, tel, ui });
    if (run !== wz.run) return;
    cfg = res.applied; render(); wzPaint('');
    $('#wzTitle').textContent = res.passed ? '方向核对通过' : '方向核对没通过';
    $('#wzBody').textContent = res.passed ? '轴向已生效，但还没保存。确认手感后点「保存到手柄」。' : '多半是动作做反了或幅度太小，可以再跑一次。平放、竖起两步都做对了还反的话，把日志发给固件同事。';
  } catch (err) {
    if (run !== wz.run) return;
    $('#wzTitle').textContent = '向导已停止'; $('#wzBody').textContent = err.message;
    const r = await client?.get().catch(() => null); if (r) { cfg = r.cfg; render(); }
  }
  go.hidden = true;
};
$('#wzCancel').onclick = () => { wz.run++; wz.abort?.(new Error('已关闭')); wz.el.hidden = true; };

// ---------- 逐项测试 ----------
const STORE = 'aikey-bench-v1';
const bench = { at: 0, results: {}, running: null, waiters: [], last: null, wavUrl: null };
try { const s = JSON.parse(localStorage.getItem(STORE) || '{}'); bench.results = s.results || {}; $('#benchBoard').value = s.board || ''; } catch {}
function benchSave() { try { localStorage.setItem(STORE, JSON.stringify({ results: bench.results, board: $('#benchBoard').value })); } catch {} }
const stLabel = (r) => (!r ? ['未测', ''] : r.skipped ? ['跳过', ''] : r.pass ? ['通过', 'pass'] : ['不通过', 'fail']);
function benchPaint() {
  const running = bench.running !== null, t = TESTS[bench.at], r = bench.results[t.id];
  $('#benchList').replaceChildren(...TESTS.map((x, i) => {
    const li = document.createElement('li'), b = document.createElement('button'), st = document.createElement('span'), nm = document.createElement('span');
    const [label, cls] = bench.running === i ? ['进行中', 'run'] : stLabel(bench.results[x.id]);
    b.type = 'button'; b.className = i === bench.at ? 'now' : ''; b.disabled = running && i !== bench.at;
    st.className = 'st ' + cls; st.textContent = label; nm.textContent = `${i + 1}. ${x.title}`;
    b.append(st, nm); b.onclick = () => { bench.at = i; benchClear(); benchPaint(); };
    li.append(b); return li;
  }));
  $('#benchName').textContent = `${bench.at + 1}. ${t.title}`; $('#benchHow').textContent = t.how;
  $('#toneBox').hidden = !t.needsSpeaker;
  const res = $('#benchRes'); res.textContent = r?.text ?? ''; res.className = 'benchres ' + stLabel(r)[1];
  const blocked = t.needsSpeaker && !$('#spkOk').checked;
  const run = $('#benchRun'); run.hidden = running; run.disabled = blocked; run.textContent = r ? '重测' : '开始';
  $('#benchStop').hidden = !running; $('#benchSkip').disabled = running; $('#benchNext').disabled = running || bench.at === TESTS.length - 1;
  const pass = TESTS.filter((x) => bench.results[x.id]?.pass).length;
  $('#benchScore').textContent = `${pass} / ${TESTS.length} 通过`;
  $('#benchReset').disabled = $('#benchCopy').disabled = running;
}
function benchClear() {
  $('#benchSay').textContent = ''; $('#benchKeys').hidden = true; $('#benchMeter').hidden = true; $('#benchAsk').hidden = true;
  $('#benchAudio').hidden = true; $('#benchAudio').removeAttribute('src');
  if (bench.wavUrl) { URL.revokeObjectURL(bench.wavUrl); bench.wavUrl = null; }
}
function benchReport(r) {
  bench.last = r;
  bench.waiters = bench.waiters.filter((w) => { if (!w.test(r)) return true; clearTimeout(w.timer); w.resolve(r); return false; });
}
function benchCtx(signal) {
  const aborted = () => new Error('已中止');
  const stop = (reject) => { signal.addEventListener('abort', () => reject(aborted()), { once: true }); };
  return {
    get hid() { return hid; }, get client() { return client; },
    now: () => performance.now(), last: () => bench.last,
    sleep: (ms) => new Promise((res, rej) => { if (signal.aborted) rej(aborted()); stop(rej); setTimeout(res, ms); }),
    waitReport: (test, ms, msg = '等待超时') => new Promise((resolve, reject) => {
      if (signal.aborted) { reject(aborted()); return; }
      const w = { test, resolve, timer: setTimeout(() => { bench.waiters = bench.waiters.filter((x) => x !== w); reject(new Error(msg)); }, ms) };
      stop((e) => { clearTimeout(w.timer); bench.waiters = bench.waiters.filter((x) => x !== w); reject(e); });
      bench.waiters.push(w);
    }),
    say(text, pendingKeys) {
      $('#benchSay').textContent = text;
      if (!pendingKeys) return;
      $('#benchKeys').hidden = false;
      $('#benchKeys').replaceChildren(...['L', 'R', 'V', 'S'].map((k) => { const s = document.createElement('span'); s.textContent = k; if (!pendingKeys.includes(k)) s.className = 'done'; return s; }));
    },
    level(v) { $('#benchMeter').hidden = false; $('#benchLevel').style.width = `${Math.min(100, Math.max(0, (20 * Math.log10(v + 1e-6) + 70) / 70 * 100))}%`; },
    async telemetry(ms) {
      const d0 = tel.dropped, got = await tel.collect(ms);
      const span = got.length > 1 ? got.at(-1).t - got[0].t : 0;
      return { count: got.length, hz: span ? (got.length - 1) * 1000 / span : 0, dropped: tel.dropped - d0 };
    },
    capture: () => (sim ? sim.capture() : openMic()),
    expectSound: () => sim?.clap(),
    toneParams() {
      const v = (id, lo, hi) => { const n = Math.round(+$(id).value); if (!(n >= lo && n <= hi)) throw new Error(`${id === '#toneHz' ? '频率' : id === '#toneMs' ? '时长' : '衰减'}要在 ${lo}–${hi}`); return n; };
      const L = TONE_LIMITS;
      return { hz: v('#toneHz', L.minHz, L.maxHz), ms: v('#toneMs', L.minMs, L.maxMs), atten: v('#toneAtten', L.minAtten, L.maxAtten) };
    },
    ask: (q, options) => new Promise((resolve, reject) => {
      const box = $('#benchAsk'); $('#benchSay').textContent = q; box.hidden = false; stop(reject);
      box.replaceChildren(...options.map((t, i) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = t; b.onclick = () => { box.hidden = true; resolve(i); }; return b; }));
    }),
  };
}
async function benchRun() {
  const i = bench.at, t = TESTS[i], ac = new AbortController();
  benchClear(); delete bench.results[t.id];
  bench.running = i; bench.abort = ac; benchPaint();
  let r;
  try { r = await t.run(benchCtx(ac.signal)); }
  catch (err) { r = { pass: false, text: err.message }; }
  if (r.wav) { bench.wavUrl = URL.createObjectURL(new Blob([r.wav], { type: 'audio/wav' })); const a = $('#benchAudio'); a.src = bench.wavUrl; a.hidden = false; }
  const aborted = ac.signal.aborted;
  bench.running = null; bench.abort = null; bench.waiters = [];
  if (!aborted) { bench.results[t.id] = { pass: !!r.pass, text: r.text }; log(`测试 ${t.title}：${r.pass ? '通过' : '不通过'}  ${r.text}`, r.pass ? 'p' : 'e'); }
  $('#benchSay').textContent = ''; $('#benchAsk').hidden = true; $('#benchMeter').hidden = true;
  benchSave(); benchPaint();
}
$('#benchRun').onclick = benchRun;
$('#benchStop').onclick = () => bench.abort?.abort();
$('#benchSkip').onclick = () => { const t = TESTS[bench.at]; bench.results[t.id] = { skipped: true, text: '' }; benchSave(); if (bench.at < TESTS.length - 1) bench.at++; benchClear(); benchPaint(); };
$('#benchNext').onclick = () => { bench.at = Math.min(bench.at + 1, TESTS.length - 1); benchClear(); benchPaint(); };
$('#benchReset').onclick = () => { bench.results = {}; bench.at = 0; benchClear(); benchSave(); benchPaint(); };
$('#benchBoard').addEventListener('change', benchSave);
$('#spkOk').addEventListener('change', benchPaint);
$('#benchCopy').onclick = async () => {
  const text = report(bench.results, $('#benchBoard').value.trim());
  try { await navigator.clipboard.writeText(text); log('测试结果已复制', 'p'); } catch { log(text); }
};
benchPaint();

// ---------- 启动 ----------
render();
if (!HidLink.supported()) banner('这个浏览器不支持 WebHID。请用桌面版 Chrome 或 Edge，从 http://127.0.0.1 打开。可以先点「虚拟手柄」看界面。', 'warn');
else navigator.hid.getDevices().then((ds) => { // 授权过的手柄：打开页面直接连，不再弹选择框
  const d = ds.find((x) => x.vendorId === AIKEY_FILTER.vendorId && x.productId === AIKEY_FILTER.productId);
  if (d && !hid) connectReal(d);
});
if (Telemetry.supported()) navigator.serial.getPorts().then((ps) => {
  const p = ps.find((x) => { const i = x.getInfo(); return i.usbVendorId === 0xcafe && i.usbProductId === 0x4031; });
  if (p && !tel.port) tel.connect(p).catch((err) => log(err.message, 'e'));
});
window.__host = { get hid() { return hid; }, get cfg() { return cfg; }, get sim() { return sim; }, tel, bench };
