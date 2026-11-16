// 五个场景，三种模式。所有 AI 结果均为本地脚本演出（示例结果），不调用模型、不改动真实文件。
const h = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const center = (r) => ({ x: r.x + r.w / 2, y: r.y + r.h / 2 });
// 手绘感的环形路径（设计坐标）
export function ring(cx, cy, rx, ry, n = 22, wobble = 0.06, start = -2.2) {
  const pts = [];
  for (let i = 0; i <= n + 2; i++) {
    const a = start + (i / n) * Math.PI * 2, k = 1 + Math.sin(i * 1.7) * wobble;
    pts.push({ x: cx + Math.cos(a) * rx * k, y: cy + Math.sin(a) * ry * k });
  }
  return pts;
}
function boundsOf(rects, pad = 0) {
  const x = Math.min(...rects.map((r) => r.x)) - pad, y = Math.min(...rects.map((r) => r.y)) - pad;
  const x2 = Math.max(...rects.map((r) => r.x + r.w)) + pad, y2 = Math.max(...rects.map((r) => r.y + r.h)) + pad;
  return { x, y, w: x2 - x, h: y2 - y };
}
const panelActs = (go = '确认应用', no = '取消') => `<div class="acts"><span class="go"><kbd>L</kbd>${go}</span><span><kbd>R</kbd>${no}</span></div>`;
const said = (t) => `<div class="said">${t}</div>`;

