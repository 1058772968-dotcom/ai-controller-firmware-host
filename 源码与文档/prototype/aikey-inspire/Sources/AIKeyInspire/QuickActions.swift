import AppKit
import SwiftUI
import InspireCore

/// F1–F3 快捷功能的日志：~/Library/Logs/AIKeyInspire/actions.jsonl，每一步走了哪条路、用了多久
let actionLog = JSONLLog(name: "actions")

// MARK: - F1 随处快速搜索

extension AppDelegate {
    /// ⌃⌥S：记下前台应用和当前网址，弹出搜索框（选中的文字会预填进去）
    func openQuickSearch() {
        let prev = NSWorkspace.shared.frontmostApplication
        let isSelf = prev?.bundleIdentifier == Bundle.main.bundleIdentifier
        let pid = isSelf ? nil : prev?.processIdentifier
        let url = pid.flatMap { FrontApp.webURL(pid: $0) } ?? AXProbe().context(at: ScreenGeometry.mouseAX()).url
        let selected = pid.flatMap { FrontApp.selectedText(pid: $0) } ?? ""
        let view = SearchView(initial: selected, currentURL: url, onSubmit: { [weak self] plan in
            self?.closeWindow("search")
            self?.runSearch(plan, previous: isSelf ? nil : prev)
        }, onCancel: { [weak self] in
            self?.closeWindow("search")
            if !isSelf { prev?.activate() }
        })
        closeWindow("search")
        show("search", title: "快速搜索", view, floating: true)
        actionLog.append(["event": "search_open", "front_app": prev?.localizedName ?? "", "current_url": url ?? "",
                          "prefilled": !selected.isEmpty])
    }

    func runSearch(_ plan: SearchPlan, previous: NSRunningApplication?) {
        var o: [String: Any] = ["event": "search_run", "destination": plan.destination.name, "query": plan.query, "reason": plan.reason]
        switch plan.destination {
        case .site:
            guard let url = plan.url else { NSSound.beep(); return }
            o["url"] = url.absoluteString
            // 搜索词顺便成为“当前目标”，点击预判会参考它
            state.userGoal = plan.query
            if let app = previous, let appURL = app.bundleURL, Self.isBrowser(appURL) {
                o["opened_with"] = app.localizedName ?? ""
                NSWorkspace.shared.open([url], withApplicationAt: appURL, configuration: NSWorkspace.OpenConfiguration())
            } else {
                o["opened_with"] = "默认浏览器"
                NSWorkspace.shared.open(url)
            }
            state.lastQuickAction = "搜索 · \(plan.destination.name)：\(plan.query)"
            overlay.toast("在\(plan.destination.name)搜索：\(plan.query)")
            // 功能定义 F1 第 5 步：搜索词成为目标，结果页直接进入目标模式（等页面加载 2.5 s）
            if state.autoTargetAfterSearch {
                DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) { [weak self] in
                    guard let self else { return }
                    if self.targetMode.on { self.targetMode.goalChanged() } else { self.targetMode.enable(ask: false) }
                }
            } else {
                targetMode.goalChanged()
            }
        case .inPage:
            previous?.activate()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in self?.findInPage(plan.query) }
            o["opened_with"] = previous?.localizedName ?? ""
            state.lastQuickAction = "页内查找：\(plan.query)"
        case .library:
            state.query = LibraryQuery()
            state.query.text = plan.query
            showLibrary()
            state.lastQuickAction = "灵感库筛选：\(plan.query)"
        }
        actionLog.append(o)
    }

    /// 能打开网页的应用就算浏览器，在它里面新开标签页搜
    static func isBrowser(_ appURL: URL) -> Bool {
        guard let probe = URL(string: "https://example.com") else { return false }
        return NSWorkspace.shared.urlsForApplications(toOpen: probe).contains { $0.standardizedFileURL == appURL.standardizedFileURL }
    }

    /// 页内查找：⌘F → 粘贴搜索词 → 回车。借用剪贴板，1 秒后恢复原内容
    func findInPage(_ q: String) {
        let pb = NSPasteboard.general
        let saved: [NSPasteboardItem] = (pb.pasteboardItems ?? []).map { item in
            let copy = NSPasteboardItem()
            for t in item.types { if let d = item.data(forType: t) { copy.setData(d, forType: t) } }
            return copy
        }
        pb.clearContents()
        pb.setString(q, forType: .string)
        InputPoster.key(InputPoster.f, flags: .maskCommand)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            InputPoster.key(InputPoster.v, flags: .maskCommand)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) {
                InputPoster.key(InputPoster.returnKey)
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                    pb.clearContents()
                    if !saved.isEmpty { pb.writeObjects(saved) }
                }
            }
        }
        actionLog.append(["event": "find_in_page", "query": q])
    }
}

