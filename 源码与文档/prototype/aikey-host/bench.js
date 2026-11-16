// 逐项测试：不依赖页面，步骤和判定都在这里，虚拟手柄和实物走同一份代码。
// ctx 由页面提供：hid、client、telemetry()、capture()、say()、ask()、sleep()、waitReport()。
import { KEY } from '../island-poc/protocol.js';

export const TONE_LIMITS = { minHz: 200, maxHz: 4000, minMs: 10, maxMs: 1000, minAtten: 30, maxAtten: 80 };
const PADS = { L: 'J5', R: 'J6', V: 'J7', S: 'J8' };
const db = (v) => (v > 0 ? 20 * Math.log10(v) : -120);
const fmt = (v) => v.toFixed(1);

// ---------- 判定：纯函数 ----------
export function judgeTelemetry({ hz, dropped, count }) {
  if (!count) return { pass: false, text: '3 秒内没收到遥测。先点「连接遥测串口」。' };
  const pass = hz >= 90 && dropped === 0;
  return { pass, text: `${fmt(hz)} Hz，丢弃 ${dropped} 行${pass ? '' : '（要求至少 90 Hz、丢弃 0 行）'}` };
}
export function judgeMic(a) {
  const base = `RMS ${fmt(a.rmsDb)} dBFS，峰值 ${fmt(a.peakDb)} dBFS，左槽非零 ${a.leftPct}%，右槽非零 ${a.rightPct}%`;
  if (!a.testValid) return { pass: false, text: '自检没有完成。' };
  if (a.rxErrors) return { pass: false, text: `I²S 读错误 ${a.rxErrors} 次。${base}` };
  if (a.leftPct < 50) return { pass: false, text: `左槽几乎全零：查 U3 焊接、BCLK、WS、MIC_DOUT。${base}` };
  if (a.rightPct > 5) return { pass: false, text: `右槽也有数据：槽位或 SELECT 不对。${base}` };
  return { pass: true, text: base };
}
export function judgeResponse(quiet, loud) {
  const rise = loud.peakDb - quiet.peakDb;
  return { pass: rise >= 10, text: `安静峰值 ${fmt(quiet.peakDb)}，出声峰值 ${fmt(loud.peakDb)}，升高 ${fmt(rise)} dB${rise >= 10 ? '' : '（要求至少 10 dB）'}` };
}
// POC 档主机开流即放行，这两项的“必须全零”按设计不成立，不能判成隐私故障
export const POC_NA = { skipped: true, text: '这块板烧的是麦克风 POC 档（AI KEY Mic POC），不按 V 也放行，闸门项不适用。烧回联调档再测。' };

export function judgeClosed({ samples, nonzero, peak, streaming, gate }) {
  if (!streaming) return { pass: false, text: '设备没有收到主机取流，这次不算数。确认选中的是 Held-key microphone。' };
  if (samples < 8000) return { pass: false, text: `只收到 ${samples} 个样本，不够判断。` };
  if (gate) return { pass: false, text: '闸门是开着的，这项要在没有录音时测。' };
  return { pass: nonzero === 0, text: `${samples} 个样本，非零 ${nonzero} 个，峰值 ${fmt(db(peak))} dBFS` };
}
export function judgeRecord({ opened, before, during, after, durationMs }) {
  if (!opened) return { pass: false, text: '闸门没有打开：没等到“麦克风就绪”。' };
  if (before.nonzero) return { pass: false, text: `按 V 之前收到 ${before.nonzero} 个非零样本，隐私闸门有问题。` };
  if (after.nonzero) return { pass: false, text: `松键 300 ms 后还有 ${after.nonzero} 个非零样本，闸门没有及时关。` };
  if (!during.samples || !during.nonzero) return { pass: false, text: '开闸期间全是零：闸门开了但没有声音数据。' };
  const ratio = during.nonzero / during.samples, rms = db(during.rms), peak = db(during.peak);
  const text = `录到 ${(durationMs / 1000).toFixed(1)} 秒，RMS ${fmt(rms)} dBFS，峰值 ${fmt(peak)} dBFS，非零 ${Math.round(ratio * 100)}%；按 V 前和松键后都是零`;
  return { pass: ratio > 0.5 && durationMs >= 500, text: durationMs < 500 ? `按得太短。${text}` : text };
}

// 按时段统计取流样本。
export class SegmentStats {
  constructor() { this.samples = 0; this.nonzero = 0; this.peak = 0; this.sum2 = 0; }
  add(block) {
    for (const x of block) {
      const a = Math.abs(x);
      if (a >= 1 / 65536) this.nonzero++;
      if (a > this.peak) this.peak = a;
      this.sum2 += x * x;
    }
    this.samples += block.length;
  }
  get rms() { return this.samples ? Math.sqrt(this.sum2 / this.samples) : 0; }
}

