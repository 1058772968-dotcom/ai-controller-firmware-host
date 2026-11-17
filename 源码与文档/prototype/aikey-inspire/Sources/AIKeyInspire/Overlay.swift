import AppKit
import InspireCore

/// 全屏透明浮层：画预判高亮、全部候选、圈选轨迹和提示条。不接收鼠标，也不进截图（sharingType = .none）。
final class OverlayController {
    struct Box {
        var rect: CGRect      // AX 坐标
        var text: String
        var strong: Bool
    }

    /// B2 目标模式给卡片的标注：相关的绿框，无关 / 推广的压暗，还在等 Jev 的虚线
    struct CardMark {
        enum Style { case pending, exact, relevant, loose, dim }
        var rect: CGRect
        var style: Style
        var text: String
    }

    var highlight: Box?
    var others: [Box] = []
    var cards: [CardMark] = []
    var circlePath: [CGPoint] = []
    var hint: String?

    private var windows: [NSWindow] = []

    init() {
        rebuild()
        NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification,
                                               object: nil, queue: .main) { [weak self] _ in self?.rebuild() }
    }

    func rebuild() {
        windows.forEach { $0.orderOut(nil) }
        windows = NSScreen.screens.map { screen in
            let w = NSWindow(contentRect: screen.frame, styleMask: .borderless, backing: .buffered, defer: false)
            w.setFrame(screen.frame, display: false)
            w.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.overlayWindow)))
            w.ignoresMouseEvents = true
            w.isOpaque = false
            w.backgroundColor = .clear
            w.hasShadow = false
            w.sharingType = .none
            w.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
            let v = OverlayView(frame: NSRect(origin: .zero, size: screen.frame.size))
            v.controller = self
            v.screenFrame = screen.frame
            w.contentView = v
            w.orderFrontRegardless()
            return w
        }
    }

    func refresh() { windows.forEach { $0.contentView?.needsDisplay = true } }

    private var toastToken = 0
    /// 屏幕上方短暂显示一句结果
    func toast(_ text: String, seconds: Double = 1.8) {
        toastToken += 1
        let token = toastToken
        hint = text
        refresh()
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { [weak self] in
            guard let self, self.toastToken == token else { return }
            self.hint = nil
            self.refresh()
        }
    }

    /// 短暂框出一个元素（看清楚 App 找到的是哪个按钮）
    func flash(_ rect: CGRect, text: String, seconds: Double = 1.5) {
        highlight = .init(rect: rect, text: text, strong: true)
        refresh()
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { [weak self] in
            guard let self, self.highlight?.rect == rect else { return }
            self.highlight = nil
            self.refresh()
        }
    }

    func clearPrediction() {
        guard highlight != nil || !others.isEmpty else { return }
        highlight = nil
        others = []
        refresh()
    }
}

final class OverlayView: NSView {
    weak var controller: OverlayController?
    var screenFrame: NSRect = .zero

    private func toView(_ r: CGRect) -> NSRect {
        let c = ScreenGeometry.axToCocoa(r)
        return NSRect(x: c.minX - screenFrame.minX, y: c.minY - screenFrame.minY, width: c.width, height: c.height)
    }

    private func toView(_ p: CGPoint) -> NSPoint {
        let c = ScreenGeometry.axToCocoa(p)
        return NSPoint(x: c.x - screenFrame.minX, y: c.y - screenFrame.minY)
    }

    private func pill(_ text: String, at p: NSPoint, color: NSColor, font: NSFont) {
        let attrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: NSColor.white]
        let s = NSAttributedString(string: text, attributes: attrs)
        let size = s.size()
        var r = NSRect(x: p.x, y: p.y, width: size.width + 14, height: size.height + 6)
        r.origin.x = min(max(r.origin.x, 4), bounds.width - r.width - 4)
        r.origin.y = min(max(r.origin.y, 4), bounds.height - r.height - 4)
        color.setFill()
        NSBezierPath(roundedRect: r, xRadius: r.height / 2, yRadius: r.height / 2).fill()
        s.draw(at: NSPoint(x: r.minX + 7, y: r.minY + 3))
    }

    override func draw(_ dirtyRect: NSRect) {
        guard let c = controller else { return }
        NSColor.clear.setFill()
        dirtyRect.fill(using: .copy)

        for m in c.cards {
            let r = toView(m.rect)
            guard r.intersects(bounds) else { continue }
            let p = NSBezierPath(roundedRect: r.insetBy(dx: 1, dy: 1), xRadius: 8, yRadius: 8)
            switch m.style {
            case .dim:
                NSColor.black.withAlphaComponent(0.42).setFill()
                p.fill()
                pill(m.text, at: NSPoint(x: r.minX + 6, y: r.maxY - 24), color: NSColor.darkGray.withAlphaComponent(0.85), font: .systemFont(ofSize: 11))
            case .loose:
                NSColor.black.withAlphaComponent(0.18).setFill()
                p.fill()
            case .relevant, .exact:
                let green = NSColor.systemGreen
                green.withAlphaComponent(m.style == .exact ? 0.16 : 0.07).setFill()
                p.fill()
                green.setStroke()
                p.lineWidth = m.style == .exact ? 4 : 2.5
                p.stroke()
                pill(m.text, at: NSPoint(x: r.minX + 6, y: r.maxY - 24), color: green.withAlphaComponent(0.92), font: .boldSystemFont(ofSize: 11))
            case .pending:
                NSColor.systemGray.withAlphaComponent(0.7).setStroke()
                p.lineWidth = 1.5
                p.setLineDash([5, 4], count: 2, phase: 0)
                p.stroke()
            }
        }

        for o in c.others {
            let r = toView(o.rect)
            guard r.intersects(bounds) else { continue }
            NSColor.systemBlue.withAlphaComponent(0.55).setStroke()
            let p = NSBezierPath(roundedRect: r, xRadius: 4, yRadius: 4)
            p.lineWidth = 1
            p.stroke()
            pill(o.text, at: NSPoint(x: r.minX, y: r.minY - 16), color: NSColor.systemBlue.withAlphaComponent(0.7),
                 font: .systemFont(ofSize: 10))
        }

        if let h = c.highlight {
            let r = toView(h.rect).insetBy(dx: -3, dy: -3)
            if r.intersects(bounds) {
                let color: NSColor = h.strong ? .systemGreen : .systemOrange
                color.withAlphaComponent(0.14).setFill()
                let p = NSBezierPath(roundedRect: r, xRadius: 6, yRadius: 6)
                p.fill()
                color.setStroke()
                p.lineWidth = 3
                p.stroke()
                pill(h.text, at: NSPoint(x: r.minX, y: r.maxY + 4), color: color.withAlphaComponent(0.9), font: .boldSystemFont(ofSize: 12))
            }
        }

        if c.circlePath.count > 1 {
            let path = NSBezierPath()
            path.move(to: toView(c.circlePath[0]))
            for q in c.circlePath.dropFirst() { path.line(to: toView(q)) }
            NSColor.systemYellow.setStroke()
            path.lineWidth = 4
            path.lineCapStyle = .round
            path.lineJoinStyle = .round
            path.stroke()
        }

        if let hint = c.hint {
            let mouse = NSEvent.mouseLocation
            if screenFrame.contains(mouse) {
                let font = NSFont.boldSystemFont(ofSize: 15)
                let w = NSAttributedString(string: hint, attributes: [.font: font]).size().width + 14
                pill(hint, at: NSPoint(x: (bounds.width - w) / 2, y: bounds.height - 80), color: NSColor.black.withAlphaComponent(0.75), font: font)
            }
        }
    }
}
