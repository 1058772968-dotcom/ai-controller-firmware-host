import AppKit
import InspireCore

/// 浏览部分的日志：~/Library/Logs/AIKeyInspire/browse.jsonl（目标模式扫描、下一条、关闭弹窗）
let browseLog = JSONLLog(name: "browse")

// MARK: - B2 目标模式 + B3 下一条相关的

/// ⌃⌥G 开关。打开后：滚动停下、点击之后重新扫屏上的卡片，Jev 给每张卡片打相关度、判断是不是推广，
/// 相关的加绿框，无关和推广的压暗。结果按“目标 + 卡片文字”缓存，同一张卡不重复问。
final class TargetMode {
    private let state: AppState
    private let overlay: OverlayController
    private let queue = DispatchQueue(label: "aikey.inspire.target")
    private var cache: [String: CardJudgement] = [:]
    private(set) var cards: [PageCard] = []
    private var judgements: [String: CardJudgement] = [:]
    private var token = 0
    private var pending: DispatchWorkItem?
    private var monitors: [Any] = []
    private var emptyRetries = 0
    /// 没有目标时向用户要一个（AppDelegate 弹输入框）
    var askGoal: ((@escaping (String) -> Void) -> Void)?

    init(state: AppState, overlay: OverlayController) {
        self.state = state
        self.overlay = overlay
    }

    var on: Bool { state.targetModeOn }

    func toggle() { on ? disable(message: "目标模式已关闭") : enable(ask: true) }

    func enable(ask: Bool) {
        let goal = state.userGoal.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !goal.isEmpty else {
            if ask { askGoal? { [weak self] g in self?.state.userGoal = g; self?.enable(ask: false) } }
            return
        }
        let wasOn = on
        state.targetModeOn = true
        if !wasOn { install() }
        overlay.toast("目标模式：\(goal)（再按 ⌃⌥G 关闭，⌃⌥N 下一条相关的）", seconds: 2.2)
        browseLog.append(["event": "target_on", "goal": goal])
        emptyRetries = 0
        schedule(after: 0.05)
    }

    func disable(message: String?) {
        guard on else { return }
        state.targetModeOn = false
        state.targetStatus = ""
        monitors.forEach { NSEvent.removeMonitor($0) }
        monitors = []
        pending?.cancel()
        token += 1
        cards = []
        judgements = [:]
        overlay.cards = []
        overlay.refresh()
        if let m = message { overlay.toast(m, seconds: 1.2) }
        browseLog.append(["event": "target_off"])
    }

    /// 目标变了（比如快速搜索换了词）：缓存键里带目标，直接重扫
    func goalChanged() { if on { emptyRetries = 0; schedule(after: 0.05) } }

