// 轴向向导流程：与 e24ctl.py run_wizard 同步骤。界面通过 ui 注入，便于测试。
//   ui.step({ id, title, body, action }) 等用户点按钮；ui.note(text) 显示过程；ui.result(lines) 给结论。
import { deriveAxes, summarizeStill, integrate } from './axes.js';
import { axesText } from './devcfg.js';

export const WIZARD_STEPS = [
  { id: 'flat', title: '平放', body: '正面（按键那面）朝上，平放在桌面上，前端指向屏幕。放好后别碰它。', action: '放好了' },
  { id: 'noseUp', title: '竖起', body: '把前端（指向屏幕那头）竖直朝向天花板，拿稳不动。', action: '竖好了' },
  { id: 'rest', title: '放回桌面', body: '写入轴向后要重新校准零偏。请先平放回桌面，别碰它。', action: '写入并校准' },
  { id: 'right', title: '向右转', body: '拿起来按平常握法，点按钮后 2 秒内水平向右转约 30°，像手电筒从左扫到右。', action: '开始' },
  { id: 'up', title: '向上抬', body: '回到中间，点按钮后 2 秒内把前端向上抬约 30°。', action: '开始' },
];

export async function runWizard({ cfg, client, tel, ui, captureMs = 1000, moveMs = 2500, calTimeoutMs = 8000, tickMs = 200 }) {
  const [flat, noseUp, rest, right, up] = WIZARD_STEPS;
  await client.telemetry(true);

  const pose = async (step) => {
    for (let i = 0; i < 3; i++) {
      await ui.step(step);
      const s = summarizeStill(await tel.collect(captureMs));
      if (s.still) return s.a;
      ui.note(`${step.title}时检测到晃动（陀螺波动 ${s.spread.toFixed(1)} °/s），再来一次。`);
    }
    throw new Error(`${step.title}三次都没静止下来，向导已停止`);
  };
  const aFlat = await pose(flat);
  const aUp = await pose(noseUp);
  const axes = deriveAxes(aFlat, aUp);
  ui.note(`推导结果 ${axesText(axes.axisSrc, axes.axisNeg)}（原来 ${axesText(cfg.axisSrc, cfg.axisNeg)}）`);

  // 先放好再写入：写入后设备一静止就开始校准，不能让它在手里校准。
  await ui.step(rest);
  const applied = (await client.set({ ...cfg, ...axes, invertX: false, invertY: false })).cfg;
  await client.calibrate();
  const end = Date.now() + calTimeoutMs;
  for (;;) {
    const r = await client.get();
    if (r.state === 2) break;
    if (Date.now() > end) throw new Error('8 秒内没完成校准：确认手柄是静止的，再点「重新校准」');
    await new Promise((res) => setTimeout(res, tickMs));
  }

  const checks = [];
  for (const [step, key, want, label] of [[right, 'h', 1, '向右转 → 光标向右'], [up, 'vv', -1, '向上抬 → 光标向上']]) {
    await ui.step(step);
    const angle = integrate(await tel.collect(moveMs), key);
    const good = angle * want > 8;
    checks.push({ label, angle, good });
    ui.note(`${label}：测得 ${angle >= 0 ? '+' : ''}${angle.toFixed(1)}°，${good ? '正确' : '不对'}`);
  }
  return { applied, axes, checks, passed: checks.every((c) => c.good) };
}
