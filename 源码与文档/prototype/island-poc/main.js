import { KeyGrammar } from './grammar.js';
import { Haptics } from './haptics.js';
import { HidLink, Voice } from './devices.js';
import { Mascot, Buddy } from './mascot.js';
import { SCENES, INTRO, OUTRO } from './scenes.js';

const $ = (s) => document.querySelector(s);
const W = 1280, H = 800, ISLAND = { x: 640, y: 20 };
const inner = $('#inner'), screen = $('#screen');

// ---------- 缩放：内部按 1280×800 设计坐标 ----------
let scale = 1;
function fit() { scale = (screen.clientWidth - 20) / W; inner.style.transform = `scale(${scale})`; }
new ResizeObserver(fit).observe(screen); fit();
const toInner = (cx, cy) => { const r = inner.getBoundingClientRect(); return { x: (cx - r.left) / scale, y: (cy - r.top) / scale }; };
function rectOf(el) { const r = el.getBoundingClientRect(), o = inner.getBoundingClientRect(); return { x: (r.left - o.left) / scale, y: (r.top - o.top) / scale, w: r.width / scale, h: r.height / scale }; }

// ---------- 日志 ----------
const logEl = $('#log');
function log(text, cls = '') {
  const li = document.createElement('li'); if (cls) li.className = cls;
  const t = new Date(); li.innerHTML = `<span>${String(t.getSeconds()).padStart(2, '0')}.${String(t.getMilliseconds()).padStart(3, '0').slice(0, 2)}</span><b>${text}</b>`;
  logEl.prepend(li); while (logEl.children.length > 9) logEl.lastChild.remove();
}

// ---------- 灵动岛 ----------
const islandEl = $('#island'), islBody = $('#islBody');
const islMascot = new Mascot($('#islMascot'));
const island = {
  state: 'idle',
  set(state, html) { islandEl.className = 'island state-' + state + (this.away ? ' state-away' : ''); this.state = state; if (html !== undefined) islBody.innerHTML = html; },
  idle() { this.set('idle', `<span class="isl-text">${app.scene?.mode ?? ''}</span><span class="isl-dot"></span>`); islMascot.mood(null); },
  hint(text, keys = '') { this.set('hint', `<span class="isl-text">${text}</span>${keys ? `<span class="isl-keys">${keys}</span>` : ''}`); },
  think(text) { islMascot.mood('think'); this.set('think', `<span class="isl-text isl-shimmer">${text}</span>`); },
  done(text) { islMascot.mood('happy'); this.set('done', `<span class="isl-check">✓</span><span class="isl-text">${text}</span>`); },
  away: false,
  setAway(on) { this.away = on; islandEl.classList.toggle('state-away', on); },
};

// ---------- 指针 ----------
const pointerEl = $('#pointer');
const pointer = { x: 640, y: 420 };
function placePointer() { pointerEl.style.transform = `translate(${pointer.x}px,${pointer.y}px)`; }
placePointer();

// ---------- 触觉 ----------
const scope = $('#scope'), sctx = scope.getContext('2d'), motorIcon = $('#motorIcon'), hapName = $('#hapName');
let env = 0, envUntil = 0, phaseT = 0; const trace = new Array(150).fill(0);
const haptics = new Haptics({
  isBlocked: () => grammar.drawing || grammar.recording,
  onPulse: ({ name, dur, amp }) => {
    env = amp; envUntil = performance.now() + dur; hapName.textContent = `马达 · ${name} ${dur}ms`;
    motorIcon.classList.add('buzz'); setTimeout(() => motorIcon.classList.remove('buzz'), dur);
    islMascot.zap(); if (app.buddy.out) Mascot.prototype.zap.call(app.buddy);
    if (hid) hid.pulse();
  },
});
function haptic(id) { const r = haptics.play(id); log(`触觉 · ${id}${r === 'queued' ? '（录音/圈画中，排队）' : ''}`, 'p'); }
function drawScope(now) {
  const a = now < envUntil ? env : 0; phaseT += 0.9;
  trace.push(a * Math.sin(phaseT) * (0.7 + Math.random() * 0.3)); trace.shift();
  const w = scope.width, h = scope.height; sctx.clearRect(0, 0, w, h);
  sctx.strokeStyle = '#2a2622'; sctx.beginPath(); sctx.moveTo(0, h / 2); sctx.lineTo(w, h / 2); sctx.stroke();
  sctx.strokeStyle = '#f2b33d'; sctx.lineWidth = 2; sctx.beginPath();
  trace.forEach((v, i) => { const x = (i / (trace.length - 1)) * w, y = h / 2 - v * h * 0.42; i ? sctx.lineTo(x, y) : sctx.moveTo(x, y); });
  sctx.stroke();
  if (now > envUntil + 600 && !hapName.textContent.endsWith('静止')) hapName.textContent = '马达 · 静止';
}