// =====================================================================
// 创作 · CAD 改模
// =====================================================================
const cad = {
  id: 'cad', mode: '创作', title: 'CAD 改模', icon: '⬡', appName: 'Fusion 360',
  desc: '圈出零件特征，说一句，模型就改好', draw: 'lasso', needsSelection: true,
  hint: '圈出要改的特征', keys: '按住 <kbd>S</kbd> 圈',
  pitch: '不用记命令，也不用一个个 Ctrl 点选——圈出来，说出来。',
  mount(app) {
    this.root = h(`<div class="win cad">
      <div class="bar"><span class="tl"><i></i><i></i><i></i></span><b>支架_v7.f3d</b><span>· 已保存</span></div>
      <div class="tools"><span>草图</span><span>拉伸</span><span class="t-hole">孔</span><span class="t-ch">倒角</span><span>圆角</span><span>阵列</span><span>测量</span></div>
      <div class="body">
        <div class="tree"><div>原点</div><div>草图1 · 底板轮廓</div><div>拉伸1 · 6 mm</div><div>草图2 · 立板</div><div>拉伸2 · 6 mm</div><div>孔1 · Ø4.2 ×2</div><div>孔2 · Ø4.2 ×2</div></div>
        <div class="view">
          <svg viewBox="0 0 920 612" preserveAspectRatio="xMidYMid meet">
            <g class="grid">${Array.from({ length: 16 }, (_, i) => `<line x1="${i * 60}" y1="0" x2="${i * 60 - 300}" y2="612"/><line x1="${i * 60 - 300}" y1="0" x2="${i * 60}" y2="612"/>`).join('')}</g>
            <g transform="translate(60,70)">
              <polygon class="face-front" points="200,330 440,420 440,450 200,360"/>
              <polygon class="face-side" points="440,420 760,330 760,360 440,450"/>
              <polygon class="face-top" points="200,330 520,240 760,330 440,420"/>
              <polygon class="chamfer" points="440,420 760,330 750,324 438,412" fill="#e6ebf0"/>
              <polygon class="chamfer" points="200,330 440,420 438,412 208,326" fill="#e6ebf0"/>
              <polygon class="face-side" points="200,130 224,139 224,339 200,330"/>
              <polygon class="face-top" points="200,130 520,40 544,49 224,139"/>
              <polygon class="face-front" points="224,139 544,49 544,249 224,339" style="fill:#a7b1bc"/>
              <g class="base-holes">
                <ellipse class="hole h-b" cx="412" cy="357" rx="17" ry="9.5"/><ellipse class="csk" cx="412" cy="357" rx="26" ry="14.5"/><ellipse class="hole" cx="412" cy="357" rx="12" ry="6.6"/>
                <ellipse class="hole h-b" cx="572" cy="312" rx="17" ry="9.5"/><ellipse class="csk" cx="572" cy="312" rx="26" ry="14.5"/><ellipse class="hole" cx="572" cy="312" rx="12" ry="6.6"/>
                <ellipse class="feat-hl" cx="412" cy="357" rx="34" ry="20"/><ellipse class="feat-hl" cx="572" cy="312" rx="34" ry="20"/>
              </g>
              <g class="wall-holes">
                <ellipse class="hole h-w" cx="320" cy="202" rx="10" ry="16" transform="rotate(-16 320 202)"/>
                <ellipse class="hole h-w" cx="448" cy="166" rx="10" ry="16" transform="rotate(-16 448 166)"/>
                <ellipse class="feat-hl" cx="320" cy="202" rx="20" ry="28" transform="rotate(-16 320 202)"/><ellipse class="feat-hl" cx="448" cy="166" rx="20" ry="28" transform="rotate(-16 448 166)"/>
              </g>
              <polyline class="edge" points="200,330 520,240 760,330 440,420 200,330"/>
              <text class="dim d1" x="600" y="440">底板 120 × 80 × 6</text>
            </g>
          </svg>
          <div class="props"><b>选择</b><span class="pv">未选择 · 圈出零件上的特征</span></div>
        </div>
      </div>
    </div>`);
    app.apps.appendChild(this.root); this.applied = false; this.target = null;
  },
  onClear() { this.root.querySelectorAll('.feat-hl').forEach((e) => e.classList.remove('on')); this.root.querySelector('.pv').textContent = '未选择 · 圈出零件上的特征'; },
  select(app, sel) {
    const base = [...this.root.querySelectorAll('.h-b')], wall = [...this.root.querySelectorAll('.h-w')];
    const nb = base.filter((e) => app.hits(e, sel)).length, nw = wall.filter((e) => app.hits(e, sel)).length;
    if (!nb && !nw) return { ok: false, msg: '圈里没有可识别的特征，靠近孔位再圈一次' };
    this.target = nb >= nw ? 'base' : 'wall';
    const g = this.root.querySelector(this.target === 'base' ? '.base-holes' : '.wall-holes');
    g.querySelectorAll('.feat-hl').forEach((e) => e.classList.add('on'));
    this.root.querySelector('.t-hole').classList.add('hl');
    this.root.querySelector('.pv').innerHTML = `快速模型识别 · 0.4 s<br>${this.target === 'base' ? '底板' : '立板'}通孔 Ø4.2 × 2，深 6 mm<br>与 3 个约束关联`;
    return { ok: true, label: `${this.target === 'base' ? '底板' : '立板'}通孔 ×2` };
  },
  utterance: () => '把这两个孔改成 M4 沉头孔，底板外沿顺便倒个 2 毫米的角',
  async onVoice(app, text) {
    app.island.think('快速模型理解意图 · 匹配特征…'); await app.sleep(900);
    app.island.think('生成特征操作 · 检查约束…'); await app.sleep(900);
    const where = this.target === 'base' ? '底板' : '立板';
    app.showPanel(`<h4>AI 修改预览</h4><div class="sub">支架_v7 · 2 步特征操作 · 不触碰其他特征</div>${said(text)}
      <ul><li class="ok"><i>1</i>${where}孔 ×2 → M4 沉头孔（Ø8.4 × 90°）</li><li class="ok"><i>2</i>底板外沿 2 条棱 → 倒角 C2</li><li><i>✓</i>其余 12 个约束保持不变</li></ul>
      <div class="ba"><div><b>修改前</b>通孔 Ø4.2 · 直角外沿</div><div><b>修改后</b>沉头 M4 · C2 倒角</div></div>${panelActs()}`);
    app.island.hint('左边是修改预览', '<kbd>L</kbd> 应用 · <kbd>R</kbd> 取消'); app.islMascot.mood('happy');
    app.phase = 'preview';
  },
  async onConfirm(app) {
    app.island.think('写入特征树…'); await app.sleep(700);
    this.root.classList.add('applied'); app.clearInk(); this.onClear();
    const tree = this.root.querySelector('.tree');
    tree.append(h('<div class="new">沉头孔 · M4 ×2</div>'), h('<div class="new">倒角 · C2</div>'));
    this.root.querySelector('.pv').innerHTML = `<span class="chg">孔 Ø4.2 → 沉头 M4 Ø8.4×90°</span><br><span class="chg">外沿 → 倒角 C2</span><br>重建 0.8 s · 无错误`;
    this.root.querySelector('.d1').textContent = '底板 120 × 80 × 6 · C2';
    app.haptic('success'); app.island.done('已修改 · 2 个沉头孔 + C2 倒角 · ⌘Z 可撤销');
    app.selection = null; app.phase = 'idle';
  },
  async demo(d) {
    const { app } = d;
    d.caption('改一个 CAD 模型：<b>圈出</b>要改的孔', '背键 S 按住，倾斜手柄画一圈——松开，“嗒嗒”两下，圈闭合了');
    await d.wait(1200);
    const r = boundsOf([...this.root.querySelectorAll('.h-b')].map(app.rectOf), 26), c = center(r);
    await d.draw(ring(c.x, c.y, r.w / 2 + 16, r.h / 2 + 22, 24), 1500);
    d.caption('快速模型 0.4 秒认出：<b>两个 Ø4.2 通孔</b>', '右上角属性栏同步显示识别结果和关联约束');
    await d.wait(1800);
    d.caption('按住背键 V，<b>说出</b>要改成什么', '按下的瞬间锁定目标——说话时手怎么动，“这里”都不会变');
    await d.say(this.utterance());
    d.caption('左侧出现<b>修改预览</b>：做什么、不碰什么，一目了然', '手柄不替你决定——L 确认才会写入模型');
    await d.wait(2600);
    await d.tap('L'); await d.until(() => app.phase === 'idle');
    d.caption('<b>两步特征</b>写入特征树，模型重建完成', '马达“嗒—嗒啦”：成功只跟随真实执行回执');
    await d.wait(2600);
  },
};