// MARK: - F2 图片翻页

/// ⌃⌥← / ⌃⌥→：按一下翻一张；按住不放，0.45 s 后开始连续翻，越翻越快，松开就停
final class ImageFlipper {
    private let overlay: OverlayController
    private let state: AppState
    private var timer: Timer?
    private var interval = 0.35
    private var flips = 0
    private var direction: FlipDirection = .next
    private var pressedAt = 0.0

    init(overlay: OverlayController, state: AppState) {
        self.overlay = overlay
        self.state = state
    }

    func begin(_ d: FlipDirection) {
        stop()
        direction = d
        flips = 0
        interval = 0.35
        pressedAt = CFAbsoluteTimeGetCurrent()
        flipOnce()
        let t = Timer(timeInterval: 0.45, repeats: false) { [weak self] _ in self?.repeatFlip() }
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    func end() {
        let held = CFAbsoluteTimeGetCurrent() - pressedAt
        if timer != nil || flips > 1 {
            actionLog.append(["event": "flip_end", "direction": direction.rawValue, "flips": flips, "held_s": (held * 100).rounded() / 100])
        }
        stop()
        if flips > 1 { overlay.toast("连续翻了 \(flips) 张", seconds: 1.0) }
    }

    private func stop() {
        timer?.invalidate()
        timer = nil
    }

    private func repeatFlip() {
        guard flips < 80 else { stop(); return }   // 保险：最多连续翻 80 张
        flipOnce()
        interval = max(0.12, interval * 0.85)
        let t = Timer(timeInterval: interval, repeats: false) { [weak self] _ in self?.repeatFlip() }
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    /// 先找图集里的“上一张 / 下一张”按钮；找不到就给指针下的应用发左右方向键
    private func flipOnce() {
        let p = ScreenGeometry.mouseAX()
        let t0 = CFAbsoluteTimeGetCurrent()
        let found = ImageNav.findButton(direction, near: p)
        let word = direction == .next ? "下一张" : "上一张"
        var method: String
        var label = ""
        if let b = found.button {
            method = "按钮 · " + InputPoster.press(b.element, frame: b.frame)
            label = b.label
            if flips == 0 { overlay.flash(b.frame, text: "\(word)：“\(b.label)”", seconds: 0.8) }
        } else {
            let system = AXUIElementCreateSystemWide()
            if let hit = AX.hit(system, p), let pid = AX.pid(hit), pid != getpid(),
               let app = NSRunningApplication(processIdentifier: pid), !app.isActive {
                app.activate()
            }
            InputPoster.key(direction == .next ? InputPoster.right : InputPoster.left)
            method = "方向键"
            if flips == 0 { overlay.toast("\(word)（方向键）", seconds: 0.8) }
        }
        flips += 1
        let ms = (CFAbsoluteTimeGetCurrent() - t0) * 1000
        state.lastQuickAction = "\(word) · \(method)\(label.isEmpty ? "" : "“\(label)”") · \(Int(ms)) ms"
        if flips <= 2 {   // 连续翻时只记前两次，免得刷屏
            actionLog.append(["event": "flip", "direction": direction.rawValue, "method": method, "button": label,
                              "container": found.container, "nodes": found.nodes, "ms": (ms * 10).rounded() / 10])
        }
    }
}

// MARK: - F3 点赞、收藏、投币、关注

final class QuickInteractor {
    private let overlay: OverlayController
    private let state: AppState
    private let queue = DispatchQueue(label: "aikey.inspire.actions")
    private var busy = false
    private var lastDone: (el: AXUIElement, frame: CGRect, action: QuickAction, at: Double)?
    /// 投币、关注要先确认：交给 AppDelegate 弹确认框
    var confirm: ((String, @escaping () -> Void) -> Void)?

    init(overlay: OverlayController, state: AppState) {
        self.overlay = overlay
        self.state = state
    }

    func run(_ a: QuickAction) {
        guard !busy else { return }
        busy = true
        let p = ScreenGeometry.mouseAX()
        overlay.toast("找“\(a.zh)”按钮…", seconds: 3)
        queue.async { [weak self] in
            let scan = PageScanner.findActionButtons(a, near: p)
            DispatchQueue.main.async { self?.choose(scan, at: p) }
        }
    }

    private func choose(_ scan: ActionScan, at p: CGPoint) {
        var o: [String: Any] = ["event": "action_find", "action": scan.action.rawValue, "root": scan.root, "nodes": scan.nodes,
                                "scan_ms": (scan.elapsedMs * 10).rounded() / 10, "truncated": scan.truncated,
                                "app": scan.context.appName ?? "", "window_title": scan.context.windowTitle ?? "",
                                "url": scan.context.url ?? "",
                                "candidates": scan.candidates.map { ["id": $0.id, "role": $0.role, "label": $0.label, "classes": $0.classes,
                                                                     "distance": $0.distance, "in_comment": $0.inComment,
                                                                     "already_done": $0.alreadyDone.map { $0 as Any } ?? NSNull()] }]
        guard !scan.candidates.isEmpty else {
            busy = false
            o["result"] = "no_candidates"
            actionLog.append(o)
            state.lastQuickAction = "\(scan.action.zh)：没找到按钮（看了 \(scan.nodes) 个元素，\(Int(scan.elapsedMs)) ms）"
            overlay.toast("没找到“\(scan.action.zh)”按钮", seconds: 1.8)
            return
        }
        // 只有一个候选、而且不在评论区：直接用，不问 Jev
        if scan.candidates.count == 1 && !scan.candidates[0].inComment {
            o["source"] = "only_one"
            act(scan, choice: scan.candidates[0].id, log: o)
            return
        }
        guard let key = state.apiKey else {
            o["source"] = "mock"
            act(scan, choice: ActionQuestions.mock(scan.candidates), log: o)
            return
        }
        let body = ActionQuestions.requestBody(scan.action, context: scan.context, pointer: p, candidates: scan.candidates)
        let t0 = CFAbsoluteTimeGetCurrent()
        JevClient(key: key).systemOne(body) { [weak self] r in
            let ms = (CFAbsoluteTimeGetCurrent() - t0) * 1000
            DispatchQueue.main.async {
                guard let self else { return }
                var log = o
                log["jev_ms"] = (ms * 10).rounded() / 10
                switch r {
                case .success(let d):
                    if let a = try? ActionQuestions.parse(d) {
                        log["source"] = "jev"
                        log["probabilities"] = a.probabilities
                        log["confidence"] = a.confidence.map { $0 as Any } ?? NSNull()
                        self.act(scan, choice: a.choice, log: log)
                    } else {
                        log["source"] = "mock_after_error"
                        self.act(scan, choice: ActionQuestions.mock(scan.candidates), log: log)
                    }
                case .failure(let e):
                    log["source"] = "mock_after_error"
                    log["error"] = e.description
                    self.act(scan, choice: ActionQuestions.mock(scan.candidates), log: log)
                }
            }
        }
    }

    private func act(_ scan: ActionScan, choice: String, log: [String: Any]) {
        var o = log
        o["choice"] = choice
        let a = scan.action
        guard let c = scan.candidates.first(where: { $0.id == choice }), let el = scan.elements[choice] else {
            busy = false
            o["result"] = "none_chosen"
            actionLog.append(o)
            state.lastQuickAction = "\(a.zh)：\(scan.candidates.count) 个候选里没有主内容的按钮"
            overlay.toast("没认出主内容的“\(a.zh)”按钮", seconds: 1.8)
            return
        }
        let desc = "\(a.zh)：“\(c.label.isEmpty ? c.classes : c.label)”"
        if c.alreadyDone == true {
            busy = false
            o["result"] = "already_done"
            actionLog.append(o)
            overlay.flash(c.frame, text: "已经\(a.zh)过了，没有再点", seconds: 1.8)
            state.lastQuickAction = "\(desc) · 已经做过，未操作"
            return
        }
        if a.undoable {
            press(el, c, a, log: o)
        } else {
            overlay.flash(c.frame, text: desc, seconds: 6)
            busy = false
            confirm?("将对这条内容执行“\(a.zh)”\n按钮：\(c.label.isEmpty ? c.classes : c.label)\n\(scan.context.windowTitle ?? "")") { [weak self] in
                self?.busy = true
                self?.press(el, c, a, log: o)
            }
            o["result"] = "awaiting_confirm"
            actionLog.append(o)
        }
    }

    private func press(_ el: AXUIElement, _ c: ActionCandidate, _ a: QuickAction, log: [String: Any]) {
        var o = log
        let before = PageScanner.state(of: el, a)
        let method = InputPoster.press(el, frame: c.frame)
        o["method"] = method
        o["state_before"] = before.label
        // 浏览器更新辅助功能信息有延迟（测试页实测 0.5 s 还没变、几秒后变了）：每 0.3 s 回读，最多 2 s
        waitForChange(el, a, from: before.label, started: CFAbsoluteTimeGetCurrent()) { [weak self] after, waited in
            guard let self else { return }
            self.busy = false
            o["readback_wait_ms"] = Int(waited * 1000)
            o["state_after"] = after.label
            o["done_after"] = after.done.map { $0 as Any } ?? NSNull()
            let changed = after.label != before.label
            o["result"] = changed ? "state_changed" : "no_visible_change"
            o["event"] = "action_exec"
            actionLog.append(o)
            if a.undoable { self.lastDone = (el, c.frame, a, CFAbsoluteTimeGetCurrent()) }
            let tail = a.undoable ? " · 5 秒内 ⌃⌥Z 撤销" : ""
            let msg = changed ? "已\(a.zh)（按钮变成“\(after.label)”）\(tail)" : "已点了“\(a.zh)”，但按钮看不出变化\(tail)"
            self.overlay.flash(c.frame, text: msg, seconds: 2.5)
            self.state.lastQuickAction = "\(a.zh) · \(method) · \(changed ? "状态已变" : "状态没变")"
        }
    }

    private func waitForChange(_ el: AXUIElement, _ a: QuickAction, from before: String, started: Double,
                               done: @escaping ((label: String, done: Bool?), Double) -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in
            let now = PageScanner.state(of: el, a)
            let waited = CFAbsoluteTimeGetCurrent() - started
            if now.label != before || waited >= 2.0 { done(now, waited) }
            else { self?.waitForChange(el, a, from: before, started: started, done: done) }
        }
    }

    /// ⌃⌥Z：5 秒内撤销刚才的点赞 / 收藏（再按一次同一个按钮）
    func undo() {
        guard let d = lastDone, CFAbsoluteTimeGetCurrent() - d.at <= 5 else {
            overlay.toast("没有可撤销的操作（只能撤销 5 秒内的点赞、收藏）", seconds: 1.8)
            return
        }
        lastDone = nil
        let method = InputPoster.press(d.el, frame: d.frame)
        overlay.flash(d.frame, text: "已撤销\(d.action.zh)", seconds: 1.5)
        actionLog.append(["event": "action_undo", "action": d.action.rawValue, "method": method])
        state.lastQuickAction = "撤销\(d.action.zh) · \(method)"
    }
}