// ---------- 陀螺仪姿态示意 ----------
const attDot = $('#attDot'); let vx = 0, vy = 0;
function feelMotion(dx, dy) { vx = vx * 0.6 + dx * 0.4; vy = vy * 0.6 + dy * 0.4; }
function drawAtt() { vx *= 0.88; vy *= 0.88; const k = 1.6, cx = Math.max(-36, Math.min(36, vx * k)), cy = Math.max(-36, Math.min(36, vy * k)); attDot.style.transform = `translate(${cx}px,${cy}px)`; }

// ---------- 画线层 ----------
const ink = $('#ink');
const svgNS = 'http://www.w3.org/2000/svg';
let stroke = null;
function startStroke(kind) {
  ink.innerHTML = '';
  stroke = { kind, points: [{ ...pointer }], el: document.createElementNS(svgNS, 'path') };
  if (kind === 'brush') stroke.el.setAttribute('style', 'fill:none;stroke:#f2b33d;stroke-opacity:.45;stroke-width:34;stroke-linecap:round;stroke-linejoin:round');
  else stroke.el.setAttribute('style', 'fill:#f2b33d22;stroke:#f2b33d;stroke-width:3.5;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:0');
  ink.appendChild(stroke.el); renderStroke();
}
function renderStroke(close = false) {
  if (!stroke) return;
  const p = stroke.points; let d = `M${p[0].x},${p[0].y}`;
  for (let i = 1; i < p.length; i++) { const a = p[i - 1], b = p[i]; d += ` Q${a.x},${a.y} ${(a.x + b.x) / 2},${(a.y + b.y) / 2}`; }
  if (close && stroke.kind === 'lasso') d += ' Z';
  stroke.el.setAttribute('d', d);
}
function clearInk() { ink.innerHTML = ''; stroke = null; app.apps.querySelectorAll('.hl-box').forEach((n) => n.remove()); }
function markBox(r, label) {
  const b = document.createElement('div'); b.className = 'hl-box';
  Object.assign(b.style, { left: r.x - 6 + 'px', top: r.y - 30 - 6 + 'px', width: r.w + 12 + 'px', height: r.h + 12 + 'px' });
  b.innerHTML = `<span>${label}</span>`; app.apps.appendChild(b); return b;
}
function inPoly(pt, poly) {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i], b = poly[j];
    if ((a.y > pt.y) !== (b.y > pt.y) && pt.x < ((b.x - a.x) * (pt.y - a.y)) / (b.y - a.y) + a.x) c = !c;
  }
  return c;
}
function polyArea(p) { let s = 0; for (let i = 0, j = p.length - 1; i < p.length; j = i++) s += (p[j].x + p[i].x) * (p[j].y - p[i].y); return Math.abs(s / 2); }
// 选中判定：圈选看中心点是否在闭合区域内；涂抹看笔迹落在元素内的点数。
function hits(el, sel) {
  const r = rectOf(el), c = { x: r.x + r.w / 2, y: r.y + r.h / 2 };
  if (sel.kind === 'lasso') return inPoly(c, sel.points) ? 1 : 0;
  return sel.points.filter((p) => p.x >= r.x - 12 && p.x <= r.x + r.w + 12 && p.y >= r.y - 12 && p.y <= r.y + r.h + 12).length;
}

// ---------- 面板 / 提示 / 字幕 ----------
const panelEl = $('#panel'), toastEl = $('#toast'), captionEl = $('#caption');
function showPanel(html) { panelEl.hidden = false; panelEl.innerHTML = html; panelEl.style.animation = 'none'; void panelEl.offsetWidth; panelEl.style.animation = ''; }
function hidePanel() { panelEl.hidden = true; }
let toastT;
function toast(text, ms = 2200) { toastEl.hidden = false; toastEl.innerHTML = text; clearTimeout(toastT); toastT = setTimeout(() => (toastEl.hidden = true), ms); }
function caption(main, sub = '') { captionEl.classList.remove('show'); setTimeout(() => { captionEl.innerHTML = main + (sub ? `<small>${sub}</small>` : ''); captionEl.classList.add('show'); }, 120); }