// =====================================================================
// 创作 · 网页微调
// =====================================================================
const web = {
  id: 'web', mode: '创作', title: '网页微调', icon: '◩', appName: 'Chrome',
  desc: '在页面上涂一下，再说一句，左边确认就改', draw: 'brush', needsSelection: true,
  hint: '涂抹要改的区域', keys: '按住 <kbd>S</kbd> 涂',
  pitch: '涂抹比框选更随手：盖住哪儿，就是哪儿。',
  mount(app) {
    this.root = h(`<div class="win browser">
      <div class="bar"><span class="tl"><i></i><i></i><i></i></span><div class="url">localhost:5173 / grip-landing</div></div>
      <div class="site">
        <nav><b>GRIP</b><span>产品</span><span>场景</span><span>开发者</span><span>预约</span></nav>
        <div class="device"></div>
        <div class="hero"><h2 class="h2">一只手，<br>指挥你的 AI。</h2><p class="p">倾斜指向、背键圈选、按住说话。离开键盘鼠标，也能把想法交给 AI 完成。</p><span class="cta">了解更多</span></div>
        <div class="cards"><div class="c1"><b>圈选即上下文</b>选中的就是 AI 要看的。</div><div class="c2"><b>说话即指令</b>不用再组织长长的提示词。</div><div class="c3"><b>确认才执行</b>每一步都由你点头。</div></div>
      </div></div>`);
    app.apps.appendChild(this.root); this.target = null;
  },
  select(app, sel) {
    const cands = [['.cta', '主按钮'], ['.h2', '主标题'], ['.p', '介绍文字'], ['.c1', '卡片 1'], ['.c2', '卡片 2'], ['.c3', '卡片 3']];
    let best = null, n = 0;
    for (const [q, label] of cands) { const el = this.root.querySelector(q), k = app.hits(el, sel); if (k > n) { n = k; best = [el, label, q]; } }
    if (!best || n < 3) return { ok: false, msg: '没盖住页面元素，再涂一下' };
    this.target = best[2]; app.markBox(app.rectOf(best[0]), `① ${best[1]} · <button>`.replace('<button>', best[2] === '.cta' ? '&lt;a.cta&gt;' : '元素'));
    return { ok: true, label: best[1] };
  },
  utterance: () => '按钮换成呆毛金的渐变，做成胶囊圆角，文字改成"立即预约体验"',
  async onVoice(app, text) {
    app.island.think('读取选中元素与样式 · 生成补丁…'); await app.sleep(1300);
    app.showPanel(`<h4>修改 1 处 · 主按钮</h4><div class="sub">src/components/Hero.vue · 3 行样式 + 1 行文案</div>${said(text)}
      <div class="ba"><div><b>修改前</b><span style="display:inline-block;background:#2d6cdf;color:#fff;border-radius:5px;padding:6px 10px;font-size:11px">了解更多</span></div>
      <div><b>修改后</b><span style="display:inline-block;background:linear-gradient(135deg,#f2b33d,#ff9a3d);color:#1b1408;border-radius:99px;padding:6px 12px;font-size:11px;font-weight:700">立即预约体验</span></div></div>
      <ul><li><i>−</i><code>background:#2d6cdf; border-radius:6px</code></li><li class="ok"><i>+</i><code>background:linear-gradient(135deg,#f2b33d,#ff9a3d)</code></li><li class="ok"><i>+</i><code>border-radius:999px; padding:15px 30px</code></li></ul>${panelActs('在左边确认，写入页面')}`);
    app.island.hint('左边确认就改', '<kbd>L</kbd> 应用 · <kbd>R</kbd> 取消'); app.islMascot.mood('happy');
    app.phase = 'preview';
  },
  async onConfirm(app) {
    app.island.think('写入 Hero.vue · 热更新…'); await app.sleep(800);
    app.clearInk(); const site = this.root.querySelector('.site'); site.classList.add('applied');
    this.root.querySelector('.cta').textContent = '立即预约体验';
    app.haptic('success'); app.island.done('已写入 Hero.vue · 页面热更新完成');
    app.selection = null; app.phase = 'idle';
  },
  async demo(d) {
    const { app } = d;
    d.caption('改网页：在按钮上<b>涂一笔</b>', '不用精确对准——涂抹盖住的元素，就是要改的元素');
    await d.wait(1200);
    const r = app.rectOf(this.root.querySelector('.cta')), y = r.y + r.h / 2;
    await d.draw([{ x: r.x - 6, y }, { x: r.x + r.w * 0.5, y: y - 6 }, { x: r.x + r.w + 8, y: y + 2 }, { x: r.x + r.w * 0.45, y: y + 8 }, { x: r.x + 4, y: y + 2 }, { x: r.x + r.w * 0.7, y: y - 4 }], 1300);
    d.caption('认出 <b>主按钮</b>，按住 V 说出想要的样子');
    await d.wait(1200);
    await d.say(this.utterance());
    d.caption('<b>在左边确认</b>：前后对比 + 真实代码补丁', '只改选中的这一处，不顺手动别的');
    await d.wait(2800);
    await d.tap('L'); await d.until(() => app.phase === 'idle');
    d.caption('写入、热更新，<b>马上看到结果</b>'); await d.wait(2400);
  },
};