// 16 kHz 单声道 float → 16 bit WAV，只在内存里，给「回放」用。
export function wavBytes(blocks, rate = 16000) {
  const n = blocks.reduce((s, b) => s + b.length, 0), out = new DataView(new ArrayBuffer(44 + n * 2));
  const tag = (o, t) => { for (let i = 0; i < 4; i++) out.setUint8(o + i, t.charCodeAt(i)); };
  tag(0, 'RIFF'); out.setUint32(4, 36 + n * 2, true); tag(8, 'WAVE'); tag(12, 'fmt '); out.setUint32(16, 16, true);
  out.setUint16(20, 1, true); out.setUint16(22, 1, true); out.setUint32(24, rate, true); out.setUint32(28, rate * 2, true);
  out.setUint16(32, 2, true); out.setUint16(34, 16, true); tag(36, 'data'); out.setUint32(40, n * 2, true);
  let o = 44;
  for (const b of blocks) for (const x of b) { out.setInt16(o, Math.max(-32768, Math.min(32767, Math.round(x * 32768))), true); o += 2; }
  return new Uint8Array(out.buffer);
}

async function withHost(ctx, fn) {
  if (ctx.hid.owner !== 'HOST') {
    ctx.hid.takeHost();
    await ctx.waitReport((r) => r.owner === 'HOST', 3000, '没拿到控制权：先松开 L、R，并保持这个页面在最前面');
  }
  try { return await fn(); } finally { ctx.hid.releaseHost(); }
}

async function micOnce(ctx) {
  await ctx.client.micTest();
  await ctx.sleep(1000);
  for (let i = 0; i < 30; i++) {
    const a = (await ctx.client.audio()).audio;
    if (!a.testing) return a;
    await ctx.sleep(50);
  }
  throw new Error('自检 2.5 秒没结束');
}

