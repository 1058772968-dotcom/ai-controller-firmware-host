import AppKit
import InspireCore

/// 点击预判：停留触发 → 后台枚举候选 → Jev（或模拟）→ 浮层高亮 + 调试面板 + JSONL 日志
final class ClickPredictor {
    private let state: AppState
    private let overlay: OverlayController
    private let probe = AXProbe()
    private let scanQueue = DispatchQueue(label: "aikey.inspire.scan")
    private let log = JSONLLog(name: "predictions")
    private var dwell = DwellDetector()
    private var inFlight = false
    private var lastSig = ""
    private var lastPoint: CGPoint?
    private var lastRequestAt = 0.0
    private var lastElements: [String: AXUIElement] = [:]
    private var lastCandidates: [CandidateInfo] = []
    private var lastAnswer: ClickAnswer?
    private var seq = 0
    var paused = false

    /// 两次自动请求的最小间隔（秒）
    let minInterval = 0.8
    /// 指针离开预判点超过这么远就撤掉高亮（点）
    let clearDistance: CGFloat = 70

    init(state: AppState, overlay: OverlayController) {
        self.state = state
        self.overlay = overlay
    }

    func tick(_ p: CGPoint, t: Double) {
        if let lp = lastPoint, hypot(p.x - lp.x, p.y - lp.y) > clearDistance, overlay.highlight != nil,
           !(overlay.highlight.map { Geometry.distance(p, $0.rect) <= Double(clearDistance) } ?? false) {
            overlay.clearPrediction()
        }
        let fired = dwell.feed(p, at: t)
        guard fired, state.predictionEnabled, state.axTrusted, !paused else { return }
        trigger(at: p, motion: dwell.motion(), manual: false)
    }

    /// 快捷键 ⌃⌥P：不等停留，立刻预判一次
    func triggerNow() {
        let p = ScreenGeometry.mouseAX()
        trigger(at: p, motion: dwell.motion(), manual: true)
    }

    private func trigger(at p: CGPoint, motion: PointerMotion, manual: Bool) {
        guard !inFlight else { return }
        let now = CFAbsoluteTimeGetCurrent()
        if !manual && now - lastRequestAt < minInterval { return }
        inFlight = true
        let goal = state.userGoal
        scanQueue.async { [weak self] in
            guard let self else { return }
            let scan = self.probe.scan(at: p)
            DispatchQueue.main.async { self.handle(scan, at: p, motion: motion, goal: goal, manual: manual) }
        }
    }

    private func handle(_ scan: AXProbe.Scan, at p: CGPoint, motion: PointerMotion, goal: String, manual: Bool) {
        if scan.context.bundleId == Bundle.main.bundleIdentifier {
            inFlight = false   // 指着灵感圈自己的窗口：不预判
            return
        }
        let sig = ClickQuestions.signature(scan.candidates)
        if !manual, sig == lastSig, let lp = lastPoint, hypot(p.x - lp.x, p.y - lp.y) < 12 {
            inFlight = false   // 同一处、同一批候选：不重复花请求
            return
        }
        seq += 1
        let id = seq
        lastSig = sig
        lastPoint = p
        lastRequestAt = CFAbsoluteTimeGetCurrent()
        lastElements = scan.elements
        lastCandidates = scan.candidates
        state.scanMs = scan.elapsedMs
        state.contextText = scan.context.summary
        state.motionText = motion.text
        state.lastTime = Date()

        let snap = ClickSnapshot(context: scan.context, pointer: motion, candidates: scan.candidates, userGoal: goal)
        let body = ClickQuestions.requestBody(snap)
        state.requestJSON = Self.pretty(body)

        if scan.candidates.isEmpty {
            inFlight = false
            lastAnswer = nil
            overlay.clearPrediction()
            state.rows = []
            state.predicted = nil
            state.source = "无候选"
            state.jevMs = nil
            record(id: id, snap: snap, scan: scan, answer: nil, source: "no_candidates", jevMs: nil, error: nil, manual: manual)
            return
        }

        guard let key = state.apiKey else {
            finish(id: id, snap: snap, scan: scan, answer: ClickQuestions.mock(snap), source: "mock", jevMs: nil, error: nil, manual: manual)
            return
        }
        let t0 = CFAbsoluteTimeGetCurrent()
        JevClient(key: key).systemOne(body) { [weak self] result in
            let ms = (CFAbsoluteTimeGetCurrent() - t0) * 1000
            DispatchQueue.main.async {
                guard let self else { return }
                switch result {
                case .success(let data):
                    do {
                        let a = try ClickQuestions.parse(data)
                        self.finish(id: id, snap: snap, scan: scan, answer: a, source: "jev", jevMs: ms, error: nil, manual: manual)
                    } catch {
                        self.finish(id: id, snap: snap, scan: scan, answer: ClickQuestions.mock(snap), source: "mock_after_error",
                                    jevMs: ms, error: "\(error)", manual: manual)
                    }
                case .failure(let e):
                    self.finish(id: id, snap: snap, scan: scan, answer: ClickQuestions.mock(snap), source: "mock_after_error",
                                jevMs: ms, error: e.description, manual: manual)
                }
            }
        }
    }

