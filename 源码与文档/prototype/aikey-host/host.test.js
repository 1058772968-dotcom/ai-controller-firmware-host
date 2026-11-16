// 对端是固件同一份 C 代码（tests/host/devcfg_shim.c + aikey_core），不是 JS 自己对自己。
import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { OP, DEFAULT_CFG, ConfigClient, buildFrame, parseReply, encodeCfg, decodeCfg, encodeTone, cfgProblems } from './devcfg.js';
import { deriveAxes, integrate, summarizeStill } from './axes.js';
import { parseLine, LineSplitter, CDC_BAUD, Telemetry } from './telemetry.js';
import { runWizard } from './wizard.js';
import { HidLink } from '../island-poc/devices.js';
import { CMD, EVT, crc16, decodeReport } from '../island-poc/protocol.js';
import { SimDevice } from './sim.js';
import { pickMic } from './miccap.js';
import { TESTS, judgeMic, judgeResponse, judgeClosed, judgeRecord, judgeTelemetry, SegmentStats, wavBytes, report } from './bench.js';

const E24 = fileURLToPath(new URL('../../engineering/e24/', import.meta.url));
const CORE = join(E24, 'firmware/components/aikey_core');
const dir = mkdtempSync(join(tmpdir(), 'aikey-host-'));
const bin = join(dir, 'shim');
after(() => rmSync(dir, { recursive: true, force: true }));
const built = spawnSync('cc', ['-std=c11', '-O1', `-I${CORE}/include`, join(E24, 'tests/host/devcfg_shim.c'), ...['controller', 'pointer', 'protocol', 'devcfg'].map((n) => join(CORE, n + '.c')), '-lm', '-o', bin], { encoding: 'utf8' });
assert.equal(built.status, 0, built.stderr);

const hex = (b) => Buffer.from(b).toString('hex');
const unhex = (s) => new Uint8Array(Buffer.from(s, 'hex'));
function shim() {
  const p = spawn(bin, [], { stdio: ['pipe', 'pipe', 'inherit'] }), waiters = [];
  const rl = createInterface({ input: p.stdout });
  rl.on('line', (l) => waiters.shift()?.(l));
  const cmd = (line) => new Promise((res) => { waiters.push(res); p.stdin.write(line + '\n'); });
  return {
    cmd, close() { p.stdin.end(); rl.close(); },
    async session() { return decodeReport(unhex((await cmd('status')).slice(2))).session; },
    async cfg(frame) { return parseReply(unhex((await cmd('cfg ' + hex(frame))).slice(2))); },
    async feed(g, a, n) { const f = (await cmd(`feed ${g.join(' ')} ${a.join(' ')} ${n}`)).split(' '); return { dx: +f[1], dy: +f[2], state: +f[3] }; },
  };
}

