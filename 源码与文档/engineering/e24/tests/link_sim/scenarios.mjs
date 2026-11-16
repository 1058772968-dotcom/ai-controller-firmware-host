// 场景。每条检查写的是“联调时应该成立的行为”，所以当前失败 = 问题重现；修好后全绿，这份脚本就是回归门槛。
import { load } from './harness.mjs';

const { HidLink } = await load('island-poc/devices.js');
const { ConfigClient, DEFAULT_CFG } = await load('aikey-host/devcfg.js');
const { Telemetry } = await load('aikey-host/telemetry.js');
const { runWizard } = await load('aikey-host/wizard.js');
const { CMD } = await load('island-poc/protocol.js');

// 与 prototype/aikey-host/main.js 的 hooks()、status() 同样的接法
async function host(b, { autoClaim = false, existing } = {}) {
  const h = { keys: [], motion: [0, 0], frames: 0, states: [], logs: [], session: null, last: null, caps: null };
  h.link = new HidLink({
    autoClaim,
    onKey: (k, d) => h.keys.push([k, d]),
    onMotion: (dx, dy) => { h.motion[0] += dx; h.motion[1] += dy; h.frames++; },
    onCaps: (c) => { h.caps = c; },
    onLog: (t, c) => h.logs.push({ t: b.ms, text: t, c }),
    onConfig: (x) => h.client.onReply(x),
    onStatus: (r) => { h.session = r.session; h.last = r; },
    onState: (s) => h.states.push({ t: b.ms, ...s }),
  });
  h.client = new ConfigClient({ send: (x) => h.link.sendConfig(x), getSession: () => h.session, onLog: () => {} });
  await b.wait(h.link.connect(existing));
  await b.until(() => h.session !== null, 500);
  return h;
}
const hostIs = (h) => () => h.link.owner === 'HOST';
const hellos = (b, from = 0) => b.outLog.filter((o) => o.id === 2 && o.cmd === CMD.HELLO && o.t >= from).length;
const yawRight = (dps) => [0, 0, -dps];   // 平放时绕设备 Z 负向 = 向右转
const near = (v, want, tol) => Math.abs(v - want) <= tol;

function parseReportDesc(d) {
  const out = {}; let page = 0, usage = 0, id = 0, size = 0, count = 0, depth = 0, top = null;
  for (let i = 0; i < d.length;) {
    const h = d[i++], n = [0, 1, 2, 4][h & 3], tag = h & 0xfc; let v = 0;
    for (let k = 0; k < n; k++) v |= d[i + k] << (8 * k);
    i += n;
    if (tag === 0x04) page = v; else if (tag === 0x08) usage = v; else if (tag === 0x84) id = v; else if (tag === 0x74) size = v; else if (tag === 0x94) count = v;
    else if (tag === 0xa0) { if (!depth++) top = { page, usage }; } else if (tag === 0xc0) depth--;
    else if (tag === 0x80 || tag === 0x90) { const o = (out[id] ??= { top, in: 0, out: 0 }); o[tag === 0x80 ? 'in' : 'out'] += size * count; }
  }
  return out;
}