// ---------- 应用上下文（场景使用） ----------
let cancelToken = { stopped: false };
const sleep = (ms) => new Promise((res, rej) => { const t = cancelToken; setTimeout(() => (t.stopped && directing ? rej(new Error('stop')) : res()), ms); });
const app = {
  inner, apps: $('#apps'), island, islMascot, haptic, log, toast, caption, showPanel, hidePanel, panel: panelEl,
  rectOf, hits, markBox, inPoly, sleep, pointer, clearInk,
  buddy: new Buddy($('#buddy')), phase: 'idle', selection: null, scene: null, sceneIndex: 0,
  setAppName(n) { $('#appName').textContent = n; },
  async buddyOut(x, y) {
    const b = app.buddy;
    if (!b.out) { b.place(ISLAND.x, ISLAND.y + 8); $('#buddy').hidden = false; island.setAway(true); b.out = true; haptic('hop'); }
    b.mood('wow'); await b.hopTo(x, y, { height: 120, ms: 760 }); haptic('land'); b.mood(null);
  },
  async buddyHome() {
    const b = app.buddy; if (!b.out) return;
    b.quiet(); b.peek(false); b.mood('happy'); await b.hopTo(ISLAND.x, ISLAND.y + 8, { height: 90, ms: 650 });
    $('#buddy').hidden = true; b.out = false; island.setAway(false);
  },
};

// ---------- 场景切换 ----------
const nav = $('#sceneNav');
function buildNav() {
  const groups = {};
  SCENES.forEach((s, i) => { (groups[s.mode] ||= []).push([s, i]); });
  nav.innerHTML = Object.entries(groups).map(([m, list]) => `<div class="grp"><span>${m}</span>${list.map(([s, i]) => `<button type="button" data-i="${i}">${s.title}</button>`).join('')}</div>`).join('');
  nav.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b && !directing) enter(+b.dataset.i); });
}
function enter(i, { quiet = false } = {}) {
  const s = SCENES[i]; app.sceneIndex = i; app.scene = s;
  nav.querySelectorAll('button').forEach((b) => b.classList.toggle('on', +b.dataset.i === i));
  app.apps.innerHTML = ''; clearInk(); hidePanel(); toastEl.hidden = true; app.selection = null; app.phase = 'idle';
  app.buddy.quiet(); $('#buddy').hidden = true; app.buddy.out = false; island.setAway(false);
  s.mount(app); app.setAppName(s.appName);
  island.hint(s.hint, s.keys ?? '');
  if (!quiet) caption(`<b>${s.mode}</b> · ${s.title}`, s.pitch);
}

// ---------- 灵动岛流转菜单 ----------
let menu = null;
function openMenu() {
  menu = { i: app.sceneIndex, acc: 0 };
  islMascot.mood('wow'); renderMenu(); haptic('open'); log('灵动岛展开 · 倾斜挑选界面');
}
function renderMenu() {
  island.set('menu', `<div class="menu"><div class="menu-h"><b>去哪儿？</b><span>倾斜手柄左右挑选 · <kbd>L</kbd> 进入 · <kbd>R</kbd> 收起</span></div><div class="menu-cards">${SCENES.map((s, i) => `<div class="mc ${i === menu.i ? 'on' : ''} ${i === app.sceneIndex ? 'cur' : ''}"><div class="m">${s.mode}</div><div class="ic">${s.icon}</div><div class="t">${s.title}</div><div class="d">${s.desc}</div></div>`).join('')}</div></div>`);
}
function menuTilt(dx) {
  if (!menu) return; menu.acc += dx;
  const step = 70;
  while (Math.abs(menu.acc) >= step) {
    const dir = Math.sign(menu.acc); menu.acc -= dir * step;
    const ni = Math.max(0, Math.min(SCENES.length - 1, menu.i + dir));
    if (ni !== menu.i) { menu.i = ni; haptic('tick'); renderMenu(); }
  }
}
function closeMenu(go) {
  const target = menu?.i; menu = null; islMascot.mood(null);
  if (go && target !== undefined) { haptic('land'); enter(target); } else { island.hint(app.scene.hint, app.scene.keys ?? ''); }
}