// =====================================================================
// AI 协助 · 整理桌面
// =====================================================================
const FILES = [
  ['报价单_final.docx', 'doc', 'DOC', '#2d6cdf', 70, 70], ['报价单_final_v3.docx', 'doc', 'DOC', '#2d6cdf', 190, 60], ['报价单_final_v3(1).docx', 'doc', 'DOC', '#2d6cdf', 300, 90],
  ['截屏 11-02 10.21', 'img', '', '', 470, 60], ['截屏 11-02 10.24', 'img', '', '', 580, 110], ['截屏 11-03 16.08', 'img', '', '', 420, 200], ['截屏 11-04 09.12', 'img', '', '', 760, 70], ['截屏 11-05 21.40', 'img', '', '', 880, 150],
  ['会议纪要 1103.md', 'doc', 'MD', '#5b6b7d', 120, 230], ['BOM_R2.xlsx', 'doc', 'XLS', '#1f8a4c', 250, 300], ['原理图_R2.pdf', 'doc', 'PDF', '#c0392b', 640, 250],
  ['EasyEDA-Pro.dmg', 'dmg', '', '', 960, 290], ['FreeCAD-1.0.dmg', 'dmg', '', '', 820, 330], ['未命名文件夹', 'folder', '', '', 300, 420],
];
const desk = {
  id: 'desk', mode: 'AI 协助', title: '整理桌面', icon: '▦', appName: 'Finder',
  desc: '圈住整个桌面，说“清理一下”', draw: 'lasso', needsSelection: true,
  hint: '圈住要整理的文件', keys: '按住 <kbd>S</kbd> 圈',
  pitch: '呆毛会从灵动岛跳下来，先看清楚，再动手。',
  mount(app) {
    this.icons = FILES.map(([n, k, t, c, x, y]) => {
      const el = h(`<div class="icon ${k}" style="left:${x}px;top:${y}px"><div class="g" data-t="${t}" style="--c:${c}"></div><span>${n}</span></div>`);
      el.dataset.kind = k; el.dataset.name = n; app.apps.appendChild(el); return el;
    });
  },
  onClear() { this.icons.forEach((i) => i.classList.remove('sel')); },
  select(app, sel) {
    const inside = this.icons.filter((i) => app.hits(i, sel));
    if (inside.length < 3) return { ok: false, msg: '圈住的文件太少，圈大一点' };
    inside.forEach((i) => i.classList.add('sel')); this.sel = inside;
    return { ok: true, label: `${inside.length} 个文件` };
  },
  utterance: () => '你帮我把这些文档清理一下',
  async onVoice(app, text) {
    const b = app.buddy, pick = (re) => this.sel.filter((i) => re.test(i.dataset.name));
    app.island.think('呆毛下来看看…');
    const first = app.rectOf(this.sel[0]);
    await app.buddyOut(first.x + 40, first.y + 70);
    b.say('我先看看都有些什么～', 1400); await app.sleep(1200);
    const groups = [
      [pick(/报价单/), '这 <b>3 份报价单</b>几乎一样，只有 v3 是最新的'],
      [pick(/截屏/), '<b>5 张截屏</b>都是这周的，散在各处'],
      [pick(/\.dmg/), '<b>2 个安装包</b>已经装好了，留着占地方'],
      [pick(/纪要|BOM|原理图/), '纪要、BOM、原理图是 <b>R2 项目资料</b>'],
    ];
    for (const [list, msg] of groups) {
      if (!list.length) continue;
      const r = app.rectOf(list[0]);
      await b.walkTo(r.x + 46, r.y + 74, 700); b.peek(true);
      list.forEach((i) => i.classList.add('peek')); b.say(msg); await app.sleep(1500);
      list.forEach((i) => i.classList.remove('peek')); b.peek(false);
    }
    b.mood('think'); b.say('想好了，方案放在左边给你看');
    app.showPanel(`<h4>整理方案 · ${this.sel.length} 个文件</h4><div class="sub">3 个子 Agent 并行 · 只移动，不永久删除</div>${said(text)}
      <div class="agents"><div class="agent run" data-a="1"><i class="sp"></i>归类 · 按类型与项目<span class="st">运行中</span></div>
      <div class="agent wait" data-a="2"><i class="sp"></i>去重 · 比对内容指纹<span class="st">排队</span></div>
      <div class="agent wait" data-a="3"><i class="sp"></i>命名 · 统一日期格式<span class="st">排队</span></div></div><div class="plan"></div>`);
    for (const a of [1, 2, 3]) {
      const el = app.panel.querySelector(`[data-a="${a}"]`); el.className = 'agent run'; el.querySelector('.st').textContent = '运行中';
      await app.sleep(800); el.className = 'agent done'; el.querySelector('.st').textContent = '完成';
    }
    app.panel.querySelector('.plan').innerHTML = `<ul><li class="ok"><i>→</i>R2 项目资料 3 个 → 「文稿 / R2 控制器」</li><li class="ok"><i>→</i>截屏 5 张 → 「截屏 / 2026-11」</li><li class="ok"><i>→</i>报价单保留 v3，旧版 2 份 → 废纸篓</li><li class="warn"><i>!</i>安装包 2 个 → 废纸篓（可随时恢复）</li></ul>${panelActs('照这样整理')}`;
    b.mood('happy'); b.say('<b>L</b> 就开工，<b>R</b> 我就不动', 2400);
    app.island.hint('整理方案已就绪', '<kbd>L</kbd> 开工 · <kbd>R</kbd> 不动');
    app.phase = 'preview';
  },
  onBack(app) { app.buddyHome(); },
  async onConfirm(app) {
    const b = app.buddy; app.clearInk();
    const folders = [['文稿 / R2 控制器', 1030, 420], ['截屏 / 2026-11', 1030, 530], ['废纸篓', 1150, 640]].map(([n, x, y]) => {
      const el = h(`<div class="icon folder" style="left:${x}px;top:${y}px;opacity:0"><div class="g"></div><span>${n}</span></div>`);
      if (n === '废纸篓') { el.className = 'icon dmg'; el.querySelector('.g').style.background = 'linear-gradient(#e9edf1,#aab3bd)'; el.querySelector('.g').style.borderRadius = '8px 8px 14px 14px'; }
      app.apps.appendChild(el); requestAnimationFrame(() => (el.style.opacity = 1)); return el;
    });
    app.island.think('子 Agent 正在移动文件…'); b.say('开工！', 900);
    await b.walkTo(1000, 520, 700);
    const dest = (i) => (/纪要|BOM|原理图/.test(i.dataset.name) ? folders[0] : /截屏/.test(i.dataset.name) ? folders[1] : /\.dmg|报价单_final(\.docx|_v3\(1\))/.test(i.dataset.name) ? folders[2] : null);
    let moved = 0;
    for (const i of this.sel) {
      const f = dest(i); if (!f) continue;
      i.classList.remove('sel'); i.style.left = f.style.left; i.style.top = f.style.top; i.classList.add('gone'); moved++;
      app.haptic('tick'); await app.sleep(220);
    }
    const keep = this.sel.find((i) => /v3\.docx$/.test(i.dataset.name)); if (keep) { keep.classList.remove('sel'); keep.style.left = '1030px'; keep.style.top = '300px'; }
    const tf = folders[0].querySelector('span'); tf.insertAdjacentHTML('afterend', '<i class="badge-n">3</i>');
    app.haptic('success'); b.mood('happy'); b.say(`搞定！移走 <b>${moved}</b> 个文件，废纸篓里都能找回`, 2600);
    app.island.done(`桌面已整理 · ${moved} 个文件归位 · 可在废纸篓恢复`);
    await app.sleep(2400); await app.buddyHome();
    app.island.done(`桌面已整理 · ${moved} 个文件归位`); app.selection = null; app.phase = 'idle';
  },
  async demo(d) {
    const { app } = d;
    d.caption('AI 协助：桌面乱了？<b>把整个桌面圈起来</b>', '圈选会把这些文件作为上下文，一起交给后台 Agent');
    await d.wait(1200);
    await d.draw(ring(590, 290, 565, 255, 26, 0.04), 2000);
    d.caption('按住 V：<b>“你帮我把这些文档清理一下”</b>');
    await d.wait(900);
    await d.say(this.utterance(), 2200);
    d.caption('呆毛从灵动岛<b>跳下来</b>，挨个观摩你圈住的内容', '三个子 Agent 并行：归类、去重、命名——方案先给你看');
    await d.until(() => app.phase === 'preview', 25000);
    await d.wait(2200);
    await d.tap('L');
    d.caption('<b>L</b> 开工：文件各回各家，只移动，不永久删除');
    await d.until(() => app.phase === 'idle', 20000); await d.wait(1600);
  },
};