    private func install() {
        // 全局监听只读事件，不拦截、不改写：滚动时先撤掉标注（位置会错），停下 0.5 s 后重扫
        if let m = NSEvent.addGlobalMonitorForEvents(matching: [.scrollWheel], handler: { [weak self] _ in self?.scrolled() }) {
            monitors.append(m)
        }
        if let m = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseUp, .keyUp], handler: { [weak self] _ in
            self?.schedule(after: 1.0)   // 点开了别的页面、或用键盘翻了页
        }) { monitors.append(m) }
    }

    private func scrolled() {
        if !overlay.cards.isEmpty { overlay.cards = []; overlay.refresh() }
        schedule(after: 0.5)
    }

    func schedule(after s: Double) {
        pending?.cancel()
        let w = DispatchWorkItem { [weak self] in self?.scan() }
        pending = w
        DispatchQueue.main.asyncAfter(deadline: .now() + s, execute: w)
    }

    private func scan() {
        guard on else { return }
        token += 1
        let t = token
        let p = ScreenGeometry.mouseAX()
        let goal = state.userGoal
        queue.async { [weak self] in
            let t0 = CFAbsoluteTimeGetCurrent()
            guard let web = WebRoot.locate(near: p), web.context.bundleId != Bundle.main.bundleIdentifier else {
                DispatchQueue.main.async { self?.show([], context: nil, goal: goal, token: t, info: ["result": "no_web_area"]) }
                return
            }
            let vp = WebRoot.viewport(web)
            let snap = PageSnapshot.take(web.root, clip: vp, maxNodes: 4000, maxSeconds: 1.2)
            let found = CardFinder.find(snap.root, viewport: vp)
            let info: [String: Any] = ["nodes": snap.nodes, "truncated": snap.truncated,
                                       "scan_ms": ((CFAbsoluteTimeGetCurrent() - t0) * 10000).rounded() / 10]
            DispatchQueue.main.async { self?.show(found, context: web.context, goal: goal, token: t, info: info) }
        }
    }

    private func show(_ found: [PageCard], context: ScreenContext?, goal: String, token t: Int, info: [String: Any]) {
        guard on, t == token else { return }
        cards = found
        judgements = [:]
        for c in found { if let j = cache[CardQuestions.cacheKey(goal: goal, card: c)] { judgements[c.id] = j } }
        draw()
        var log = info
        log["event"] = "target_scan"
        log["goal"] = goal
        log["url"] = context?.url ?? ""
        log["cards"] = found.count
        log["cached"] = judgements.count
        if found.isEmpty {
            state.targetStatus = context == nil ? "指针下没有网页" : "这一屏没认出卡片（看了 \(info["nodes"] ?? 0) 个元素）"
            browseLog.append(log)
            // 页面可能还在加载：再试一次
            if emptyRetries < 1 { emptyRetries += 1; schedule(after: 1.5) }
            return
        }
        emptyRetries = 0
        let missing = found.filter { judgements[$0.id] == nil }
        guard !missing.isEmpty, let ctx = context else { finish(log); return }
        guard let key = state.apiKey else {
            apply(CardQuestions.mock(goal: goal, cards: missing), missing, goal: goal)
            log["source"] = "mock"
            finish(log)
            return
        }
        let body = CardQuestions.requestBody(goal: goal, context: ctx, cards: missing)
        let t0 = CFAbsoluteTimeGetCurrent()
        JevClient(key: key).systemOne(body) { [weak self] r in
            let ms = (CFAbsoluteTimeGetCurrent() - t0) * 1000
            DispatchQueue.main.async {
                guard let self else { return }
                var l = log
                l["jev_ms"] = (ms * 10).rounded() / 10
                l["asked"] = missing.count
                switch r {
                case .success(let d):
                    if let j = try? CardQuestions.parse(d, count: missing.count) {
                        l["source"] = "jev"
                        l["input_tokens"] = ((try? JSONSerialization.jsonObject(with: d)) as? [String: Any])
                            .flatMap { ($0["usage"] as? [String: Any])?["input_tokens"] } ?? NSNull()
                        self.apply(j, missing, goal: goal)
                    } else {
                        l["source"] = "mock_after_error"
                        self.apply(CardQuestions.mock(goal: goal, cards: missing), missing, goal: goal)
                    }
                case .failure(let e):
                    l["source"] = "mock_after_error"
                    l["error"] = e.description
                    self.state.lastError = "目标模式：\(e.description)"
                    self.apply(CardQuestions.mock(goal: goal, cards: missing), missing, goal: goal)
                }
                if t == self.token { self.finish(l) } else { browseLog.append(l) }
            }
        }
    }

    private func apply(_ j: [Int: CardJudgement], _ list: [PageCard], goal: String) {
        for (i, c) in list.enumerated() {
            guard let x = j[i] else { continue }
            cache[CardQuestions.cacheKey(goal: goal, card: c)] = x
            judgements[c.id] = x
        }
        if cache.count > 600 { cache.removeAll() }
    }

    private func finish(_ log: [String: Any]) {
        draw()
        var l = log
        l["results"] = cards.map { c -> [String: Any] in
            let j = judgements[c.id]
            return ["title": c.title, "score": j?.score ?? NSNull(), "ad": j?.ad ?? NSNull()]
        }
        browseLog.append(l)
    }

    private func draw() {
        overlay.cards = cards.map { c in
            guard let j = judgements[c.id] else { return .init(rect: c.frame, style: .pending, text: "") }
            let style: OverlayController.CardMark.Style = j.isAd || j.score < 0.75 ? .dim : j.score >= 2.5 ? .exact : j.score >= 1.5 ? .relevant : .loose
            return .init(rect: c.frame, style: style, text: String(format: "%@ %.1f", j.label, j.score))
        }
        overlay.refresh()
        let rel = judgements.values.filter(\.relevant).count
        let ads = judgements.values.filter(\.isAd).count
        let waiting = cards.count - judgements.count
        state.targetStatus = "\(cards.count) 张卡片：相关 \(rel)，推广 \(ads)" + (waiting > 0 ? "，等 Jev \(waiting)" : "")
    }

    /// ⌃⌥N：跳到指针下方的下一张相关卡片，把指针放上去（直接按 L 就能打开）；这一屏没有就往下翻一屏
    func next() {
        guard on else { overlay.toast("先按 ⌃⌥G 打开目标模式", seconds: 1.5); return }
        let p = ScreenGeometry.mouseAX()
        guard let c = CardQuestions.next(after: p, cards: cards, judgements: judgements) else {
            let h = Int32(max(300, (cards.map(\.frame.maxY).max() ?? 800) - (cards.map(\.frame.minY).min() ?? 0)) * 0.8)
            CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 1, wheel1: -h, wheel2: 0, wheel3: 0)?.post(tap: .cghidEventTap)
            overlay.toast("这一屏下面没有相关的了，往下翻一屏", seconds: 1.4)
            browseLog.append(["event": "next_card", "result": "scrolled", "px": h])
            schedule(after: 0.7)
            return
        }
        if let el = c.el, !visibleScreensAX().contains(c.frame) { AXUIElementPerformAction(el, "AXScrollToVisible" as CFString) }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { [weak self] in
            guard let self else { return }
            let f = c.el.flatMap { AX.frame($0) } ?? c.frame
            let center = CGPoint(x: f.midX, y: f.midY)
            CGWarpMouseCursorPosition(center)
            CGAssociateMouseAndMouseCursorPosition(1)
            CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: center, mouseButton: .left)?.post(tap: .cghidEventTap)
            let j = self.judgements[c.id]
            self.overlay.flash(f, text: "下一条相关：\(c.title)", seconds: 1.4)
            self.state.lastQuickAction = "下一条相关 · \(c.title) · \(j.map { String(format: "%.1f", $0.score) } ?? "")"
            browseLog.append(["event": "next_card", "result": "moved", "title": c.title, "score": j?.score ?? NSNull()])
        }
    }
}