// ---------- 语音 ----------
const voice = new Voice();
let listen = null;
function startListening() {
  const scene = app.scene;
  const canned = (directing && app.demoUtterance) || scene.utterance?.(app) || '';
  listen = { canned, shown: '', real: false, t0: performance.now() };
  if ($('#realVoice').checked && !directing && voice.available) { listen.real = voice.start(); voice.onPartial = (t) => { if (listen) listen.shown = t; }; }
  islMascot.mood('listen');
  island.set('listen', `<div class="isl-wave">${'<i></i>'.repeat(14)}</div><span class="isl-text" id="islSaid">在听…</span>`);
  pointerEl.classList.add('voice');
  hid?.record(true);
  log('V 保持 → 开始说话 · RECORD=1', 'h');
}
function tickListening(now) {
  if (!listen) return;
  const waves = islBody.querySelectorAll('.isl-wave i');
  waves.forEach((w, i) => { w.style.height = 5 + Math.abs(Math.sin(now / 120 + i * 0.7)) * (10 + Math.random() * 12) + 'px'; });
  if (!listen.real) { const n = Math.min(listen.canned.length, Math.floor((now - listen.t0) / 95)); listen.shown = listen.canned.slice(0, n); }
  const said = $('#islSaid'); if (said && listen.shown) said.textContent = listen.shown.slice(-26);
}
async function stopListening() {
  const l = listen; listen = null; pointerEl.classList.remove('voice');
  hid?.record(false);
  let text = l.canned;
  if (l.real) { const heard = await voice.stop(); if (heard) text = heard; else log('未识别到语音，改用示例话术', 'e'); }
  log(`V 松开 → 「${text.slice(0, 16)}…」`, 'h');
  return text;
}

