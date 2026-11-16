// 智慧呆毛：圆团身体 + 头顶一笔带弧、末端翘弯的呆毛。呆毛是它的“天线”：振动时跳一下，思考时打转。
export function mascotSVG(cls = '') {
  return `<svg class="dm ${cls}" viewBox="0 0 64 64" aria-hidden="true">
    <ellipse cx="22" cy="57" rx="6" ry="3.2" fill="#d8cfc2"/><ellipse cx="42" cy="57" rx="6" ry="3.2" fill="#d8cfc2"/>
    <path d="M10 38 C10 24 20 18 32 18 C44 18 54 24 54 38 C54 50 45 56 32 56 C19 56 10 50 10 38 Z" fill="#f6f1e8"/>
    <path d="M14 46 C20 53 44 53 50 46" stroke="#e4dacb" stroke-width="2" fill="none" stroke-linecap="round"/>
    <g class="ahoge"><path d="M32 20 C29 9 40 2 45 8 C49 13 44 17 40.5 13.5" fill="none" stroke="#f2b33d" stroke-width="3.6" stroke-linecap="round"/>
      <path d="M33.5 15 C33 10 37 6.5 40.5 7.5" fill="none" stroke="#ffe3a3" stroke-width="1.2" stroke-linecap="round"/></g>
    <g class="pupils"><ellipse class="eye" cx="24" cy="37" rx="3.3" ry="4.2" fill="#1a1715"/><ellipse class="eye" cx="40" cy="37" rx="3.3" ry="4.2" fill="#1a1715"/>
      <circle cx="25.2" cy="35.4" r="1.1" fill="#fff"/><circle cx="41.2" cy="35.4" r="1.1" fill="#fff"/></g>
    <g class="happy"><path d="M20.5 38.5 Q24 33.5 27.5 38.5" stroke="#1a1715" stroke-width="2.4" fill="none" stroke-linecap="round"/>
      <path d="M36.5 38.5 Q40 33.5 43.5 38.5" stroke="#1a1715" stroke-width="2.4" fill="none" stroke-linecap="round"/></g>
    <ellipse cx="18" cy="44" rx="3.4" ry="2" fill="#ffb3a0" opacity=".7"/><ellipse cx="46" cy="44" rx="3.4" ry="2" fill="#ffb3a0" opacity=".7"/>
    <path d="M29.5 45 Q32 47.2 34.5 45" stroke="#1a1715" stroke-width="1.6" fill="none" stroke-linecap="round"/>
  </svg>`;
}

export class Mascot {
  constructor(el) { this.el = el; el.innerHTML = mascotSVG(); this.svg = el.querySelector('svg'); }
  mood(m) { this.svg.classList.remove('mood-happy', 'mood-think', 'mood-listen', 'mood-wow'); if (m) this.svg.classList.add('mood-' + m); }
  zap() { this.svg.classList.remove('zap'); void this.svg.getBBox?.(); this.svg.classList.add('zap'); setTimeout(() => this.svg.classList.remove('zap'), 360); }
}

// 跳出灵动岛、在桌面上走动、观摩内容的呆毛。
export class Buddy {
  constructor(el) {
    this.el = el;
    el.innerHTML = `${mascotSVG()}<i class="lens"></i><i class="shadow"></i><div class="bubble"></div>`;
    this.svg = el.querySelector('svg'); this.bubble = el.querySelector('.bubble');
    this.x = 602; this.y = -10; this.out = false;
  }
  mood(m) { Mascot.prototype.mood.call(this, m); }
  place(x, y) { this.x = x; this.y = y; this.el.style.transform = `translate(${x - 38}px,${y - 70}px)`; }
  async hopTo(x, y, { height = 140, ms = 700 } = {}) {
    const x0 = this.x, y0 = this.y; this.el.classList.toggle('flip', x > 1000);
    const frames = [];
    for (let i = 0; i <= 12; i++) {
      const t = i / 12, px = x0 + (x - x0) * t, py = y0 + (y - y0) * t - Math.sin(Math.PI * t) * height;
      const sq = i === 12 ? 'scale(1.12,.86)' : i === 0 ? 'scale(.92,1.08)' : 'scale(1,1)';
      frames.push({ transform: `translate(${px - 38}px,${py - 70}px) ${sq}`, offset: t });
    }
    await this.el.animate(frames, { duration: ms, easing: 'cubic-bezier(.3,.6,.4,1)' }).finished.catch(() => {});
    this.place(x, y);
  }
  async walkTo(x, y, ms = 900) {
    const x0 = this.x, y0 = this.y; this.el.classList.toggle('flip', x > 1000);
    const frames = [];
    for (let i = 0; i <= 16; i++) { const t = i / 16; frames.push({ transform: `translate(${x0 + (x - x0) * t - 38}px,${y0 + (y - y0) * t - 70 - Math.abs(Math.sin(t * Math.PI * 6)) * 6}px)` }); }
    await this.el.animate(frames, { duration: ms, easing: 'linear' }).finished.catch(() => {});
    this.place(x, y);
  }
  say(html, ms) {
    this.bubble.innerHTML = html; this.bubble.classList.add('show');
    clearTimeout(this.sayT); if (ms) this.sayT = setTimeout(() => this.quiet(), ms);
  }
  quiet() { this.bubble.classList.remove('show'); }
  peek(on) { this.el.classList.toggle('peek', on); }
}