// MARK: - B7 关闭弹窗

/// ⌃⌥X：在指针所在网页里找弹窗和它的关闭按钮（关闭、×、暂不登录、以后再说），
/// 多个候选时问 Jev（J9），按下后回读弹窗还在不在。找到弹窗却认不出按钮时发一次 Esc。
final class PopupCloser {
    private let state: AppState
    private let overlay: OverlayController
    private let queue = DispatchQueue(label: "aikey.inspire.popup")
    private var busy = false

    init(state: AppState, overlay: OverlayController) {
        self.state = state
        self.overlay = overlay
    }

    private struct Found {
        var web: WebRoot.Found
        var scan: PopupScan
        var viewport: CGRect
        var ms: Double
    }

    private func look(near p: CGPoint) -> Found? {
        let t0 = CFAbsoluteTimeGetCurrent()
        guard let web = WebRoot.locate(near: p), web.context.bundleId != Bundle.main.bundleIdentifier else { return nil }
        let vp = WebRoot.viewport(web)
        let snap = PageSnapshot.take(web.root, clip: vp, maxNodes: 5000, maxSeconds: 1.2)
        return Found(web: web, scan: PopupFinder.find(snap.root, viewport: vp), viewport: vp, ms: (CFAbsoluteTimeGetCurrent() - t0) * 1000)
    }

    func run() {
        guard !busy else { return }
        busy = true
        let p = ScreenGeometry.mouseAX()
        overlay.toast("找弹窗的关闭按钮…", seconds: 2)
        queue.async { [weak self] in
            let f = self?.look(near: p)
            DispatchQueue.main.async { self?.choose(f) }
        }
    }