export const scenarios = [
  { id: 'A1', title: 'USB 描述符（usb_link.c 真实字节）', run: async (b, c) => {
    await b.tick(50);
    const { rep, cfg, dev } = await b.descriptors();
    const r = parseReportDesc(rep);
    c('ID1 鼠标集合 5 字节输入', r[1]?.in === 40 && r[1].top.page === 1 && r[1].top.usage === 2, JSON.stringify(r[1]));
    c('ID2 厂商集合 0xFF00/1，收发各 32 字节', r[2]?.in === 256 && r[2].out === 256 && r[2].top.page === 0xff00 && r[2].top.usage === 1, JSON.stringify(r[2]));
    c('ID3 厂商集合 0xFF00/3，收发各 32 字节', r[3]?.in === 256 && r[3].out === 256 && r[3].top.page === 0xff00 && r[3].top.usage === 3, JSON.stringify(r[3]));
    c('VID/PID/bcdDevice 与预案一致', dev.readUInt16LE(8) === 0xcafe && dev.readUInt16LE(10) === 0x4031 && dev.readUInt16LE(12) === 0x0124);
    c('配置描述符长度自洽', cfg.readUInt16LE(2) === cfg.length && cfg[4] === 5, `总长 ${cfg.length}，接口 ${cfg[4]}`);
  } },
  { id: 'A2', title: '上电、枚举、校准', run: async (b, c) => {
    await b.boot(); await b.tick(2000);
    const s = await b.read(), n = b.status.filter((x) => x.t > b.ms - 2000).length;
    c('状态报告约 10 Hz', n >= 19 && n <= 21, `2 s 内 ${n} 帧`);
    c('静置后完成校准', s.dev.calibrated === 1, `第 ${b.logs.find((l) => l.includes('已校准'))?.match(/\((\d+)\)/)?.[1]} ms`);
    c('未实现能力的故障位 = 触觉', s.dev.faults === 4);
    c('session 全程不变', b.sessions.length === 1, `${b.sessions.length} 个`);
    c('零偏估计接近注入值 0.4/-0.3/0.2', near(s.dev.bias[0], 0.4, 0.02) && near(s.dev.bias[1], -0.3, 0.02) && near(s.dev.bias[2], 0.2, 0.02), s.dev.bias.join(','));
  } },
  { id: 'A3', title: '不开上位机，当普通鼠标用', run: async (b, c) => {
    await b.boot();
    const t0 = b.ms; b.move(yawRight(30));
    await b.until(() => b.mouse.x !== 0, 200);
    c('转动后首个位移报告的固件内延迟', b.ms - t0 <= 15, `${b.ms - t0} ms（不含 USB 和系统）`);
    await b.tick(995); b.move([0, 0, 0]); await b.tick(300);
    c('转 30°：位移 ≈ 30×28 = 840 计数', near(b.mouse.x, 840, 45) && Math.abs(b.mouse.y) < 12, `x=${b.mouse.x} y=${b.mouse.y}`);
    const x0 = b.mouse.x; await b.tick(2000);
    c('静止不漂', Math.abs(b.mouse.x - x0) <= 1, `2 s 内 ${b.mouse.x - x0}`);
    const k0 = b.ms; b.key(1); await b.tick(40); c('按 L → 鼠标左键，去抖约 25 ms', b.mouse.b === 1 && near(b.mouse.edges[0].t - k0, 26, 3), `${b.mouse.edges[0].t - k0} ms`); b.key(0); await b.tick(40); c('松 L', b.mouse.b === 0);
  } },
  { id: 'A4', title: '调参通道（不接管）', run: async (b, c) => {
    await b.boot();
    const h = await host(b);
    const g = await b.wait(h.client.get());
    c('读回默认参数', g.cfg.sens === 28 && g.cfg.deadzone === 0.7 && g.cfg.accelHi === 250);
    const s = await b.wait(h.client.set({ ...g.cfg, sens: 33.337, deadzone: 0.84 }));
    c('写入后以设备回显为准（量化）', s.cfg.sens === 33.34 && s.cfg.deadzone === 0.8, JSON.stringify([s.cfg.sens, s.cfg.deadzone]));
    await b.wait(h.client.save());
    b.cmd('f nvs_fail 1');
    let e = ''; try { await b.wait(h.client.save()); } catch (x) { e = x.message; }
    c('NVS 失败给中文错误', e.includes('NVS'), e);
    b.cmd('f nvs_fail 0');
    await b.wait(h.client.calibrate());
    let st = (await b.wait(h.client.get())).state;
    c('校准中状态 = 1', st === 1, `state=${st}`);
    await b.tick(1300); st = (await b.wait(h.client.get())).state;
    c('静置 1.2 s 后恢复可用', st === 2, `state=${st}`);
    c('调参期间没发 HELLO/CLAIM', hellos(b) === 0 && h.link.owner === 'POINTER');
    b.move(yawRight(30)); await b.tick(500); b.move([0, 0, 0]); await b.tick(100);
    c('调参时系统光标照常动', b.mouse.x > 300, `x=${b.mouse.x}`);
    c('session 全程不变', b.sessions.length === 1);
  } },
  { id: 'A5', title: '接管 HOST、0x81 位移、交还', run: async (b, c) => {
    await b.boot();
    const h = await host(b);
    h.link.takeHost();
    const ms = await b.until(hostIs(h), 200);
    c('HELLO→CLAIM→HOST', ms >= 0 && ms < 30, `${ms} ms`);
    const x0 = b.mouse.reports, t1 = b.ms; b.move(yawRight(30));
    await b.until(() => h.frames > 0, 100);
    c('转动后首帧 0x81 的固件内延迟', b.ms - t1 <= 15, `${b.ms - t1} ms（不含 USB、浏览器）`);
    await b.tick(1000 - (b.ms - t1)); b.move([0, 0, 0]); await b.tick(300);
    c('0x81 位移守恒 ≈ 840', near(h.motion[0], 840, 45), `x=${h.motion[0]} y=${h.motion[1]}，${h.frames} 帧`);
    c('0x81 帧率不超过 250 Hz', h.frames <= 260, `${h.frames} 帧/s`);
    c('HOST 期间不发系统鼠标位移', b.mouse.reports - x0 <= 1, `${b.mouse.reports - x0} 个`);
    b.key(1); await b.tick(40); b.key(0); await b.tick(40);
    c('按键走事件，不走系统鼠标', h.keys.length === 2 && b.mouse.b === 0, JSON.stringify(h.keys));
    await b.tick(1000);
    const ka = (b.counts['out2:3'] ?? 0);
    c('KEEPALIVE 保活', ka >= 5 && h.link.owner === 'HOST', `${ka} 次`);
    h.link.recenter(); await b.tick(10);
    c('RECENTER 有 ACK', h.logs.some((l) => l.text.includes('RECENTER') && l.text.includes('OK')));
    h.link.releaseHost(); await b.tick(10);
    c('RELEASE 后立即回到系统鼠标', h.link.owner === 'POINTER' && (await b.read()).dev.owner === 0);
  } },
  { id: 'A6', title: '轴向向导全流程（错位安装，真实遥测）', run: async (b, c) => {
    b.mount = { p: [1, 2, 0], s: [1, -1, -1] }; b.dirty = true;
    await b.boot();
    const h = await host(b);
    const tel = new Telemetry({ onSample: () => { h.samples = (h.samples ?? 0) + 1; }, onLog: () => {} });
    await b.wait(tel.connect(b.port));
    const cfg = (await b.wait(h.client.get())).cfg;
    const acts = { flat: () => b.pose([0, 0, 1]), noseUp: () => b.pose([0, 1, 0]), rest: () => b.pose([0, 0, 1]),
      right: () => { b.pose([0, 0, 1]); b.move(yawRight(30)); setTimeout(() => b.move([0, 0, 0]), 1000); },
      up: () => { b.pose([0, 0, 1]); b.move([30, 0, 0]); setTimeout(() => b.move([0, 0, 0]), 1000); } };
    const ui = { step: (s) => new Promise((r) => { acts[s.id](); setTimeout(r, s.id === 'right' || s.id === 'up' ? 1 : 400); }), note: () => {} };
    const res = await b.wait(runWizard({ cfg, client: h.client, tel, ui }), 30000);
    c('向导推导并写入轴映射', res.applied.axisSrc.join() === '1,2,0' && res.applied.axisNeg === 6, JSON.stringify([res.applied.axisSrc, res.applied.axisNeg]));
    c('方向核对通过', res.passed, res.checks.map((k) => `${k.label} ${k.angle.toFixed(1)}°`).join('；'));
    c('遥测约 100 Hz，无解析丢弃', tel.dropped === 0 && h.samples > 800, `样本 ${h.samples}，丢弃 ${tel.dropped}`);
    b.pose([0, 0, 1]); await b.tick(200);
    const x0 = b.mouse.x; b.move(yawRight(30)); await b.tick(1000); b.move([0, 0, 0]); await b.tick(200);
    c('写入后向右转光标向右', b.mouse.x - x0 > 700, `dx=${b.mouse.x - x0}`);
    await b.wait(tel.close());
  } },
  { id: 'A7', title: '租约超时（页面卡 1 s）', run: async (b, c) => {
    await b.boot();
    const h = await host(b, { autoClaim: true });
    await b.until(hostIs(h), 100);
    const t0 = b.ms; h.link.stopKeepalive();
    const ms = await b.until(async () => (await b.read()).dev.owner === 0, 1000);
    c('约 750 ms 后设备自己交还系统鼠标', near(ms, 750, 210), `${ms} ms`);
    await b.until(hostIs(h), 1000);
    c('页面恢复后自动重新接管', h.link.owner === 'HOST', `+${b.ms - t0} ms`);
    c('新 session 生效', b.sessions.length === 2);
  } },
  { id: 'A8', title: '未实现能力降级', run: async (b, c) => {
    await b.boot();
    const h = await host(b, { autoClaim: true });
    await b.until(hostIs(h), 100);
    c('caps 标记音频可用、触觉不可用', h.caps?.audio === true && h.caps?.haptic === false, JSON.stringify(h.caps));
    c('振动不下发', h.link.pulse() === false && !b.counts['out2:7']);
    await h.link.draw(true); await b.tick(10);
    c('DRAW 可用', h.logs.some((l) => l.text.includes('DRAW') && l.text.includes('OK')));
    await h.link.draw(false); await b.tick(10);
  } },
  { id: 'A9', title: '进下载模式', run: async (b, c) => {
    await b.boot();
    const h = await host(b);
    const r = await b.wait(h.client.download());
    c('先收到回复再重启', r.code === 0);
    await b.tick(120);
    c('固件写入 FORCE_DOWNLOAD 后重启', b.restart?.includes('download=1'), b.restart);
  } },

  { id: 'A10', title: '放在桌上时跟踪温漂', run: async (b, c) => {
    await b.boot(); await b.tick(1000);
    const x0 = b.mouse.x; b.cmd('f bias_z_mdps 500');   // 零偏 0.2 → 0.5 °/s，模拟升温
    await b.tick(30000);
    const z = (await b.read()).dev.bias[2];
    c('30 s 内零偏跟上', near(z, 0.5, 0.08), `Z 零偏 ${z.toFixed(3)} °/s`);
    c('跟踪期间光标基本不动', Math.abs(b.mouse.x - x0) <= 30, `漂 ${b.mouse.x - x0} 计数`);
  } },

  { id: 'L01', title: 'RELEASE 之后 750 ms：系统鼠标被打断', run: async (b, c) => {
    await b.boot();
    const h = await host(b);
    h.link.takeHost(); await b.until(hostIs(h), 100); await b.tick(500);
    const s0 = (await b.read()).dev.session;
    h.link.releaseHost(); await b.tick(300);
    b.key(1); await b.tick(40);                     // 交还后按住 L 拖动
    const pressed = b.mouse.b;
    await b.tick(1500);
    const s1 = (await b.read()).dev;
    c('拖动中左键保持按下', pressed === 1 && b.mouse.b === 1, `按下 ${pressed}，1.5 s 后 ${b.mouse.b}，沿 ${JSON.stringify(b.mouse.edges)}`);
    c('已交还后 session 不再变化', s1.session === s0, `0x${s0.toString(16)} → 0x${s1.session.toString(16)}`);
    c('已交还后 host_connected 清零', s1.host_connected === 0);
    b.key(0); await b.tick(60);
  } },
  { id: 'L02', title: '页面失焦后反复重连', run: async (b, c) => {
    await b.boot();
    const h = await host(b, { autoClaim: true });
    await b.until(hostIs(h), 100); await b.tick(300);
    const t0 = b.ms, sess0 = b.sessions.length;
    h.link.suspend();
    await b.tick(3000);
    b.key(1); await b.tick(40);
    const pressed = b.mouse.b;
    await b.tick(5000);
    const held = b.mouse.b; b.key(0); await b.tick(2000);
    const cuts = b.mouse.edges.filter((e) => e.t > t0 && e.to === 0).length;
    c('失焦期间不发 HELLO', hellos(b, t0 + 1) === 0, `10 s 内 ${hellos(b, t0 + 1)} 次`);
    c('失焦期间 session 不变', b.sessions.length === sess0, `多了 ${b.sessions.length - sess0} 次`);
    c('失焦期间系统鼠标按键不被切断', pressed === 1 && held === 1, `按下 ${pressed}，5 s 后 ${held}，切断 ${cuts} 次`);
    c('没有误报“设备未应答”', !h.states.some((s) => s.phase === 'error'), h.states.filter((s) => s.phase === 'error').map((s) => `${s.t - t0} ms: ${s.text}`)[0] ?? '');
    h.link.resume(); await b.until(hostIs(h), 2000);
    c('回到页面重新接管', h.link.owner === 'HOST');
  } },
  { id: 'L03', title: '断开再连接：旧监听器还活着', run: async (b, c) => {
    await b.boot();
    const h1 = await host(b);
    h1.link.takeHost(); await b.until(hostIs(h1), 100);
    await b.wait(h1.link.close());
    await b.tick(1000);
    const h2 = await host(b, { existing: b.hidDevice });
    h2.link.takeHost(); await b.until(hostIs(h2), 200);
    h1.motion = [0, 0]; h1.frames = 0; h2.motion = [0, 0];
    b.move(yawRight(30)); await b.tick(1000); b.move([0, 0, 0]); await b.tick(200);
    c('新连接收到全部位移', near(h2.motion[0], 840, 45), `x=${h2.motion[0]}`);
    c('已关闭的旧 HidLink 不再收到报告', h1.frames === 0, `旧链路仍收到 ${h1.frames} 帧，x=${h1.motion[0]}`);
  } },
  { id: 'A11', title: '晚几秒才打开串口，还能看到启动日志', run: async (b, c) => {
    await b.boot(); await b.tick(7000);             // 人打开串口总要几秒
    b.cmd('d 1'); await b.tick(800);
    const t = b.cdc;
    c('能看到 复位原因（查崩溃要用）', t.includes('复位原因'), `FIFO 只留最后 512 字节，收到 ${Buffer.byteLength(t)} 字节，从“${t.slice(0, 24).replace(/\s+/g, ' ')}…”开始`);
    c('能看到 I2C 三地址探测结果', t.includes('I2C 探测'));
    c('能看到 BMI270 就绪', t.includes('BMI270 就绪'));
    c('能看到 陀螺仪已校准', t.includes('已校准'));
    b.cdc = '';
  } },
  { id: 'A12', title: '录音隐私闸门', run: async (b, c) => {
    await b.boot();
    const h = await host(b, { autoClaim: true });
    await b.until(hostIs(h), 100);
    const gate = async () => (await b.read()).sim;
    c('空闲时闸门关、不要时钟', (await gate()).mic_gate === 0 && (await gate()).mic_power === 0);
    h.link.record(true); await b.tick(100);
    c('没按 V：主机请求也打不开', (await gate()).mic_gate === 0 && (await gate()).gate_opens === 0);
    b.key(4); await b.tick(40);
    c('按住 V 但没请求：不开', (await gate()).mic_gate === 0);
    h.link.record(true); await b.tick(30);
    let s = await gate();
    c('请求后先上电，稳定前闸门关', s.mic_power === 1 && s.mic_gate === 0, JSON.stringify(s));
    await b.tick(40);
    c('50 ms 稳定后闸门开', (await gate()).mic_gate === 1);
    const t0 = b.ms; b.key(0); await b.tick(10);
    s = await gate();
    c('松键 10 ms 内关闸（规格目标）', s.mic_gate === 0 && s.gate_closed_ms - t0 <= 10, `${s.gate_closed_ms - t0} ms`);
    await b.tick(40);
    b.key(4); await b.tick(40); h.link.record(true); await b.tick(80);
    c('再次录音能打开', (await gate()).mic_gate === 1);
    h.link.suspend?.(); await b.tick(1000);
    c('切走页面或租约结束后闸门关', (await gate()).mic_gate === 0);
    b.key(0);
  } },
  { id: 'L05', title: 'IMU 任务先于 imu_init 启动', run: async (b, c) => {
    await b.boot();
    const s = (await b.read()).sim;
    c('bmi270_init 期间没有并发读传感器', s.race_reads === 0, `初始化期间 imu_read 被调用 ${s.race_reads} 次（模型 0.9 s）`);
  } },
  { id: 'L06', title: '电脑睡眠时位移累积，唤醒后光标跳', run: async (b, c) => {
    await b.boot(); await b.tick(100);
    const x0 = b.mouse.x;
    b.cmd('s 1'); await b.tick(50);
    b.move(yawRight(30)); await b.tick(2000); b.move([0, 0, 0]); await b.tick(50);
    const st = (await b.read()).dev;
    b.cmd('s 0'); await b.tick(300);
    c('挂起期间不累积位移', st.acc_x === 0, `acc_x=${st.acc_x}`);
    c('唤醒后光标不跳', Math.abs(b.mouse.x - x0) <= 2, `dx=${b.mouse.x - x0}`);
  } },
  { id: 'L07', title: 'CDC 暂停读取 100 ms（遥测整行性）', run: async (b, c) => {
    await b.boot();
    const h = await host(b);
    const tel = new Telemetry({ onSample: () => {}, onLog: () => {} });
    await b.wait(tel.connect(b.port)); await b.wait(h.client.telemetry(true)); await b.tick(500);
    b.cmd('f cdc_rate 0'); await b.tick(100); b.cmd('f cdc_rate 256'); await b.tick(500);
    const s = (await b.read()).sim;
    c('FIFO 满时整行丢弃，不写半行', s.cdc_partial === 0, `半行 ${s.cdc_partial} 次，解析丢弃 ${tel.dropped} 行`);
    await b.wait(tel.close());
  } },
  { id: 'L08', title: 'session 切换瞬间发配置（重试用了旧 session）', run: async (b, c) => {
    await b.boot();
    const h = await host(b);
    h.link.takeHost(); await b.until(hostIs(h), 100);
    h.link.wantHost = false; h.link.stopKeepalive();
    const s0 = (await b.read()).dev.session;
    await b.until(async () => (await b.read()).dev.session !== s0, 1000);
    let e = ''; try { await b.wait(h.client.get(), 2000); } catch (x) { e = x.message; }
    c('配置请求自动换到新 session', e === '', e);
  } },
  { id: 'L09', title: '慢速平移被零偏跟踪吃掉', run: async (b, c) => {
    await b.boot(); await b.tick(100);
    const x0 = b.mouse.x, rate = 2, secs = 6;
    b.move(yawRight(rate)); await b.tick(secs * 1000); b.move([0, 0, 0]);
    const moved = b.mouse.x - x0, want = rate * secs * 28, bias = (await b.read()).dev.bias[2];
    await b.tick(200); const x1 = b.mouse.x; await b.tick(5000); const back = b.mouse.x - x1;
    c('2 °/s 匀速 6 s 位移完整（±10%）', near(moved, want, want * 0.1), `应 ${want}，实得 ${moved}`);
    c('零偏不被运动带跑', near(bias, 0.2, 0.1), `Z 零偏 0.2 → ${bias.toFixed(2)} °/s`);
    c('停下后不回爬', Math.abs(back) <= 5, `5 s 内回爬 ${back} 计数`);
    b.cmd('f noise_mdps 400');                      // 手持：叠加约 0.4 °/s 手抖
    await b.tick(3000); const x2 = b.mouse.x;
    b.move(yawRight(1)); await b.tick(6000); b.move([0, 0, 0]); await b.tick(200);
    c('手持 1 °/s 慢移 6 s 位移基本完整（±25%）', near(b.mouse.x - x2, 168, 42), `应 168，实得 ${b.mouse.x - x2}`);
  } },
  { id: 'L10', title: 'IMU 运行中故障与恢复', run: async (b, c) => {
    await b.boot();
    const h = await host(b, { autoClaim: true });
    await b.until(hostIs(h), 100); await b.tick(200);
    b.cmd('f imu_fail_read 1'); await b.tick(1000);
    c('状态报告带 IMU 故障位', (h.last?.faults & 1) === 1, `faults=${h.last?.faults}`);
    b.cmd('f imu_fail_read 0'); await b.tick(1500);
    const d = (await b.read()).dev; const m0 = h.motion[0], f0 = h.frames;
    b.move(yawRight(30)); await b.tick(500); b.move([0, 0, 0]); await b.tick(100);
    const moved = h.frames > f0;
    c('故障位与实际行为一致（要么恢复且清位，要么真的停用）', ((d.faults & 1) === 1) !== moved, `faults=${d.faults}，日志说“停用指向”，恢复后仍出位移 ${h.motion[0] - m0}`);
  } },
  { id: 'L11', title: 'BMI270 初始化失败（虚焊）', run: async (b, c) => {
    b.cmd('f imu_fail_init 1');
    await b.boot(); await b.tick(5000);
    const s = await b.read();
    c('上报 IMU 故障，按键仍可用', (s.dev.faults & 1) === 1);
    c('不再空转读总线', s.sim.failed_reads < 20, `失败读 ${s.sim.failed_reads} 次（每次真机都打一条 I2C 错误日志）`);
  } },
  { id: 'L12', title: '按住 L 时点接管', run: async (b, c) => {
    await b.boot();
    const h = await host(b);
    b.key(1); await b.tick(40);
    h.link.takeHost(); await b.tick(3000);
    c('提示先松键，不误报设备无响应', !h.states.some((s) => s.phase === 'error'), h.states.at(-1)?.text);
    c('不影响正在按住的左键', b.mouse.b === 1, `沿 ${JSON.stringify(b.mouse.edges)}`);
    b.key(0); await b.tick(1500);
  } },
  { id: 'L13', title: 'HOST 时拔线再插', run: async (b, c) => {
    await b.boot();
    const h = await host(b, { autoClaim: true });
    await b.until(hostIs(h), 100);
    b.key(1); await b.tick(40);
    b.unplug(); await b.tick(100);
    c('页面进入断开状态，按键不悬挂', h.states.at(-1).phase === 'lost' && h.link.buttons === 0, JSON.stringify(h.states.at(-1)));
    b.key(0); await b.tick(100); b.cmd('m 1'); await b.tick(200);
    const d = (await b.read()).dev;
    c('固件回到普通鼠标、输入已清', d.owner === 0 && d.host_connected === 0 && d.hid_buttons === 0);
  } },
  { id: 'F1', title: '随机压力 60 s', run: async (b, c) => {
    await b.boot();
    const h = await host(b, { autoClaim: true });
    let seed = 0x1234567; const r = (n) => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return (seed >>> 8) % n; };
    let keys = 0, spurious = 0;
    for (let i = 0; i < 600; i++) {
      const a = r(12);
      if (a < 4) { keys ^= 1 << r(4); b.key(keys); }
      else if (a === 4) h.link.suspend(); else if (a === 5) h.link.resume();
      else if (a === 6) h.link.takeHost(); else if (a === 7) h.link.releaseHost();
      else if (a === 8) h.client.get().catch(() => {});
      else if (a === 9) { b.cmd('s 1'); await b.tick(30 + r(50)); b.cmd('s 0'); }
      else b.move([r(61) - 30, 0, r(121) - 60]);
      await b.tick(100);
      if (b.mouse.b && !(keys & 3) && (await b.read()).dev.owner === 0 && b.mouse.edges.at(-1).t < b.ms - 60) spurious++;
    }
    b.move([0, 0, 0]); b.key(0); h.link.releaseHost(); await b.tick(2500);
    const d = (await b.read()).dev;
    c('全部松开后鼠标按键清零', b.mouse.b === 0 && d.hid_buttons === 0 && d.buttons === 0);
    c('没有悬挂的鼠标按键', spurious === 0, `${spurious} 次`);
    c('页面按键状态清零', h.link.buttons === 0);
    c('上位机待确认命令不无限增长', h.link.pending.size < 20, `${h.link.pending.size} 条`);
  } },
];