    private func finish(id: Int, snap: ClickSnapshot, scan: AXProbe.Scan, answer: ClickAnswer, source: String,
                        jevMs: Double?, error: String?, manual: Bool) {
        inFlight = false
        lastAnswer = answer
        state.predictionCount += 1
        state.source = source == "jev" ? "Jev" : (source == "mock" ? "模拟" : "模拟（Jev 出错）")
        state.jevMs = jevMs
        state.lastError = error
        state.predicted = answer.choice
        state.confidence = answer.confidence
        state.aboutToClick = answer.aboutToClick
        state.rows = snap.candidates.map {
            AppState.Row(id: $0.id, kind: $0.kind, label: $0.label, distance: $0.distance, direction: $0.direction,
                         probability: answer.probabilities[$0.id])
        } + [AppState.Row(id: ClickQuestions.noneId, kind: "—", label: "都不是", distance: 0, direction: "—",
                          probability: answer.probabilities[ClickQuestions.noneId])]

        // 结果回来时指针已经走远：不再画（避免高亮跟不上）
        let now = ScreenGeometry.mouseAX()
        let target = snap.candidates.first { $0.id == answer.choice }
        let nearStart = hypot(now.x - CGFloat(snap.pointer.x), now.y - CGFloat(snap.pointer.y)) <= clearDistance
        let nearTarget = target.map { Geometry.distance(now, $0.frame) <= Double(clearDistance) } ?? false
        let stale = !(nearStart || nearTarget)
        let tag = source == "jev" ? "Jev" : "模拟"
        if !stale, let c = snap.candidates.first(where: { $0.id == answer.choice }) {
            let prob = answer.probabilities[c.id] ?? 0
            overlay.highlight = .init(rect: c.frame, text: "\(tag) · \(c.kind) “\(c.label)” \(Int((prob * 100).rounded()))%  ⌃⌥↩ 点它",
                                      strong: (answer.confidence ?? 0) >= 0.5)
        } else {
            overlay.highlight = nil
        }
        overlay.others = state.showAllCandidates && !stale ? snap.candidates.filter { $0.id != answer.choice }.map {
            .init(rect: $0.frame, text: "\($0.id) \(Int(((answer.probabilities[$0.id] ?? 0) * 100).rounded()))%", strong: false)
        } : []
        overlay.refresh()
        record(id: id, snap: snap, scan: scan, answer: answer, source: source, jevMs: jevMs, error: error, manual: manual, stale: stale)
    }

    private func record(id: Int, snap: ClickSnapshot, scan: AXProbe.Scan, answer: ClickAnswer?, source: String,
                        jevMs: Double?, error: String?, manual: Bool, stale: Bool = false) {
        var o: [String: Any] = [
            "event": "prediction",
            "seq": id,
            "trigger": manual ? "hotkey" : "dwell",
            "source": source,
            "scan_ms": (scan.elapsedMs * 10).rounded() / 10,
            "samples": scan.samples,
            "app": snap.context.appName ?? "",
            "bundle_id": snap.context.bundleId ?? "",
            "window_title": snap.context.windowTitle ?? "",
            "url": snap.context.url ?? "",
            "pointer": ["x": snap.pointer.x, "y": snap.pointer.y, "motion": snap.pointer.text, "speed": snap.pointer.speed],
            "user_goal": snap.userGoal ?? "",
            "candidates": snap.candidates.map { ["id": $0.id, "kind": $0.kind, "label": $0.label, "distance": $0.distance,
                                                 "direction": $0.direction, "frame": [$0.x, $0.y, $0.w, $0.h]] },
            "stale_when_returned": stale,
        ]
        if let jevMs { o["jev_ms"] = (jevMs * 10).rounded() / 10 }
        if let error { o["error"] = error }
        if let a = answer {
            o["answer"] = ["choice": a.choice, "confidence": a.confidence.map { $0 as Any } ?? NSNull(), "probabilities": a.probabilities,
                           "about_to_click": a.aboutToClick.map { $0 as Any } ?? NSNull(), "model": a.model ?? "", "input_tokens": a.inputTokens.map { $0 as Any } ?? NSNull()] as [String: Any]
        }
        log.append(o)
    }

    /// ⌃⌥↩：点预测的目标。优先用辅助功能 AXPress，不支持时在元素中心模拟一次点击。
    func clickPredicted() {
        guard let a = lastAnswer, a.choice != ClickQuestions.noneId,
              let el = lastElements[a.choice], let c = lastCandidates.first(where: { $0.id == a.choice }) else {
            NSSound.beep()
            return
        }
        overlay.clearPrediction()
        var how = "AXPress"
        let st = AXUIElementPerformAction(el, "AXPress" as CFString)
        if st != .success {
            how = "mouse_click"
            let pt = c.center
            let src = CGEventSource(stateID: .hidSystemState)
            CGEvent(mouseEventSource: src, mouseType: .mouseMoved, mouseCursorPosition: pt, mouseButton: .left)?.post(tap: .cghidEventTap)
            CGEvent(mouseEventSource: src, mouseType: .leftMouseDown, mouseCursorPosition: pt, mouseButton: .left)?.post(tap: .cghidEventTap)
            CGEvent(mouseEventSource: src, mouseType: .leftMouseUp, mouseCursorPosition: pt, mouseButton: .left)?.post(tap: .cghidEventTap)
        }
        log.append(["event": "click_predicted", "seq": seq, "choice": a.choice, "label": c.label, "kind": c.kind, "how": how,
                    "ax_result": Int(st.rawValue)])
    }

    /// 给“这次猜对了 / 猜错了”打标，供以后算命中率
    func mark(correct: Bool) {
        log.append(["event": "feedback", "seq": seq, "correct": correct, "choice": lastAnswer?.choice ?? ""])
    }

    static func pretty(_ o: Any) -> String {
        guard let d = try? JSONSerialization.data(withJSONObject: o, options: [.prettyPrinted, .sortedKeys]) else { return "" }
        return String(data: d, encoding: .utf8) ?? ""
    }
}