// ---------- 测试项 ----------
export const TESTS = [
  { id: 'conn', title: '连接与固件', how: '先点右上角「连接手柄」。这项确认板子在线，并且烧的是带音频的固件。',
    async run(ctx) {
      if (!ctx.hid) return { pass: false, text: '还没连接手柄。' };
      const r = await ctx.waitReport(() => true, 1500, '1.5 秒没收到设备状态');
      if (r.faults & 2) return { pass: false, text: '设备报音频故障，或者这块板是不带音频的旧固件。' };
      try { await ctx.client.audio(); }
      catch { return { pass: false, text: '设备不响应音频命令：这块板是旧固件，需要先烧带音频的联调档。' }; }
      return { pass: true, text: `已连接，session ${r.session.toString(16).padStart(8, '0')}，音频可用` };
    } },
  { id: 'cal', title: '陀螺仪校准', how: '把手柄平放在桌上别碰，等到校准完成。拿在手里过不了，这是正常的。',
    async run(ctx) {
      ctx.say('放稳，别碰…');
      await ctx.waitReport((r) => r.flags.calibrated, 15000, '15 秒没完成校准：手柄要放稳不动');
      return { pass: true, text: '已校准' };
    } },
  { id: 'tel', title: '遥测', how: '先点右上角「连接遥测串口」。这项采 3 秒，要求约 100 Hz、没有丢行。',
    async run(ctx) {
      ctx.say('采集 3 秒…');
      return judgeTelemetry(await ctx.telemetry(3000));
    } },
  { id: 'keys', title: '四键', how: '开始后依次按 L、R、V、S，每个按一下再松开。测试期间页面接管指针，所以 L、R 不会点到东西。',
    async run(ctx) {
      return withHost(ctx, async () => {
        const seen = {}, pending = () => Object.keys(KEY).filter((k) => seen[k] !== 'done');
        const end = ctx.now() + 60000;
        while (pending().length && ctx.now() < end) {
          ctx.say(`还没测到：${pending().join(' ')}`, pending());
          let r;
          try { r = await ctx.waitReport(() => true, Math.max(1, end - ctx.now())); } catch { break; }
          for (const [k, bit] of Object.entries(KEY)) {
            if (r.buttons & bit) { if (seen[k] !== 'done') seen[k] = 'down'; }
            else if (seen[k] === 'down') seen[k] = 'done';
          }
        }
        const miss = Object.keys(KEY).filter((k) => seen[k] !== 'done');
        return miss.length
          ? { pass: false, text: `没收到 ${miss.join('、')}。查 ${miss.map((k) => `${k} → ${PADS[k]}`).join('、')} 的焊点和对地通断。` }
          : { pass: true, text: 'L、R、V、S 按下和松开都收到了' };
      });
    } },
  { id: 'mic', title: '麦克风电平', how: '自检约 1 秒，只读电平，不录声音。',
    async run(ctx) {
      ctx.say('自检中…');
      return judgeMic(await micOnce(ctx));
    } },
  { id: 'micLoud', title: '麦克风响应声音', how: '先保持安静 1 秒，看到提示后对着手柄拍手或说话 1 秒。',
    async run(ctx) {
      ctx.say('保持安静…');
      const quiet = await micOnce(ctx);
      const q = judgeMic(quiet); if (!q.pass) return q;
      ctx.say('现在拍手或大声说话！');
      ctx.expectSound?.();
      await ctx.sleep(400);
      return judgeResponse(quiet, await micOnce(ctx));
    } },
  { id: 'gate', title: '闸门关闭时无声', how: '不要按键。页面打开麦克风流 2 秒，这时收到的必须全是零。第一次会弹麦克风授权。',
    async run(ctx) {
      const cap = await ctx.capture();
      if (cap.poc) { await cap.close(); return POC_NA; }
      try {
        const st = new SegmentStats();
        cap.onBlock = (b) => st.add(b);
        ctx.say('取流 2 秒…');
        await ctx.sleep(600);
        const a = (await ctx.client.audio()).audio;
        await ctx.sleep(1400);
        return judgeClosed({ samples: st.samples, nonzero: st.nonzero, peak: st.peak, streaming: a.streaming, gate: a.gate });
      } finally { await cap.close(); }
    } },
  { id: 'record', title: '真实录音', how: '开始后按住 V 说几句话，松开就结束。录音只留在这个页面的内存里，可以回放，关页面或重测就清掉。测试期间别切走页面。',
    async run(ctx) {
      const cap = await ctx.capture();
      if (cap.poc) { await cap.close(); return POC_NA; }
      try {
        return await withHost(ctx, async () => {
          const seg = { before: new SegmentStats(), during: new SegmentStats(), after: new SegmentStats() };
          const blocks = [];
          let phase = 'before', openedAt = 0, closedAt = 0, settle = 0;
          cap.onBlock = (b) => {
            if (phase === 'during') blocks.push(b);
            if (phase === 'tail' && ctx.now() >= settle) phase = 'after';
            if (phase !== 'tail') seg[phase].add(b);
            ctx.level(Math.sqrt(b.reduce((s, x) => s + x * x, 0) / b.length));
          };
          ctx.say('按住 V 说话…');
          await ctx.waitReport((r) => r.buttons & KEY.V, 30000, '30 秒没收到 V 键。先过「四键」这一项。');
          // 按 V 之前才是“绝不能有声音”的时段。开闸状态可能比第一块音频晚到页面，所以从这里就算录音段。
          phase = 'during';
          await ctx.hid.record(true);
          ctx.say('请求录音，等待开闸…');
          await ctx.waitReport((r) => r.flags.micReady || !(r.buttons & KEY.V), 1000, '1 秒没开闸：看日志里 RECORD 的 ACK');
          const opened = ctx.last().flags.micReady && !!(ctx.last().buttons & KEY.V);
          if (opened) {
            openedAt = ctx.now();
            ctx.say('录音中，说话，松开就停');
            await ctx.waitReport((r) => !(r.buttons & KEY.V) || !r.flags.micReady, 30000, '按了 30 秒还没松开');
            closedAt = ctx.now(); phase = 'tail'; settle = closedAt + 300;
            ctx.say('已松开，确认闸门关闭…');
            await ctx.sleep(1000);
          }
          const res = judgeRecord({ opened, ...seg, durationMs: closedAt - openedAt });
          if (blocks.length) res.wav = wavBytes(blocks);
          return res;
        });
      } finally { ctx.level(0); await cap.close(); }
    } },
  { id: 'tone', title: '扬声器提示音', how: '会真的出声。先确认扬声器已接好，勾选后才能开始。音量上限比满幅低 30 dB，从低音量开始。',
    needsSpeaker: true,
    async run(ctx) {
      const { hz, ms, atten } = ctx.toneParams();
      ctx.say(`播放 ${hz} Hz，${ms} ms，-${atten} dB…`);
      await ctx.client.tone(hz, ms, atten);
      await ctx.sleep(ms + 200);
      const a = (await ctx.client.audio()).audio;
      if (a.failed) return { pass: false, text: '设备报音频故障。' };
      const heard = await ctx.ask('听到提示音了吗？', ['听到，声音干净', '听到，有爆音或杂音', '没听到']);
      return { pass: heard === 0, text: `${hz} Hz，-${atten} dB：${['听到，声音干净', '听到，有爆音或杂音', '没听到'][heard]}` };
    } },
];

export function report(results, board) {
  const lines = [`AI KEY 逐项测试 ${new Date().toLocaleString('zh-CN')}${board ? `  板子 ${board}` : ''}`];
  for (const t of TESTS) {
    const r = results[t.id];
    lines.push(`${r ? (r.skipped ? '跳过' : r.pass ? '通过' : '不通过') : '未测'}  ${t.title}${r?.text ? '：' + r.text : ''}`);
  }
  return lines.join('\n');
}
