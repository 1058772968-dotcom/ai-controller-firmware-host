// 用法：node run.mjs [--json 报告.json] [场景ID…]
// 环境变量 SIM_FIRMWARE / SIM_PROTOTYPE 可指向打过补丁的副本，用来验证修法。退出码：有检查失败时为 1。
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Bench, buildDevice, FW_ROOT, PROTO_ROOT } from './harness.mjs';
import { scenarios } from './scenarios.mjs';

const args = process.argv.slice(2), ji = args.indexOf('--json');
const jsonOut = ji >= 0 ? args.splice(ji, 2)[1] : null;
const only = new Set(args);
const bin = buildDevice(join(mkdtempSync(join(tmpdir(), 'e24sim-')), 'device'));
const out = [];
let fails = 0;
for (const s of scenarios) {
  if (only.size && !only.has(s.id)) continue;
  const checks = [];
  const b = new Bench(bin);
  await b.start();
  const c = (name, ok, detail = '') => { checks.push({ name, ok: !!ok, detail: String(detail) }); };
  let err = null;
  try { await s.run(b, c); } catch (e) { err = e.message; checks.push({ name: '场景跑完', ok: false, detail: e.stack.split('\n').slice(0, 3).join(' | ') }); }
  await b.stop();
  out.push({ id: s.id, title: s.title, checks, simMs: b.ms });
  const bad = checks.filter((k) => !k.ok);
  fails += bad.length;
  console.log(`${bad.length ? '✗' : '✓'} ${s.id} ${s.title}（${checks.length - bad.length}/${checks.length}）`);
  for (const k of checks) if (!k.ok || process.env.SIM_VERBOSE) console.log(`    ${k.ok ? '通过' : '失败'} ${k.name}${k.detail ? '：' + k.detail : ''}`);
}
const total = out.reduce((n, s) => n + s.checks.length, 0);
console.log(`\n${total - fails}/${total} 项检查通过；固件 ${FW_ROOT}；上位机 ${PROTO_ROOT}`);
if (jsonOut) writeFileSync(jsonOut, JSON.stringify({ source: process.env.SIM_FIRMWARE ? '候选修法副本' : '当前工作区', total, failed: fails, scenarios: out }, null, 2));
process.exit(fails ? 1 : 0);