// =====================================================================
// AI 协助 · 空间诊断
// =====================================================================
const SEG = [['系统', 24, '#8e8e93'], ['应用', 48, '#2d6cdf'], ['开发者', 96, '#f2b33d'], ['文稿', 38, '#5fd3b5'], ['其他', 41, '#c9b8a6']];
const disk = {
  id: 'disk', mode: 'AI 协助', title: '空间诊断', icon: '◔', appName: '系统设置',
  desc: '磁盘满了？问一句“为啥”', draw: 'lasso', needsSelection: true,
  hint: '圈住提示和存储条', keys: '按住 <kbd>S</kbd> 圈',
  pitch: '不只是清理——呆毛会告诉你，为什么又满了。',
  mount(app) {
    this.alert = h(`<div class="alert"><i class="ic"></i><div><b>磁盘几乎已满</b><p>“Macintosh HD”只剩 9 GB 可用。请删除不需要的文件以释放空间。</p></div></div>`);
    this.win = h(`<div class="win storage"><div class="bar"><span class="tl"><i></i><i></i><i></i></span><b>存储空间</b></div><div class="sbody">
      <h3>Macintosh HD</h3><div class="cap">已用 <b class="used">247</b> GB / 256 GB</div>
      <div class="sbar">${SEG.map(([n, g, c]) => `<i data-n="${n}" style="width:${(g / 256) * 100}%;background:${c}"></i>`).join('')}</div>
      <div class="slist">
        <div data-k="dd"><i style="background:#f2b33d"></i>Xcode DerivedData<em>41 GB</em></div>
        <div data-k="sim"><i style="background:#f2b33d"></i>iOS 模拟器旧运行时<em>18 GB</em></div>
        <div data-k="idf"><i style="background:#f2b33d"></i>ESP-IDF build/ ×6<em>9 GB</em></div>
        <div data-k="wx"><i style="background:#c9b8a6"></i>微信聊天缓存<em>12 GB</em></div>
        <div><i style="background:#2d6cdf"></i>应用程序<em>48 GB</em></div>
        <div><i style="background:#5fd3b5"></i>文稿<em>38 GB</em></div>
      </div></div></div>`);
    app.apps.append(this.win, this.alert);
  },
  select(app, sel) {
    const a = app.hits(this.alert, sel), w = app.hits(this.win, sel);
    if (!a && !w) return { ok: false, msg: '圈住“磁盘已满”提示或存储窗口' };
    app.markBox(app.rectOf(a && !w ? this.alert : this.win), a && w ? '提示 + 存储概览' : a ? '磁盘已满提示' : '存储概览');
    return { ok: true, label: a && w ? '提示 + 存储概览' : a ? '磁盘已满提示' : '存储概览' };
  },
  utterance: () => '空间怎么又满了？帮我清一下，顺便说说为啥',
  async onVoice(app, text) {
    const b = app.buddy, row = (k) => this.win.querySelector(`[data-k="${k}"]`);
    app.island.think('呆毛去存储条里挖一挖…');
    const bar = app.rectOf(this.win.querySelector('.sbar'));
    await app.buddyOut(bar.x + bar.w * 0.45, bar.y + 4);
    b.peek(true); b.say('开发者数据有 <b>96 GB</b>，我钻进去看看'); await app.sleep(1600);
    for (const [k, msg] of [['dd', 'Xcode 编译中间件 <b>41 GB</b>，都能重新生成'], ['sim', '旧模拟器运行时 <b>18 GB</b>，你已经不用 iOS 16 了'], ['idf', '6 个 ESP-IDF build/ 共 <b>9 GB</b>'], ['wx', '微信缓存 <b>12 GB</b>——这个得你点头']]) {
      const r = app.rectOf(row(k)); row(k).classList.add('hot');
      await b.walkTo(r.x + 60, r.y + 6, 600); b.say(msg); await app.sleep(1300);
    }
    b.peek(false); b.mood('think');
    b.say('<b>原因找到了：</b>这两周你每天都在编固件和 App，编译中间件从来没清过。');
    await app.sleep(2200);
    app.showPanel(`<h4>清理方案 · 可释放 68 GB</h4><div class="sub">只清能重新生成的文件；个人数据不动</div>${said(text)}
      <ul><li class="ok"><i>✓</i>Xcode DerivedData · 41 GB（下次编译自动重建）</li><li class="ok"><i>✓</i>iOS 16 模拟器运行时 · 18 GB</li><li class="ok"><i>✓</i>ESP-IDF build/ ×6 · 9 GB（idf.py build 可重建）</li><li class="warn"><i>?</i>微信缓存 12 GB · 不包含，需要你单独确认</li><li><i>↻</i>建议：每周日自动清理 DerivedData</li></ul>${panelActs('清理 68 GB')}`);
    b.mood('happy'); b.say('方案在左边，<b>L</b> 就清', 2400);
    app.island.hint('诊断完成 · 可释放 68 GB', '<kbd>L</kbd> 清理 · <kbd>R</kbd> 算了');
    app.phase = 'preview';
  },
  onBack(app) { app.buddyHome(); this.win.querySelectorAll('.hot').forEach((e) => e.classList.remove('hot')); },
  async onConfirm(app) {
    const b = app.buddy; app.clearInk(); app.island.think('正在清理 · 41 + 18 + 9 GB…');
    for (const k of ['dd', 'sim', 'idf']) { const r = this.win.querySelector(`[data-k="${k}"]`); r.classList.remove('hot'); r.classList.add('cleaned'); app.haptic('tick'); await app.sleep(500); }
    this.win.querySelector('[data-k="wx"]').classList.remove('hot');
    this.win.querySelector('[data-n="开发者"]').style.width = `${(28 / 256) * 100}%`;
    let used = 247; const t = setInterval(() => { used = Math.max(179, used - 4); this.win.querySelector('.used').textContent = used; if (used === 179) clearInterval(t); }, 40);
    this.alert.style.transition = 'opacity .5s'; this.alert.style.opacity = 0;
    app.haptic('success'); b.mood('happy'); b.say('释放了 <b>68 GB</b>！以后每周日我帮你清一次', 2600);
    app.island.done('已释放 68 GB · 可用 9 → 77 GB');
    await app.sleep(2600); await app.buddyHome(); app.island.done('已释放 68 GB · 可用 77 GB'); app.selection = null; app.phase = 'idle';
  },
  async demo(d) {
    const { app } = d;
    d.caption('磁盘又满了：<b>圈住提示和存储条</b>');
    await d.wait(1000);
    const r = boundsOf([app.rectOf(this.win), app.rectOf(this.alert)], 10), c = center(r);
    await d.draw(ring(c.x, c.y + 10, r.w / 2 + 10, r.h / 2 + 4, 26, 0.03), 1800);
    d.caption('说：<b>“空间怎么又满了？帮我清一下，顺便说说为啥”</b>');
    await d.wait(800);
    await d.say(this.utterance(), 2600);
    d.caption('呆毛跳进存储条“挖”数据，边看边讲', '诊断出<b>根因</b>，而不只是给一个“清理”按钮');
    await d.until(() => app.phase === 'preview', 30000); await d.wait(2400);
    await d.tap('L');
    d.caption('能重建的才清，<b>个人数据要你点头</b>');
    await d.until(() => app.phase === 'idle', 20000); await d.wait(1400);
  },
};