test('读参数：固件默认值与 DEFAULT_CFG 一致', async () => {
  const s = shim(), session = await s.session();
  const r = await s.cfg(buildFrame(OP.GET, session, 7));
  assert.equal(r.code, 0); assert.equal(r.tx, 7); assert.equal(r.op, OP.GET); assert.equal(r.session, session);
  assert.deepEqual(r.cfg, DEFAULT_CFG);
  s.close();
});
test('写参数：500 组随机值经固件量化后，回显与本地编码逐字节相同', async () => {
  const s = shim(), session = await s.session();
  let seed = 12345; const rnd = (lo, hi) => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return lo + (seed / 0x7fffffff) * (hi - lo); };
  const perms = [[0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]];
  for (let i = 0; i < 500; i++) {
    const accelLo = Math.round(rnd(0, 200)), smoothLo = Math.round(rnd(0, 100));
    const c = { sens: rnd(1, 200), accel: rnd(1, 4), accelLo, accelHi: Math.min(510, accelLo + 2 + Math.round(rnd(0, 300)) * 2), deadzone: rnd(0, 5), smoothLo, smoothHi: smoothLo + Math.round(rnd(0, 150)), tau: rnd(0, 200), freeze: Math.round(rnd(0, 255)), invertX: i % 2 === 0, invertY: i % 3 === 0, gravity: i % 5 !== 0, axisSrc: perms[i % 6], axisNeg: i % 8 };
    assert.deepEqual(cfgProblems(c), []);
    const w = encodeCfg(c), r = await s.cfg(buildFrame(OP.SET, session, i + 1, w));
    assert.equal(r.code, 0, JSON.stringify(c));
    assert.deepEqual([...r.cfgBytes], [...w]);
    assert.deepEqual([...encodeCfg(r.cfg)], [...w], '回显解码后再编码必须不变');
  }
  s.close();
});
test('固件拒绝的情况：越界、保留位、session、CRC、存储失败', async () => {
  const s = shim(), session = await s.session();
  const bad = (patch) => encodeCfg({ ...DEFAULT_CFG, ...patch });
  for (const p of [{ sens: 0.5 }, { accel: 4.5 }, { accelLo: 250, accelHi: 250 }, { deadzone: 5.5 }, { smoothLo: 20, smoothHi: 10 }, { tau: 201 }, { axisSrc: [0, 0, 2] }]) {
    assert.equal((await s.cfg(buildFrame(OP.SET, session, 1, bad(p)))).code, 3, JSON.stringify(p));
    assert.ok(cfgProblems({ ...DEFAULT_CFG, ...p }).length, '本地也要拦下：' + JSON.stringify(p));
  }
  const rsv = encodeCfg(DEFAULT_CFG); rsv[14] = 1;
  assert.equal((await s.cfg(buildFrame(OP.SET, session, 2, rsv))).code, 3);
  assert.equal((await s.cfg(buildFrame(OP.GET, session + 1, 3))).code, 2);
  const f = buildFrame(OP.GET, session, 4); f[9] ^= 1;
  assert.equal((await s.cfg(f)).code, 1);
  await s.cmd('savefail 1');
  assert.equal((await s.cfg(buildFrame(OP.SAVE, session, 5))).code, 4);
  await s.cmd('savefail 0');
  assert.equal((await s.cfg(buildFrame(OP.SAVE, session, 6))).code, 0);
  const tel = new Uint8Array(16); tel[0] = 1;
  assert.equal((await s.cfg(buildFrame(OP.TEL, session, 7, tel))).telemetry, true);
  const dfu = new Uint8Array(16); dfu.set([0x44, 0x46, 0x55, 0x21]);
  assert.equal((await s.cfg(buildFrame(OP.DFU, session, 8, dfu))).code, 0);
  s.close();
});

// 24 种安装方向：sensor = R · device。
function rotations() {
  const out = [], perms = [[0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]], parity = [1, -1, -1, 1, 1, -1];
  perms.forEach((p, k) => { for (const s0 of [1, -1]) for (const s1 of [1, -1]) { const s2 = parity[k] * s0 * s1; out.push({ p, s: [s0, s1, s2] }); } });
  return out; // 设备第 i 轴 = 传感器第 p[i] 轴 × s[i]
}
const toSensor = ({ p, s }, d) => { const v = [0, 0, 0]; for (let i = 0; i < 3; i++) v[p[i]] = s[i] * d[i]; return v; };