// ---------- 语义事件 → 交互 ----------
let busy = false;
async function run(fn) { busy = true; try { await fn(); } catch (e) { if (e.message !== 'stop') console.error(e); } finally { busy = false; } }
const grammar = new KeyGrammar((e) => onSemantic(e));
function onSemantic(e) {
  const s = app.scene;
  if (e.type === 'key') { setKeyVisual(e.key, e.down); return; }
  if (e.type === 'island') {
    if (busy) return;
    if (menu) { closeMenu(false); return; }
    if (app.phase === 'preview') { toast('先用 <b>L</b> 确认或 <b>R</b> 取消当前修改'); return; }
    openMenu(); return;
  }
  if (e.type === 'primary') {
    if (menu) { closeMenu(true); return; }
    if (busy) return;
    if (app.phase === 'preview') { log('L → 确认应用', 'h'); run(async () => { app.phase = 'busy'; hidePanel(); await s.onConfirm(app); }); return; }
    s.onPrimary?.(app); return;
  }
  if (e.type === 'back') {
    if (menu) { closeMenu(false); return; }
    if (busy) return;
    if (app.phase === 'preview') { hidePanel(); s.onBack?.(app); app.phase = app.selection ? 'selected' : 'idle'; island.hint('已取消这次修改，原内容不变', '<kbd>V</kbd> 重新说'); haptic('tick'); log('R → 取消预览'); return; }
    if (app.phase === 'selected') { clearInk(); app.selection = null; app.phase = 'idle'; s.onClear?.(app); island.hint(s.hint, s.keys ?? ''); log('R → 清除选区'); return; }
    return;
  }
  if (e.type === 'drawStart') {
    if (menu || busy || app.phase === 'preview') return;
    if (!s.draw) { toast(s.noDraw ?? '这里不需要圈选，按住 V 直接说'); return; }
    clearInk(); app.selection = null; s.onClear?.(app);
    startStroke(s.draw); pointerEl.classList.add('draw');
    island.hint(s.draw === 'brush' ? '涂抹想改的地方…' : '圈住想改的部分…', '松开 <kbd>S</kbd> 闭合');
    hid?.draw(true); log(`S 长按 → ${s.draw === 'brush' ? '涂抹' : '圈选'}开始 · DRAW=1`, 'h'); return;
  }
  if (e.type === 'drawEnd' || e.type === 'drawCancel') {
    pointerEl.classList.remove('draw'); hid?.draw(false);
    if (!stroke) return;
    renderStroke(true);
    const sel = { kind: stroke.kind, points: stroke.points };
    const area = stroke.kind === 'lasso' ? polyArea(sel.points) : sel.points.length * 400;
    log(`S 松开 → ${stroke.kind === 'lasso' ? '圈选闭合' : '涂抹结束'} · DRAW=0`, 'h');
    if (e.type === 'drawCancel' || area < 1500 || sel.points.length < 6) { clearInk(); island.hint('选区太小，按住 S 再圈一次'); haptics.flush(); haptic('warn'); return; }
    const res = s.select(app, sel);
    haptics.flush();
    if (!res?.ok) { clearInk(); island.hint(res?.msg ?? '没认出圈里的内容，再试一次'); haptic('warn'); return; }
    app.selection = { ...sel, ...res }; app.phase = 'selected'; haptic('snap');
    island.hint(`已选中 <em>${res.label}</em>`, '按住 <kbd>V</kbd> 说要求');
    return;
  }
  if (e.type === 'lock') { app.lock = { ...pointer }; pointerEl.classList.add('locked'); return; }
  if (e.type === 'unlock') { pointerEl.classList.remove('locked'); return; }
  if (e.type === 'recenter') {
    pointer.x = 640; pointer.y = 420; placePointer(); pointerEl.classList.remove('locked'); hid?.recenter();
    haptic('tick'); log('V 双击 → 居中 · RECENTER', 'h'); island.hint('指针已回到屏幕中心'); return;
  }
  if (e.type === 'voiceStart') {
    if (menu) closeMenu(false);
    if (busy || app.phase === 'preview') { toast('先处理当前预览：<b>L</b> 确认 · <b>R</b> 取消'); grammar.recording = false; return; }
    if (s.needsSelection && !app.selection) { toast('先按住 <b>S</b> 圈出要改的部分，再说话'); grammar.recording = false; return; }
    startListening(); return;
  }
  if (e.type === 'voiceEnd' || e.type === 'voiceCancel') {
    pointerEl.classList.remove('locked');
    if (!listen) return;
    if (e.type === 'voiceCancel') { listen = null; pointerEl.classList.remove('voice'); hid?.record(false); island.hint('语音已取消'); return; }
    haptics.flush();
    run(async () => { const text = await stopListening(); app.phase = 'busy'; islMascot.mood('think'); await s.onVoice(app, text); if (app.phase === 'busy') app.phase = app.selection ? 'selected' : 'idle'; });
  }
}

// ---------- 按键可视化与输入源 ----------
const gripKeys = Object.fromEntries([...document.querySelectorAll('#grip .k')].map((g) => [g.dataset.k, g]));
const keyBtns = Object.fromEntries([...document.querySelectorAll('#keyBtns button')].map((b) => [b.dataset.k, b]));
function setKeyVisual(k, down) { gripKeys[k]?.classList.toggle('down', down); keyBtns[k]?.classList.toggle('down', down); if (down) log(`${k} 按下`); }
const now = () => performance.now();
function press(k) { grammar.press(k, now()); }
function release(k) { grammar.release(k, now()); }

function movePointer(dx, dy) {
  pointer.x = Math.max(4, Math.min(W - 4, pointer.x + dx)); pointer.y = Math.max(4, Math.min(H - 4, pointer.y + dy));
  feelMotion(dx, dy); placePointer();
  if (menu) { menuTilt(dx); return; }
  if (stroke) { const last = stroke.points[stroke.points.length - 1]; if (Math.hypot(pointer.x - last.x, pointer.y - last.y) > 4) { stroke.points.push({ ...pointer }); renderStroke(); } }
  app.scene?.onHover?.(app, pointer);
}
function setPointer(x, y) { movePointer(x - pointer.x, y - pointer.y); }