    private func choose(_ f: Found?) {
        guard let f else {
            busy = false
            overlay.toast("指针下没有网页", seconds: 1.4)
            browseLog.append(["event": "close_popup", "result": "no_web_area"])
            return
        }
        var log: [String: Any] = ["event": "close_popup", "url": f.web.context.url ?? "", "dialogs": f.scan.dialogs.count,
                                  "dialog_text": f.scan.dialogText, "scan_ms": (f.ms * 10).rounded() / 10,
                                  "candidates": f.scan.candidates.map { ["id": $0.id, "label": $0.label, "kind": $0.kind.rawValue,
                                                                         "classes": $0.classes, "in_dialog": $0.inDialog] }]
        if f.scan.candidates.isEmpty {
            busy = false
            if f.scan.dialogs.isEmpty {
                overlay.toast("没看到弹窗", seconds: 1.4)
                log["result"] = "no_popup"
            } else {
                escape(f)
                overlay.toast("找到弹窗，但没认出关闭按钮：发了一次 Esc", seconds: 1.8)
                log["result"] = "escape"
            }
            browseLog.append(log)
            return
        }
        if f.scan.candidates.count == 1 {
            log["source"] = "only_one"
            press(f, choice: f.scan.candidates[0].id, log: log)
            return
        }
        guard let key = state.apiKey else {
            log["source"] = "mock"
            press(f, choice: CloseQuestions.mock(f.scan), log: log)
            return
        }
        let t0 = CFAbsoluteTimeGetCurrent()
        JevClient(key: key).systemOne(CloseQuestions.requestBody(f.scan, context: f.web.context)) { [weak self] r in
            let ms = (CFAbsoluteTimeGetCurrent() - t0) * 1000
            DispatchQueue.main.async {
                var l = log
                l["jev_ms"] = (ms * 10).rounded() / 10
                var choice = CloseQuestions.mock(f.scan)
                switch r {
                case .success(let d):
                    if let a = try? CloseQuestions.parse(d) { choice = a.choice; l["source"] = "jev"; l["confidence"] = a.confidence ?? NSNull() }
                    else { l["source"] = "mock_after_error" }
                case .failure(let e):
                    l["source"] = "mock_after_error"; l["error"] = e.description
                }
                self?.press(f, choice: choice, log: l)
            }
        }
    }

    private func escape(_ f: Found) {
        if let pid = AX.pid(f.web.root), let app = NSRunningApplication(processIdentifier: pid), !app.isActive { app.activate() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { InputPoster.key(0x35) }
    }

    private func press(_ f: Found, choice: String, log: [String: Any]) {
        var l = log
        l["choice"] = choice
        guard let c = f.scan.candidates.first(where: { $0.id == choice }), let el = f.scan.elements[choice] else {
            busy = false
            if !f.scan.dialogs.isEmpty { escape(f); l["result"] = "none_chosen_escape" } else { l["result"] = "none_chosen" }
            browseLog.append(l)
            overlay.toast("没认出关闭按钮" + (f.scan.dialogs.isEmpty ? "" : "：发了一次 Esc"), seconds: 1.6)
            return
        }
        overlay.flash(c.frame, text: "关闭：“\(c.label.isEmpty ? "右上角按钮" : c.label)”", seconds: 1.2)
        l["method"] = InputPoster.press(el, frame: c.frame)
        let before = f.scan.dialogs.count
        let p = CGPoint(x: f.viewport.midX, y: f.viewport.midY)
        // 浏览器更新辅助功能信息有延迟：0.6 s 后回读一次
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { [weak self] in
            self?.queue.async {
                let after = self?.look(near: p)
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.busy = false
                    let stillThere = after.map { a in a.scan.candidates.contains { $0.label == c.label && $0.frame == c.frame } } ?? false
                    let closed = !stillThere && (after?.scan.dialogs.count ?? 0) < max(before, 1)
                    l["result"] = closed ? "closed" : stillThere ? "still_there" : "button_gone"
                    browseLog.append(l)
                    self.overlay.toast(closed || !stillThere ? "已关闭弹窗" : "按了“\(c.label)”，弹窗好像还在", seconds: 1.6)
                    self.state.lastQuickAction = "关闭弹窗 · \(c.label.isEmpty ? c.kind.rawValue : c.label) · \(l["result"] ?? "")"
                }
            }
        }
    }
}
