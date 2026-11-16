// 轴向推导：两个静止姿势定轴，与 engineering/e24/tools/e24ctl.py 的 derive_axes 同一方法。
// 平放（正面朝上）时朝上的 +Z 读 +1 g；竖起（前端朝天）时 +Y 读 +1 g；X = Y × Z。
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

export function dominantAxis(a, what) {
  const n = Math.hypot(...a);
  if (!(n >= 0.8 && n <= 1.2)) throw new Error(`${what}：加速度合计 ${n.toFixed(2)} g，不像静止（应约 1 g）`);
  const abs = a.map(Math.abs), i = abs.indexOf(Math.max(...abs));
  const rest = Math.max(...abs.filter((_, k) => k !== i));
  if (abs[i] < 0.85 || rest > 0.4) throw new Error(`${what}：重力没有落在单一轴上（${a.map((v) => v.toFixed(2)).join(', ')} g），请摆正后重来`);
  return [i, a[i] > 0 ? 1 : -1];
}

export function deriveAxes(aFlat, aNoseUp) {
  const [zi, zs] = dominantAxis(aFlat, '平放');
  const [yi, ys] = dominantAxis(aNoseUp, '竖起');
  if (zi === yi) throw new Error('两次姿势的重力落在同一个传感器轴上：竖起那一步要让前端朝天花板');
  const ez = [0, 0, 0], ey = [0, 0, 0];
  ez[zi] = zs; ey[yi] = ys;
  const ex = cross(ey, ez), xi = ex.findIndex((v) => v !== 0);
  return { axisSrc: [xi, yi, zi], axisNeg: (ex[xi] < 0 ? 1 : 0) | (ys < 0 ? 2 : 0) | (zs < 0 ? 4 : 0) };
}

export function summarizeStill(samples) {
  if (samples.length < 20) throw new Error('遥测样本太少：确认遥测已打开，串口没被 screen 或 e24ctl 占用');
  const a = [0, 1, 2].map((i) => samples.reduce((s, d) => s + d.a[i], 0) / samples.length);
  const spread = Math.max(...[0, 1, 2].map((i) => { const v = samples.map((d) => d.g[i]); return Math.max(...v) - Math.min(...v); }));
  return { a, spread, still: spread < 4 };
}

// 角速度（°/s）对时间积分成角度（°）。
export function integrate(samples, key) {
  let total = 0;
  for (let i = 1; i < samples.length; i++) {
    const dt = (samples[i].t - samples[i - 1].t) / 1000;
    if (dt > 0 && dt < 0.1) total += samples[i][key] * dt;
  }
  return total;
}