test('轴向推导：24 种安装方向写进固件后，右转光标向右、抬头光标向上', async () => {
  assert.equal(rotations().length, 24);
  for (const R of rotations()) {
    const s = shim(), session = await s.session();
    const up = toSensor(R, [0, 0, 1]);
    const axes = deriveAxes(up, toSensor(R, [0, 1, 0]));
    assert.deepEqual(axes.axisSrc, R.p);
    const r = await s.cfg(buildFrame(OP.SET, session, 1, encodeCfg({ ...DEFAULT_CFG, ...axes })));
    assert.equal(r.code, 0);
    assert.equal((await s.feed([0, 0, 0], up, 300)).state, 2, '静置后校准完成');
    const right = await s.feed(toSensor(R, [0, 0, -60]), up, 40);
    assert.ok(right.dx > 100 && Math.abs(right.dy) < right.dx / 10, JSON.stringify({ R, right }));
    const lift = await s.feed(toSensor(R, [60, 0, 0]), up, 40);
    assert.ok(lift.dy < -100 && Math.abs(lift.dx) < -lift.dy / 10, JSON.stringify({ R, lift }));
    s.close();
  }
});
test('轴向推导：与 e24ctl.py 的 derive_axes 结果一致', { skip: !existsSync(join(E24, 'tools/e24ctl.py')) }, () => {
  const cases = rotations().map((R) => [toSensor(R, [0, 0, 1]), toSensor(R, [0, 1, 0])]);
  const py = `import json,sys\nsys.path.insert(0,${JSON.stringify(join(E24, 'tools'))})\nfrom e24ctl import derive_axes\nprint(json.dumps([derive_axes(a,b) for a,b in json.load(sys.stdin)]))`;
  const r = spawnSync('python3', ['-B', '-c', py], { input: JSON.stringify(cases), encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  JSON.parse(r.stdout).forEach(([src, neg], i) => { const a = deriveAxes(...cases[i]); assert.deepEqual(a.axisSrc, src); assert.equal(a.axisNeg, neg); });
});
test('轴向推导：姿势不合格时报错，不写入', () => {
  assert.throws(() => deriveAxes([0, 0, 1], [0, 0, 1]), /同一个传感器轴/);
  assert.throws(() => deriveAxes([0, 0, 0.5], [0, 1, 0]), /不像静止/);
  assert.throws(() => deriveAxes([0, 0.7, 0.7], [0, 1, 0]), /单一轴/);
  assert.throws(() => summarizeStill([]), /样本太少/);
});

test('遥测解析：只收完整的 imu 行，日志和断行不混入', () => {
  const ok = '{"v":1,"type":"imu","t":12345,"dt":0.0050,"g":[0.12,-0.40,3.10],"a":[0.010,0.020,0.998],"h":3.05,"vv":-0.10,"dx":1,"dy":0,"bias":[1.20,-0.80,0.50],"cal":2,"still":0}';
  assert.equal(parseLine(ok + '\r').kind, 'imu');
  assert.equal(parseLine('I (123) e24: 陀螺仪已校准').kind, 'log');
  assert.equal(parseLine('\x1b[0;32mI (77869) e24: 遥测 开\x1b[0m\r').text, 'I (77869) e24: 遥测 开');
  assert.equal(parseLine('{"v":1,"type":"imu","t":1I (123) e24: 日志插进来').kind, 'drop');
  assert.equal(parseLine('{"v":1,"type":"imu","t":1,"g":[1,2],"a":[0,0,1],"h":0,"vv":0}').kind, 'drop');
  assert.equal(parseLine('{"v":2,"type":"imu"}').kind, 'drop');
  assert.equal(parseLine('').kind, 'empty');
  const got = []; const sp = new LineSplitter((l) => got.push(l));
  sp.push('ab'); sp.push('c\nde\nf'); assert.deepEqual(got, ['abc', 'de']);
  sp.push('x'.repeat(5000)); sp.push('\n'); assert.equal(got.at(-1), '', '超长残行被丢弃');
  assert.notEqual(CDC_BAUD, 1200);
});
test('积分：角速度对时间积分', () => {
  const s = Array.from({ length: 101 }, (_, i) => ({ t: i * 10, h: 30 }));
  assert.ok(Math.abs(integrate(s, 'h') - 30) < 1e-9);
});

function bench() {
  const sent = [];
  const c = new ConfigClient({ send: (b) => { sent.push(b); return true; }, getSession: () => bench.session, timeoutMs: 30 });
  const reply = (frame, code = 0) => { const b = new Uint8Array(32); b[0] = 1; b[1] = frame[1] | 0x80; b[2] = code; b.set(frame.slice(4, 12), 4); b.set(encodeCfg(DEFAULT_CFG), 12); const k = crc16(b, 30); b[30] = k & 0xff; b[31] = k >> 8; return b; };
  return { c, sent, reply };
}
const tick = () => new Promise((r) => setTimeout(r, 0));
test('请求队列：一次一帧，错配回复不算数，session 换了重发一次', async () => {
  bench.session = 5;
  const { c, sent, reply } = bench();
  const p1 = c.get(), p2 = c.save();
  await tick(); assert.equal(sent.length, 1, '第二帧要等第一帧回来');
  const wrong = reply(sent[0]); wrong[8] ^= 1; const k = crc16(wrong, 30); wrong[30] = k & 0xff; wrong[31] = k >> 8;
  c.onReply(wrong); await tick(); assert.equal(sent.length, 1);
  c.onReply(reply(sent[0])); await p1; await tick();
  assert.equal(sent.length, 2); assert.equal(sent[1][1], OP.SAVE);
  bench.session = 6;
  c.onReply(reply(sent[1], 2)); await tick();
  assert.equal(sent.length, 3); assert.equal(sent[2][4], 6, '用新 session 重发');
  c.onReply(reply(sent[2])); await p2;
});
test('请求队列：超时报错后后续还能用；失败原因是中文', async () => {
  bench.session = 5;
  const { c, sent, reply } = bench();
  await assert.rejects(c.get(), /没有回复/);
  const p = c.save(); await tick();
  c.onReply(reply(sent.at(-1), 4));
  await assert.rejects(p, /保存失败/);
  await assert.rejects(c.set({ ...DEFAULT_CFG, sens: 0 }), /灵敏度/);
  bench.session = null;
  await assert.rejects(c.get(), /还没收到设备状态/);
});
test('滑块连拖：只发最新一份', async () => {
  bench.session = 5;
  const { c, sent, reply } = bench(), done = [];
  for (const sens of [10, 11, 12, 13]) c.setLive({ ...DEFAULT_CFG, sens }, (e, r) => done.push(r?.op));
  await tick(); assert.equal(sent.length, 1);
  c.onReply(reply(sent[0])); await tick(); await tick();
  assert.equal(sent.length, 2); assert.equal(decodeCfg(sent[1].slice(12, 28)).sens, 13);
  c.onReply(reply(sent[1])); await tick(); await tick();
  assert.equal(sent.length, 2); assert.equal(done.length, 2);
});

function hidBench() {
  const sent = [], keys = [];
  const dev = new SimDevice({ mount: null });
  const link = new HidLink({ autoClaim: false, onKey: (k, d) => keys.push(k + (d ? '↓' : '↑')), onMotion() {}, onState() {}, onLog() {}, transport: { sendReport: async (id, b) => { sent.push([id, b[1]]); dev.sendReport(id, b); } } });
  dev.onReport = (id, b) => { if (id === 2) link.receive(b); };
  return { sent, keys, dev, link };
}
test('仅调参：不发 HELLO/CLAIM；接管后才转发按键；交还后回普通鼠标', async () => {
  const { sent, keys, dev, link } = hidBench();
  dev.status(); dev.press('L', true); dev.press('L', false); await tick();
  assert.deepEqual(sent, [], '调参模式不抢系统鼠标'); assert.deepEqual(keys, []); assert.equal(link.owner, 'POINTER');
  link.takeHost(); await tick(); await tick();
  assert.deepEqual(sent.map((s) => s[1]).slice(0, 2), [CMD.HELLO, CMD.CLAIM]); assert.equal(link.owner, 'HOST');
  dev.press('S', true); await tick(); assert.deepEqual(keys, ['S↓']);
  link.releaseHost(); await tick(); await tick();
  assert.equal(sent.at(-1)[1], CMD.RELEASE); assert.equal(link.owner, 'POINTER'); assert.deepEqual(keys, ['S↓', 'S↑']);
  assert.equal(dev.leaseActive(), false);
  link.stopKeepalive(); clearTimeout(link.helloTimer); dev.stop();
});
test('租约到期被动交还：按住的键要松开', () => {
  const keys = [];
  const link = new HidLink({ onKey: (k, d) => keys.push(k + (d ? '↓' : '↑')), onMotion() {}, onState() {}, onLog() {}, transport: { sendReport: async () => {} } });
  const report = (owner, buttons) => { const b = new Uint8Array(32); b[0] = 1; b[1] = EVT.STATUS; b[2] = owner; b[3] = buttons; b[4] = 5; const k = crc16(b, 30); b[30] = k & 0xff; b[31] = k >> 8; return b; };
  link.receive(report(1, 8)); assert.deepEqual(keys, ['S↓']);
  link.receive(report(0, 8)); assert.deepEqual(keys, ['S↓', 'S↑']);
  link.stopKeepalive(); clearTimeout(link.helloTimer);
});

test('轴向向导全流程：错位安装的虚拟手柄写入后核对通过', async () => {
  const dev = new SimDevice({ mount: { p: [1, 2, 0], s: [1, -1, -1] }, speed: 20 });
  const client = new ConfigClient({ send: (b) => { dev.sendReport(3, b); return true; }, getSession: () => dev.session, timeoutMs: 200 });
  dev.onReport = (id, b) => { if (id === 3) client.onReply(b); };
  const samples = new Set();
  dev.onLine = (l) => { const p = parseLine(l); if (p.kind === 'imu') for (const c of samples) c.push(p.data); };
  const tel = { collect: async (ms) => { const o = []; samples.add(o); await new Promise((r) => setTimeout(r, ms)); samples.delete(o); return o; } };
  dev.start();
  const seen = [];
  const ui = { note: (t) => seen.push(t), step: async (s) => { seen.push(s.id); dev.act(s.id); } };
  const cfg = (await client.get()).cfg;
  const res = await runWizard({ cfg, client, tel, ui, captureMs: 150, moveMs: 350, tickMs: 10 });
  dev.stop();
  assert.deepEqual(res.axes.axisSrc, [1, 2, 0]);
  assert.equal(res.passed, true, JSON.stringify(res.checks));
  assert.deepEqual(seen.filter((x) => !x.includes(' ') && !x.includes('：')), ['flat', 'noseUp', 'rest', 'right', 'up']);
  assert.equal(res.applied.invertX, false);
});

test('WebHID 接线：报告 2、3 分流，带偏移的 DataView 也能读对', async () => {
  Object.defineProperty(navigator, 'hid', { value: { addEventListener() {}, removeEventListener() {} }, configurable: true });
  let handler; const sent = [], cfgs = [], stat = [];
  const dev = { opened: false, productName: 'AI KEY E24', open: async () => { dev.opened = true; }, close: async () => {}, addEventListener: (_, f) => { handler = f; }, sendReport: async (id, b) => sent.push([id, b.length]) };
  const link = new HidLink({ autoClaim: false, onKey() {}, onMotion() {}, onState() {}, onLog() {}, onConfig: (b) => cfgs.push(b), onStatus: (r) => stat.push(r.session) });
  await link.connect(dev);
  const wrap = (b) => { const buf = new Uint8Array(40); buf.set(b, 5); return new DataView(buf.buffer, 5, 32); };
  const st = new SimDevice({ mount: null }).frame(EVT.STATUS);
  handler({ reportId: 2, data: wrap(st) });
  assert.equal(stat.length, 1); assert.equal(link.session, 0x5a17e24);
  handler({ reportId: 3, data: wrap(buildFrame(OP.GET, 1, 2)) });
  assert.equal(cfgs.length, 1); assert.equal(cfgs[0][1], OP.GET);
  handler({ reportId: 1, data: wrap(st) });
  assert.equal(stat.length, 1, '报告 1 不处理');
  assert.equal(await link.sendConfig(buildFrame(OP.GET, 1, 3)), true);
  assert.deepEqual(sent, [[3, 32]]);
  delete navigator.hid;
});
test('Web Serial 接线：115200、打开 DTR、跨块拼行；打不开时说清原因', async () => {
  Object.defineProperty(navigator, 'serial', { value: {}, configurable: true });
  const enc = new TextEncoder(), line = '{"v":1,"type":"imu","t":1,"g":[0,0,0],"a":[0,0,1],"h":1,"vv":2}\n';
  const chunks = [line.slice(0, 10), line.slice(10) + 'I (5) e24: 日', '志\n{"broken\n'];
  const opened = [], sig = [], got = [], logs = [];
  const port = {
    open: async (o) => opened.push(o), close: async () => {}, setSignals: async (s) => sig.push(s),
    readable: new ReadableStream({ start(c) { for (const k of chunks) c.enqueue(enc.encode(k)); c.close(); } }),
  };
  const t = new Telemetry({ onSample: (d) => got.push(d.vv), onLog: (l) => logs.push(l), onState() {} });
  await t.connect(port);
  await new Promise((r) => setTimeout(r, 20));
  assert.deepEqual(opened, [{ baudRate: 115200 }]); assert.deepEqual(sig, [{ dataTerminalReady: true }]);
  assert.deepEqual(got, [2]); assert.deepEqual(logs, ['I (5) e24: 日志']); assert.equal(t.dropped, 1);
  const busy = new Telemetry({});
  await assert.rejects(busy.connect({ open: async () => { throw new Error('Failed to open'); } }), /被 screen 或 e24ctl 占用/);
  delete navigator.serial;
});

// ---------- 逐项测试 ----------
function benchRig({ speed = 20, dead = '' } = {}) {
  const sim = new SimDevice({ speed }); sim.keysDead = dead;
  let waiters = [], lastReport = null;
  const hooks = { autoClaim: false, onKey() {}, onCaps() {}, onMotion() {}, onLog() {}, onState() {},
    onConfig: (b) => client.onReply(b), onStatus(r) { lastReport = r; waiters = waiters.filter((w) => { if (!w.test(r)) return true; clearTimeout(w.t); w.res(r); return false; }); } };
  const hid = new HidLink({ ...hooks, transport: sim });
  const client = new ConfigClient({ send: (b) => hid.sendConfig(b), getSession: () => hid.session });
  sim.onReport = (id, b) => (id === 2 ? hid.receive(b) : client.onReply(b));
  const says = [];
  const ctx = {
    hid, client, now: () => performance.now(), last: () => lastReport, level() {},
    sleep: (ms) => new Promise((r) => setTimeout(r, ms / speed)),
    waitReport: (test, ms, msg = '超时') => new Promise((res, rej) => { const w = { test, res, t: setTimeout(() => { waiters = waiters.filter((x) => x !== w); rej(new Error(msg)); }, ms / speed + 300) }; waiters.push(w); }),
    say: (t) => says.push(t), capture: () => sim.capture(), expectSound: () => sim.clap(),
    toneParams: () => ({ hz: 1000, ms: 200, atten: 50 }), ask: async () => 0,
    telemetry: async () => ({ count: 300, hz: 99, dropped: 0 }),
  };
  sim.start();
  return { sim, ctx, says, stop: () => sim.stop(), test: (id) => TESTS.find((t) => t.id === id) };
}
const nap = (ms) => new Promise((r) => setTimeout(r, ms));

test('逐项测试：判定函数', () => {
  assert.equal(judgeMic({ testValid: true, rxErrors: 0, leftPct: 99, rightPct: 0, rmsDb: -59, peakDb: -44 }).pass, true);
  assert.match(judgeMic({ testValid: true, rxErrors: 0, leftPct: 0, rightPct: 0, rmsDb: -120, peakDb: -120 }).text, /U3/);
  assert.match(judgeMic({ testValid: true, rxErrors: 0, leftPct: 99, rightPct: 99, rmsDb: -50, peakDb: -40 }).text, /SELECT/);
  assert.equal(judgeMic({ testValid: true, rxErrors: 2, leftPct: 99, rightPct: 0, rmsDb: -50, peakDb: -40 }).pass, false);
  assert.equal(judgeResponse({ peakDb: -44 }, { peakDb: -20 }).pass, true);
  assert.equal(judgeResponse({ peakDb: -44 }, { peakDb: -40 }).pass, false);
  assert.equal(judgeClosed({ samples: 32000, nonzero: 0, peak: 0, streaming: true, gate: false }).pass, true);
  assert.equal(judgeClosed({ samples: 32000, nonzero: 3, peak: 0.1, streaming: true, gate: false }).pass, false);
  assert.match(judgeClosed({ samples: 32000, nonzero: 0, peak: 0, streaming: false, gate: false }).text, /不算数/); // 假通过防护
  assert.equal(judgeClosed({ samples: 100, nonzero: 0, peak: 0, streaming: true, gate: false }).pass, false);
  assert.equal(judgeTelemetry({ hz: 98, dropped: 0, count: 300 }).pass, true);
  assert.equal(judgeTelemetry({ hz: 50, dropped: 0, count: 150 }).pass, false);
  assert.equal(judgeTelemetry({ hz: 99, dropped: 2, count: 300 }).pass, false);
  const seg = (nz) => { const s = new SegmentStats(); s.add(new Float32Array(1000).fill(nz ? 0.1 : 0)); return s; };
  const rec = (o) => judgeRecord({ opened: true, before: seg(0), during: seg(1), after: seg(0), durationMs: 2000, ...o });
  assert.equal(rec({}).pass, true);
  assert.equal(rec({ before: seg(1) }).pass, false);
  assert.equal(rec({ after: seg(1) }).pass, false);
  assert.equal(rec({ during: seg(0) }).pass, false);
  assert.equal(rec({ durationMs: 100 }).pass, false);
  assert.equal(rec({ opened: false }).pass, false);
});
test('逐项测试：WAV 头和样本', () => {
  const b = wavBytes([new Float32Array([0, 1, -1])]), d = new DataView(b.buffer);
  assert.equal(String.fromCharCode(...b.slice(0, 4)), 'RIFF'); assert.equal(d.getUint32(24, true), 16000); assert.equal(d.getUint32(40, true), 6);
  assert.deepEqual([d.getInt16(44, true), d.getInt16(46, true), d.getInt16(48, true)], [0, 32767, -32768]);
});
test('逐项测试：虚拟手柄走完连接、麦克风、闸门、提示音', async () => {
  const g = benchRig(); await nap(150);
  assert.equal((await g.test('conn').run(g.ctx)).pass, true);
  assert.equal((await g.test('cal').run(g.ctx)).pass, true);
  assert.equal((await g.test('mic').run(g.ctx)).pass, true);
  assert.equal((await g.test('micLoud').run(g.ctx)).pass, true);
  assert.equal((await g.test('gate').run(g.ctx)).pass, true);
  assert.equal((await g.test('tone').run(g.ctx)).pass, true);
  g.stop();
});
test('逐项测试：四键全按才通过，缺键点名焊盘，结束后交还控制权', async () => {
  let g = benchRig(); await nap(150);
  let p = g.test('keys').run(g.ctx); await nap(120);
  assert.equal(g.ctx.hid.owner, 'HOST');
  for (const k of 'LRVS') { g.sim.press(k, true); await nap(30); g.sim.press(k, false); await nap(30); }
  assert.equal((await p).pass, true); await nap(50);
  assert.equal(g.ctx.hid.owner, 'POINTER'); g.stop();
  g = benchRig({ speed: 2000, dead: 'V' }); await nap(150);
  p = g.test('keys').run(g.ctx); await nap(120);
  for (const k of 'LRS') { g.sim.press(k, true); await nap(20); g.sim.press(k, false); await nap(20); }
  g.ctx.now = () => performance.now() + 1e6; // 时间到
  g.sim.status();
  const r = await p; assert.equal(r.pass, false); assert.match(r.text, /V → J7/); g.stop();
});
test('逐项测试：真实录音路径，只有按住 V 才有声音，松键归零，可回放', async () => {
  const g = benchRig({ speed: 1 }); await nap(150);
  const p = g.test('record').run(g.ctx); await nap(400);
  assert.equal(g.ctx.hid.owner, 'HOST');
  g.sim.press('V', true); await nap(900);
  assert.equal(g.sim.micReady, true);
  g.sim.press('V', false); assert.equal(g.sim.micReady, false);
  const r = await p; g.stop();
  assert.equal(r.pass, true, r.text); assert.ok(r.wav.length > 44);
});
test('逐项测试：旧固件不响应音频命令时说清楚', async () => {
  const g = benchRig(); await nap(150);
  const c = g.ctx.client, orig = c.audio; c.audio = () => Promise.reject(new Error('读音频状态：800 ms 内没有回复'));
  const r = await g.test('conn').run(g.ctx);
  assert.equal(r.pass, false); assert.match(r.text, /旧固件/); c.audio = orig; g.stop();
});
test('逐项测试：报告列出每项状态和板号', () => {
  const t = report({ conn: { pass: true, text: 'ok' }, keys: { pass: false, text: '没收到 V' }, mic: { skipped: true } }, 'd3:bc');
  assert.match(t, /板子 d3:bc/); assert.match(t, /通过 {2}连接与固件：ok/); assert.match(t, /不通过 {2}四键：没收到 V/); assert.match(t, /跳过 {2}麦克风电平/); assert.match(t, /未测 {2}真实录音/);
});
test('POC 档：两种设备名都能选中，闸门项报不适用而不是隐私故障', async () => {
  const mic = (label) => ({ kind: 'audioinput', label });
  assert.equal(pickMic([mic('MacBook'), mic('AI KEY Mic POC')]).label, 'AI KEY Mic POC');
  assert.equal(pickMic([mic('Held-key microphone')]).label, 'Held-key microphone');
  assert.equal(pickMic([mic('MacBook'), { kind: 'audiooutput', label: 'AI KEY Mic POC' }]), undefined);
  let closed = 0;
  const ctx = { capture: async () => ({ poc: true, close: async () => { closed++; } }) };
  for (const id of ['gate', 'record']) {
    const r = await TESTS.find((t) => t.id === id).run(ctx);
    assert.equal(r.skipped, true); assert.match(r.text, /不适用/);
  }
  assert.equal(closed, 2, '取到的流要关掉');
});
test('音频状态解码与固件一致', async () => {
  const s = shim(), session = await s.session();
  const r = await s.cfg(buildFrame(OP.AUDIO, session, 9));
  assert.equal(r.code, 0); assert.equal(r.cfg, null);
  assert.equal(r.audio.clock, true); assert.equal(r.audio.testValid, true); assert.equal(r.audio.leftPct, 99); assert.equal(r.audio.rmsDb, -55.92); assert.equal(r.audio.peakDb, -35.68); assert.equal(r.audio.frames, 32000); assert.equal(r.audio.rxErrors, 1); assert.equal(r.audio.uacOverflow, 2);
  const t = await s.cfg(buildFrame(OP.TONE, session, 10, encodeTone(1000, 200, 50))); assert.equal(t.code, 0);
  const bad = await s.cfg(buildFrame(OP.TONE, session, 11, encodeTone(1000, 200, 10))); assert.equal(bad.code, 3); // 音量超上限，固件拒绝
  s.close();
});
