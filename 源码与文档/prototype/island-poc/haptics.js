// 触觉语汇。每个脉冲不超过 80ms（固件 AK_FEEDBACK 单次上限）；录音、圈画期间禁振，排到结束后。
export const PATTERNS = {
  tick:    { name: '轻点',   pulses: [[0, 18, 0.45]] },
  lock:    { name: '锁定',   pulses: [[0, 40, 0.8]] },
  snap:    { name: '闭合',   pulses: [[0, 30, 0.7], [90, 30, 0.7]] },
  open:    { name: '展开',   pulses: [[0, 22, 0.5], [70, 45, 0.85]] },
  hop:     { name: '起跳',   pulses: [[0, 60, 1]] },
  land:    { name: '落地',   pulses: [[0, 35, 0.9], [60, 18, 0.4]] },
  success: { name: '完成',   pulses: [[0, 40, 0.8], [120, 70, 1]] },
  warn:    { name: '提醒',   pulses: [[0, 80, 1], [140, 80, 1], [280, 80, 1]] },
  heart:   { name: '心跳',   pulses: [[0, 50, 0.9], [160, 30, 0.6]] },
};

export function validatePattern(p) {
  let last = -1;
  for (const [at, dur, amp] of p.pulses) {
    if (dur <= 0 || dur > 80 || amp <= 0 || amp > 1 || at < last) return false;
    last = at + dur;
  }
  return true;
}

export class Haptics {
  constructor({ onPulse, isBlocked }) { this.onPulse = onPulse; this.isBlocked = isBlocked; this.queue = []; }
  play(id) {
    const p = PATTERNS[id]; if (!p) return;
    if (this.isBlocked()) { this.queue.push(id); return 'queued'; }
    for (const [at, dur, amp] of p.pulses) setTimeout(() => this.onPulse({ id, name: p.name, dur, amp }), at);
    return 'played';
  }
  flush() { const q = this.queue.splice(0); q.forEach((id) => this.play(id)); }
  clear() { this.queue.length = 0; }
}