// 键鼠模拟
let simOn = true;
const simAllowed = () => simOn && !directing;
inner.addEventListener('mousemove', (e) => { if (!simAllowed()) return; const p = toInner(e.clientX, e.clientY); setPointer(p.x, p.y); });
inner.addEventListener('mousedown', (e) => { if (!simAllowed()) return; e.preventDefault(); press(e.button === 2 ? 'R' : 'L'); });
inner.addEventListener('mouseup', (e) => { if (!simAllowed()) return; release(e.button === 2 ? 'R' : 'L'); });
inner.addEventListener('contextmenu', (e) => e.preventDefault());
const KEYMAP = { F1: 'L', Digit1: 'L', F2: 'R', Digit2: 'R', F3: 'V', Space: 'V', F4: 'S', KeyD: 'S' };
addEventListener('keydown', (e) => {
  if (e.code === 'Escape') { if (directing) stopDemo(); grammar.reset(now()); return; }
  if (e.target.closest?.('input,textarea')) return;
  const k = KEYMAP[e.code]; if (!k) return;
  e.preventDefault(); if (e.repeat || !simAllowed()) return; press(k);
});
addEventListener('keyup', (e) => { const k = KEYMAP[e.code]; if (!k || !simAllowed()) return; e.preventDefault(); release(k); });
addEventListener('blur', () => { grammar.reset(now()); if (hid?.suspend()) log('页面失焦 → RELEASE，光标交还系统', 'h'); });
addEventListener('focus', () => { if (hid?.resume()) log('回到页面 → 重新 HELLO / CLAIM', 'h'); });
document.addEventListener('visibilitychange', () => {
  if (document.hidden) { grammar.reset(now()); hid?.suspend(); } else if (document.hasFocus()) hid?.resume();
});
Object.entries(keyBtns).forEach(([k, b]) => {
  b.addEventListener('pointerdown', (e) => { if (!simAllowed()) return; e.preventDefault(); b.setPointerCapture(e.pointerId); press(k); });
  b.addEventListener('pointerup', () => simAllowed() && release(k));
  b.addEventListener('pointercancel', () => simAllowed() && release(k));
});

// ---------- 实物：AI KEY（WebHID） ----------
let hid = null;
const linkStatus = $('#linkStatus'), linkBadge = $('#linkBadge'), ownerBadge = $('#ownerBadge');
$('#useSim').onclick = async () => { if (hid) { await hid.close(); hid = null; } simOn = true; setLink('sim'); };
$('#useHid').onclick = async () => {
  if (window.__ISLAND_HOSTED) { linkStatus.textContent = '在线版运行在受限框架里，浏览器不允许直连 USB 设备。接实物请在本机双击 prototype/启动灵动岛POC.command，用 Chrome 打开。'; return; }
  if (!HidLink.supported()) { linkStatus.textContent = '当前浏览器不支持 WebHID。请用桌面版 Chrome 或 Edge，通过 http://127.0.0.1 打开本页。'; return; }
  try {
    hid = new HidLink({
      onKey: (k, down) => (down ? press(k) : release(k)),
      // 0x81 的 dx/dy 已在固件内完成零偏、死区、平滑与加速：逐帧直接应用，不再二次平滑。
      onMotion: (dx, dy) => movePointer(dx, dy),
      onLog: (t, c) => log(t, c),
      onCaps: ({ audio, haptic, calibrated }) => {
        const miss = [!haptic && '触觉', !audio && '设备麦克风'].filter(Boolean);
        $('#capsNote').textContent = (calibrated ? '陀螺仪已校准' : '陀螺仪未校准，请静置手柄') + (miss.length ? ` · ${miss.join('、')}：本固件档暂不可用（屏幕上仍显示示意）` : '');
      },
      onState: ({ phase, text }) => {
        linkStatus.textContent = text; ownerBadge.textContent = phase === 'host' ? '灵动岛接管' : phase === 'pointer' ? '普通鼠标' : '未连接';
        if (phase === 'lost' || phase === 'error') { grammar.reset(now()); hid = null; setLink('sim'); simOn = true; linkStatus.textContent = text + '；已回到键鼠模拟。'; }
      },
    });
    await hid.connect(); simOn = false; setLink('hid');
  } catch (err) { hid = null; linkStatus.textContent = '未连接：' + err.message; }
};
function setLink(mode) {
  $('#useSim').classList.toggle('on', mode === 'sim'); $('#useHid').classList.toggle('on', mode === 'hid');
  linkBadge.textContent = mode === 'sim' ? '模拟手柄' : 'AI KEY · USB'; linkBadge.className = 'badge ' + (mode === 'sim' ? 'sim' : 'live');
  if (mode === 'sim') { $('#capsNote').textContent = ''; linkStatus.textContent = '鼠标 = 陀螺仪指向；左键 = L，右键 = R；按住 D = S 背键，按住空格 = V 背键。'; ownerBadge.textContent = '待命'; }
}