// =====================================================================
// 办公 · 只用语音
// =====================================================================
const MAILS = [
  ['陈经理', '下周二订单交期确认', '麻烦确认一下 R2 第一批 50 套的交期…', false],
  ['张工', '样机评审会时间确认', '周四下午我们想看一下两台样机的实物…', true],
  ['嘉立创', '您的订单已发货', 'PCB 订单 JLC-1105 已发货，预计…', true],
  ['李设计', 'ID07 外观第三轮', '附上调整后的握持六视图，重点看…', false],
  ['财务', '11 月报销提醒', '请于 11 月 15 日前提交本月报销…', false],
];
const office = {
  id: 'office', mode: '办公', title: '语音办公', icon: '✉', appName: '邮件',
  desc: '没有键盘鼠标，也能读、回、约', draw: null, noDraw: '办公模式不需要圈选：指着邮件按 L 打开，按住 V 直接说',
  hint: '倾斜指向邮件，L 打开；按住 V 直接说', keys: '<kbd>V</kbd> 说',
  pitch: '躺在沙发上、站在会议室里——只有一只手柄，照样办公。',
  mount(app) {
    this.root = h(`<div class="win mail"><div class="bar"><span class="tl"><i></i><i></i><i></i></span><b>收件箱</b><span>· 2 封未读</span></div>
      <div class="mbody"><div class="list"><div class="scroll">${MAILS.map(([f, s, p, u], i) => `<div class="item ${u ? 'unread' : ''}" data-i="${i}"><b>${f}</b><span>${s}</span><span>${p}</span></div>`).join('')}</div></div>
      <div class="read"><div class="from" style="margin-top:200px;text-align:center">指着一封邮件按 <b>L</b>，或者按住 <b>V</b> 说“打开张工的邮件”</div></div></div></div>`);
    app.apps.appendChild(this.root); this.open = -1; this.summarized = false; this.draft = null;
  },
  onHover(app, p) {
    let hit = -1;
    this.root.querySelectorAll('.item').forEach((el) => { const r = app.rectOf(el); const on = p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h; el.classList.toggle('hover', on); if (on) hit = +el.dataset.i; });
    if (hit !== this.hover) { this.hover = hit; if (hit >= 0) app.haptic('tick'); }
  },
  onPrimary(app) { if (this.hover >= 0) this.openMail(app, this.hover); },
  openMail(app, i) {
    this.open = i; this.summarized = false; this.draft = null;
    this.root.querySelectorAll('.item').forEach((el) => { el.classList.toggle('on', +el.dataset.i === i); if (+el.dataset.i === i) el.classList.remove('unread'); });
    const [f, s] = MAILS[i];
    const body = i === 1 ? '你好，<br><br>周四下午我们这边想看一下两台样机的实物，重点是握持手感和背键行程。时间上 14:00–17:00 都可以，地点在我们二楼会议室。另外如果方便，麻烦把最新的 R2 原理图和 BOM 一起带上，我们想同步评估一下量产风险。<br><br>谢谢！<br>张工' : `${MAILS[i][2]}<br><br>（示例邮件）`;
    this.root.querySelector('.read').innerHTML = `<h3>${s}</h3><div class="from">${f} · 今天 13:58 · 发给 我</div><div class="txt">${body}</div><div class="slot"></div>`;
    app.haptic('tick'); app.island.hint(`已打开 · ${s}`, '按住 <kbd>V</kbd> 说');
  },
  utterance() {
    if (this.open < 0) return '打开张工那封样机评审的邮件';
    if (!this.summarized) return '帮我总结一下这封邮件';
    return '回复他：周四下午三点可以，我会带两台样机和 R2 的资料过去';
  },
  async onVoice(app, text) {
    if (this.open < 0 || /打开|张工/.test(text) && !/回复|总结/.test(text)) {
      app.island.think('找邮件…'); await app.sleep(600); this.openMail(app, 1); return;
    }
    const slot = this.root.querySelector('.slot');
    if (!this.summarized && !/回复|回他|答复/.test(text)) {
      app.island.think('呆毛在读邮件…'); await app.sleep(1100);
      slot.innerHTML = `<div class="sum">✦ <b>一句话：</b>张工想<b>周四 14–17 点</b>在二楼会议室看两台样机（握持、背键行程），并希望带上 <b>R2 原理图和 BOM</b>。<br>✦ <b>需要你：</b>定一个时间、准备资料。</div>`;
      this.summarized = true; app.haptic('tick'); app.island.done('已总结 · 按住 V 说怎么回复'); return;
    }
    app.island.think('起草回复 · 检查日程冲突…'); await app.sleep(1000);
    slot.insertAdjacentHTML('beforeend', `<div class="draft"><div class="lbl">回复草稿 · 未发送</div><span class="typing"></span></div>`);
    const span = slot.querySelector('.draft .typing');
    const reply = '张工好，周四下午 15:00 可以，我会带两台样机过去，R2 原理图和 BOM 也一并带上。到时见！';
    for (let k = 0; k <= reply.length; k += 2) { span.textContent = reply.slice(0, k); await app.sleep(28); }
    span.classList.remove('typing'); this.draft = slot.querySelector('.draft');
    app.showPanel(`<h4>发送前确认</h4><div class="sub">收件人：张工 · 抄送：无</div>${said(text)}<ul><li class="ok"><i>✉</i>发送回复（右侧草稿）</li><li class="ok"><i>◷</i>新建日程：周四 15:00 样机评审 · 二楼会议室</li><li><i>✓</i>周四 15:00 没有冲突</li></ul>${panelActs('发送并加日程', '先不发')}`);
    app.island.hint('草稿好了，左边确认', '<kbd>L</kbd> 发送 · <kbd>R</kbd> 先不发'); app.islMascot.mood('happy');
    app.phase = 'preview';
  },
  onBack() { this.draft?.remove(); this.draft = null; },
  async onConfirm(app) {
    app.island.think('发送中…'); await app.sleep(700);
    this.draft.classList.add('sent'); this.draft.querySelector('.lbl').textContent = '已发送 · 14:33';
    app.apps.appendChild(h('<div class="cal"><b>新日程</b>周四 15:00–16:00<br>样机评审 · 二楼会议室</div>'));
    app.haptic('success'); app.island.done('已发送，并加进周四日程'); app.phase = 'idle';
  },
  async demo(d) {
    const { app } = d;
    d.caption('办公模式：<b>没有键盘和鼠标</b>，只有这一只手柄');
    await d.wait(1300);
    const it = app.rectOf(this.root.querySelector('[data-i="1"]'));
    d.caption('倾斜手柄扫过邮件列表，<b>每过一封，轻轻一震</b>', '触觉代替视线确认：不用盯着光标');
    await d.move(it.x + 40, it.y - 60, 500); await d.move(it.x + 60, it.y + it.h * 2.5, 900); await d.move(it.x + 80, it.y + it.h / 2, 600);
    await d.tap('L'); await d.wait(1200);
    d.caption('按住 V：<b>“帮我总结一下这封邮件”</b>');
    await d.say('帮我总结一下这封邮件', 2000); await d.wait(2400);
    d.caption('按住 V：<b>“回复他：周四下午三点可以…”</b>', '呆毛起草回复，顺手查了日程冲突');
    await d.say(this.utterance(), 4200);
    await d.until(() => app.phase === 'preview', 15000); await d.wait(2200);
    await d.tap('L'); await d.until(() => app.phase === 'idle');
    d.caption('<b>发送 + 日程</b>，一次确认完成'); await d.wait(2400);
  },
};

