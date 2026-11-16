import AppKit
import InspireCore

/// 全屏透明浮层：画预判高亮、全部候选、圈选轨迹和提示条。不接收鼠标，也不进截图（sharingType = .none）。
final class OverlayController {
    struct Box {
        var rect: CGRect      // AX 坐标
        var text: String
        var strong: Bool
    }

    var highlight: Box?
    var others: [Box] = []
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