// ---------- 导演模式 ----------
let directing = false;
const playAll = $('#playAll'), playScene = $('#playScene'), stopBtn = $('#stopDemo');
function check() { if (cancelToken.stopped) throw new Error('stop'); }
const d = {
  app, caption, sleep,
  async wait(ms) { check(); await sleep(ms); check(); },
  async move(x, y, ms = 600) {
    check(); const x0 = pointer.x, y0 = pointer.y, n = Math.max(2, Math.round(ms / 16));
    for (let i = 1; i <= n; i++) { check(); const t = i / n, e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; setPointer(x0 + (x - x0) * e, y0 + (y - y0) * e); await sleep(16); }
  },
  async path(points, ms) {
    const seg = ms / Math.max(1, points.length - 1);
    for (const p of points) await this.move(p.x, p.y, seg);
  },
  async tap(k, hold = 90) { check(); press(k); await sleep(hold); release(k); await sleep(120); },
  async hold(k, ms) { check(); press(k); await sleep(ms); release(k); },
  async draw(points, ms = 1400) {
    await this.move(points[0].x, points[0].y, 500); press('S'); await sleep(240);
    try { await this.path(points.slice(1), ms); } finally { release('S'); }
    await sleep(400);
  },
  async say(text, ms) {
    check(); app.demoUtterance = text; press('V');
    try { await sleep(ms ?? 380 + text.length * 95 + 500); } finally { release('V'); }
    await this.until(() => app.phase !== 'busy' && !busy, 20000);
  },
  async until(pred, ms = 15000) { const t0 = now(); while (!pred()) { check(); if (now() - t0 > ms) return; await sleep(80); } },
  enter: (i) => enter(i, { quiet: true }),
  press, release,
};
async function direct(list) {
  if (directing) return;
  grammar.reset(now()); directing = true; cancelToken = { stopped: false };
  playAll.hidden = playScene.hidden = true; stopBtn.hidden = false; inner.style.cursor = 'none';
  try { for (const step of list) await step(d); }
  catch (e) { if (e.message !== 'stop') console.error(e); }
  finally {
    grammar.reset(now()); directing = false; app.demoUtterance = '';
    playAll.hidden = playScene.hidden = false; stopBtn.hidden = true;
    if (menu) closeMenu(false);
  }
}
function stopDemo() { cancelToken.stopped = true; caption('已停止演示', '继续用鼠标、空格（V）与 D（S）自由体验'); }
playAll.onclick = () => direct([INTRO, ...SCENES.map((s, i) => async (dd) => { if (i) await flowTo(dd, i); else enter(0, { quiet: true }); await s.demo(dd); }), OUTRO]);
playScene.onclick = () => { const i = app.sceneIndex; direct([async (dd) => { enter(i, { quiet: true }); await SCENES[i].demo(dd); }]); };
stopBtn.onclick = stopDemo;
// 用灵动岛流转到下一幕：S 短按 → 倾斜 → L
async function flowTo(dd, i) {
  await dd.wait(500); await dd.move(640, 300, 500);
  await dd.tap('S'); await dd.wait(500);
  const steps = i - app.sceneIndex;
  for (let k = 0; k < Math.abs(steps); k++) { await dd.move(pointer.x + Math.sign(steps) * 75, pointer.y, 260); await dd.wait(160); }
  await dd.wait(450); await dd.tap('L'); await dd.wait(700);
}

// ---------- 主循环 ----------
function loop(t) { grammar.tick(t); tickListening(t); drawScope(t); drawAtt(); requestAnimationFrame(loop); }
requestAnimationFrame(loop);
setInterval(() => { const d0 = new Date(); $('#clock').textContent = `周五 ${String(d0.getHours()).padStart(2, '0')}:${String(d0.getMinutes()).padStart(2, '0')}`; }, 10000);

buildNav(); enter(0, { quiet: true }); island.idle();
caption('按 <b>S</b> 短按（键盘 D）打开灵动岛，或点「完整演示」', '鼠标在屏幕里移动＝倾斜手柄；按住空格＝背键 V 说话；按住 D＝背键 S 圈选');
window.__poc = { app, grammar, enter, direct, d };
