// 四键语义层：把原始按键沿变成交互语义。沿用 C 背键与 V0.3 定义：
//   L 确认 / 左击；R 取消 / 返回；S 短按 = 呼出灵动岛流转，长按 ≥180ms = 圈画 / 涂抹；
//   V 按下锁定目标，保持 ≥280ms 开始说话，松开结束；两次短按（300ms 内）= 居中。
// 录音与圈画互斥：一方进行中时另一方的按下被忽略，直到松开。
export const TIMING = { drawHold: 180, voiceHold: 280, doubleTap: 300 };

export class KeyGrammar {
  constructor(emit, timing = TIMING) {
    this.emit = emit; this.t = timing;
    this.down = { L: false, R: false, V: false, S: false };
    this.sAt = 0; this.sLong = false; this.sIgnored = false;
    this.vAt = 0; this.vLong = false; this.vIgnored = false; this.lastVTap = -1e9;
    this.drawing = false; this.recording = false;
  }
  press(key, now) {
    if (this.down[key]) return;
    this.down[key] = true;
    this.emit({ type: 'key', key, down: true, at: now });
    if (key === 'L') this.emit({ type: 'primary', at: now });
    if (key === 'R') this.emit({ type: 'back', at: now });
    if (key === 'S') { this.sAt = now; this.sLong = false; this.sIgnored = this.recording || this.down.V; }
    if (key === 'V') {
      this.vAt = now; this.vLong = false; this.vIgnored = this.drawing || this.down.S;
      if (!this.vIgnored) this.emit({ type: 'lock', at: now });
    }
  }
  release(key, now) {
    if (!this.down[key]) return;
    this.tick(now);
    this.down[key] = false;
    this.emit({ type: 'key', key, down: false, at: now });
    if (key === 'L') this.emit({ type: 'primaryUp', at: now });
    if (key === 'S' && !this.sIgnored) {
      if (this.sLong) { this.drawing = false; this.emit({ type: 'drawEnd', at: now }); }
      else this.emit({ type: 'island', at: now });
    }
    if (key === 'V' && !this.vIgnored) {
      if (this.vLong) { this.recording = false; this.emit({ type: 'voiceEnd', at: now }); this.lastVTap = -1e9; }
      else if (now - this.lastVTap <= this.t.doubleTap) { this.lastVTap = -1e9; this.emit({ type: 'recenter', at: now }); }
      else { this.lastVTap = now; this.emit({ type: 'unlock', at: now }); }
    }
  }
  tick(now) {
    if (this.down.S && !this.sIgnored && !this.sLong && now - this.sAt >= this.t.drawHold) {
      this.sLong = true; this.drawing = true; this.emit({ type: 'drawStart', at: now });
    }
    if (this.down.V && !this.vIgnored && !this.vLong && now - this.vAt >= this.t.voiceHold) {
      this.vLong = true; this.recording = true; this.emit({ type: 'voiceStart', at: now });
    }
  }
  // 断连、失焦、Esc：结束在途动作，仍按住的键要先松开才能开始新动作。
  reset(now) {
    if (this.drawing) this.emit({ type: 'drawCancel', at: now });
    if (this.recording) this.emit({ type: 'voiceCancel', at: now });
    for (const k of Object.keys(this.down)) if (this.down[k]) { this.down[k] = false; this.emit({ type: 'key', key: k, down: false, at: now }); }
    this.drawing = this.recording = false; this.sLong = this.vLong = false;
  }
}
