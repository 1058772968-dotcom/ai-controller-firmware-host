import AppKit
import InspireCore

/// 圈选：⌃⌥C 开始 → 移动光标画圈 → 再按 ⌃⌥C 完成（Esc 取消）→ 截图 + 来源 → 意图面板
final class CircleController {
    struct Draft {
        var context: ScreenContext
        var texts: [String]
        var rect: CGRect
        var png: Data?
        var captureNote: String?
        var previousApp: NSRunningApplication?
    }

    private let overlay: OverlayController
    private let probe = AXProbe()
    private let queue = DispatchQueue(label: "aikey.inspire.circle")
    private(set) var active = false
    private var path: [CGPoint] = []
    var onDraft: ((Draft) -> Void)?
    /// 截图前调用：隐藏本 App 的窗口，返回恢复它们的闭包
    var hideOwnWindows: (() -> (() -> Void))?
    var onActiveChange: ((Bool) -> Void)?

    init(overlay: OverlayController) { self.overlay = overlay }

    func toggle() { active ? finish() : start() }

    func start() {
        active = true
        path = []
        overlay.clearPrediction()
        overlay.circlePath = []
        overlay.hint = "圈选中：移动光标把喜欢的内容圈起来，再按 ⌃⌥C 完成，Esc 取消"
        overlay.refresh()
        HotKeys.shared.register(.escape, keyCode: 0x35, modifiers: 0) { [weak self] in self?.cancel("已取消圈选") }
        onActiveChange?(true)
    }

    func tick(_ p: CGPoint) {
        guard active else { return }
        if let l = path.last, hypot(p.x - l.x, p.y - l.y) < 2 { return }
        path.append(p)
        overlay.circlePath = path
        overlay.refresh()
    }

    func cancel(_ message: String? = nil) {
        active = false
        HotKeys.shared.unregister(.escape)
        path = []
        overlay.circlePath = []
        overlay.hint = message
        overlay.refresh()
        onActiveChange?(false)
        if message != nil {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
                guard let self, !self.active else { return }
                self.overlay.hint = nil
                self.overlay.refresh()
            }
        }
    }

    func finish() {
        guard active else { return }
        let xs = path.map(\.x), ys = path.map(\.y)
        guard let x0 = xs.min(), let x1 = xs.max(), let y0 = ys.min(), let y1 = ys.max(), x1 - x0 >= 24, y1 - y0 >= 24 else {
            cancel("圈得太小，没有保存")
            return
        }
        let rect = CGRect(x: x0, y: y0, width: x1 - x0, height: y1 - y0).insetBy(dx: -6, dy: -6)
        active = false
        HotKeys.shared.unregister(.escape)
        path = []
        overlay.circlePath = []
        overlay.hint = nil
        overlay.refresh()
        onActiveChange?(false)
        let prev = NSWorkspace.shared.frontmostApplication
        let canCapture = ScreenCapture.trusted
        if !canCapture { ScreenCapture.requestTrust() }   // 系统只会弹一次；之后要到系统设置里手动打开
        let restore = hideOwnWindows?() ?? {}
        // 等浮层从屏幕上消失再截，避免把黄线截进去
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { [weak self] in
            guard let self else { return }
            self.queue.async {
                let center = CGPoint(x: rect.midX, y: rect.midY)
                let ctx = self.probe.context(at: center)
                let texts = AX.trusted ? self.probe.texts(in: rect) : []
                let deliver: (Data?, String?) -> Void = { png, note in
                    DispatchQueue.main.async {
                        restore()
                        self.onDraft?(Draft(context: ctx, texts: texts, rect: rect, png: png, captureNote: note, previousApp: prev))
                    }
                }
                if canCapture {
                    ScreenCapture.png(rectAX: rect) { d, via, err in deliver(d, d == nil ? "截图失败（\(via)）：\(err ?? "")" : nil) }
                } else {
                    deliver(nil, "没有“屏幕录制”权限，这条只保存文字和来源")
                }
            }
        }
    }
}