export const SCENES = [cad, web, desk, disk, office];

export async function INTRO(d) {
  const { app } = d;
  app.island.idle();
  d.caption('它住在<b>刘海</b>里——智慧呆毛', '平时只露出一点点，不打扰你工作');
  await d.wait(2600);
  await d.move(640, 300, 600);
  d.caption('背键 S <b>轻按一下</b>，灵动岛展开', '每一个界面、每一种模式，都在这里流转');
  await d.tap('S'); await d.wait(1400);
  d.caption('<b>倾斜手柄</b>左右挑选——每跨一格，马达“嗒”一下');
  for (const dx of [80, 80, 80, -80, -80, -80]) { await d.move(app.pointer.x + dx, 300, 280); await d.wait(220); }
  d.caption('<b>L</b> 进入。先从创作模式开始');
  await d.wait(900); await d.tap('L'); await d.wait(900);
}
export async function OUTRO(d) {
  const { app } = d;
  await d.move(640, 300, 500); await d.tap('S'); await d.wait(800);
  d.caption('<b>圈出来、说出来、点个头</b>——一只手柄，流转所有界面', '四个键 + 陀螺仪 + 马达，就是全部交互');
  await d.wait(3600); await d.tap('R'); app.island.idle();
  d.caption('现在轮到你：鼠标＝倾斜，按住 <b>D</b>＝S 圈选，按住 <b>空格</b>＝V 说话', '接上 AI KEY 后，右侧「连接 AI KEY」即可用实物操作');
}
