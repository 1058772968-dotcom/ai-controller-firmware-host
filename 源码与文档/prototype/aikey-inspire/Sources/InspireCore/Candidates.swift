import ApplicationServices
import AppKit

/// 指针附近一个可点击的界面元素（只含能发给模型和写日志的信息）
public struct CandidateInfo: Codable, Equatable {
    public var id: String
    public var role: String
    public var kind: String
    public var label: String
    public var x: Double
    public var y: Double
    public var w: Double
    public var h: Double
    /// 指针到元素边框的距离（点）；0 表示指针就在元素上
    public var distance: Double
    public var direction: String

    public var frame: CGRect { CGRect(x: x, y: y, width: w, height: h) }
    public var center: CGPoint { CGPoint(x: x + w / 2, y: y + h / 2) }

    public init(id: String, role: String, kind: String, label: String, frame: CGRect, distance: Double, direction: String) {
        self.id = id; self.role = role; self.kind = kind; self.label = label
        x = Double(frame.minX); y = Double(frame.minY); w = Double(frame.width); h = Double(frame.height)
        self.distance = distance; self.direction = direction
    }
}

/// 指针所在的软件、窗口、网页
public struct ScreenContext: Codable, Equatable {
    public var appName: String?
    public var bundleId: String?
    public var windowTitle: String?
    public var url: String?
    public init(appName: String? = nil, bundleId: String? = nil, windowTitle: String? = nil, url: String? = nil) {
        self.appName = appName; self.bundleId = bundleId; self.windowTitle = windowTitle; self.url = url
    }
    public var summary: String {
        [appName, windowTitle, url].compactMap { $0 }.joined(separator: " · ")
    }
}

public enum Geometry {
    public static func distance(_ p: CGPoint, _ r: CGRect) -> Double {
        let dx = max(r.minX - p.x, 0, p.x - r.maxX)
        let dy = max(r.minY - p.y, 0, p.y - r.maxY)
        return Double((dx * dx + dy * dy).squareRoot())
    }

    /// 八方向（AX 坐标 y 向下，所以 dy>0 是“下”）
    public static func direction(dx: Double, dy: Double) -> String {
        if abs(dx) < 0.5 && abs(dy) < 0.5 { return "here" }
        let a = atan2(-dy, dx) * 180 / .pi   // 转成数学角度：右 0°，上 90°
        let names = ["right", "upper-right", "up", "upper-left", "left", "lower-left", "down", "lower-right"]
        let i = Int(((a + 360 + 22.5).truncatingRemainder(dividingBy: 360)) / 45)
        return names[i]
    }

    public static func direction(from p: CGPoint, to r: CGRect) -> String {
        if r.contains(p) { return "under_pointer" }
        return direction(dx: Double(r.midX - p.x), dy: Double(r.midY - p.y))
    }
}

/// 在指针周围按环形采样做命中测试，向上找到最近的可点击祖先。
/// 只读，不做任何动作；每个采样点一次 AX 调用，目标软件无响应时 0.25 s 超时。
public final class AXProbe {
    public struct Scan {
        public var context: ScreenContext
        public var candidates: [CandidateInfo]
        public var elements: [String: AXUIElement]
        public var elapsedMs: Double
        public var samples: Int
    }

    private let system = AXUIElementCreateSystemWide()

    static let clickableRoles: Set<String> = [
        "AXButton", "AXLink", "AXMenuItem", "AXMenuBarItem", "AXCheckBox", "AXRadioButton",
        "AXPopUpButton", "AXMenuButton", "AXTab", "AXComboBox", "AXTextField", "AXTextArea",
        "AXDisclosureTriangle", "AXDockItem", "AXIncrementor", "AXColorWell",
    ]
    /// 只有带 AXPress 动作且尺寸合理才算可点击的角色（网页里很多可点的 div 是这种）
    static let pressOnlyRoles: Set<String> = ["AXGroup", "AXImage", "AXStaticText", "AXCell", "AXRow", "AXGenericElement"]
    /// 向上找时遇到这些就停：再往上是容器，不是“一个要点的东西”
    static let stopRoles: Set<String> = [
        "AXWindow", "AXApplication", "AXWebArea", "AXScrollArea", "AXSplitGroup", "AXSheet",
        "AXDrawer", "AXBrowser", "AXOutline", "AXTable", "AXList", "AXToolbar", "AXSystemWide",
    ]

    public init(timeout: Float = 0.25) {
        AXUIElementSetMessagingTimeout(system, timeout)
    }

    public static func kind(for role: String, subrole: String?) -> String {
        if subrole == "AXSearchField" { return "search field" }
        if subrole == "AXTabButton" { return "tab" }
        switch role {
        case "AXButton": return "button"
        case "AXLink": return "link"
        case "AXMenuItem": return "menu item"
        case "AXMenuBarItem": return "menu bar item"
        case "AXCheckBox": return "checkbox"
        case "AXRadioButton": return "radio button or tab"
        case "AXPopUpButton", "AXMenuButton": return "pop-up menu"
        case "AXTab": return "tab"
        case "AXComboBox": return "combo box"
        case "AXTextField": return "text field"
        case "AXTextArea": return "text area"
        case "AXDisclosureTriangle": return "disclosure triangle"
        case "AXDockItem": return "dock item"
        case "AXImage": return "clickable image"
        case "AXCell", "AXRow": return "list item"
        case "AXStaticText": return "clickable text"
        default: return "clickable area"
        }
    }

    static func isClickable(_ el: AXUIElement, role: String) -> Bool {
        if clickableRoles.contains(role) { return true }
        if pressOnlyRoles.contains(role), AX.actions(el).contains("AXPress") {
            if let f = AX.frame(el) { return f.width <= 700 && f.height <= 420 && f.width >= 4 && f.height >= 4 }
        }
        return false
    }

    /// 元素给人看的名字：标题 > 描述 > 值 > 子孙里的文字 > 帮助 > 角色描述
    public static func label(of el: AXUIElement, role: String) -> String {
        for a in ["AXTitle", "AXDescription"] {
            if let s = AX.string(el, a) { return clip(s) }
        }
        if let v = AX.string(el, "AXValue"), v.count <= 160 { return clip(v) }
        var texts: [String] = []
        var budget = 40
        collectText(el, depth: 0, into: &texts, budget: &budget)
        if !texts.isEmpty { return clip(texts.joined(separator: " ")) }
        if let t = AX.element(el, "AXTitleUIElement"), let s = AX.string(t, "AXValue") { return clip(s) }
        if let h = AX.string(el, "AXHelp") { return clip(h) }
        return AX.string(el, "AXRoleDescription") ?? role
    }

    static func collectText(_ el: AXUIElement, depth: Int, into out: inout [String], budget: inout Int) {
        guard depth < 4, out.count < 4, budget > 0 else { return }
        for c in AX.children(el) {
            budget -= 1
            if budget <= 0 || out.count >= 4 { return }
            let r = AX.role(c)
            if r == "AXStaticText" || r == "AXHeading" {
                if let s = AX.string(c, "AXValue") ?? AX.string(c, "AXTitle") ?? AX.string(c, "AXDescription") { out.append(s) }
            } else if r == "AXImage", let s = AX.string(c, "AXDescription") {
                out.append(s)
            } else {
                collectText(c, depth: depth + 1, into: &out, budget: &budget)
            }
        }
    }

    static func clip(_ s: String, _ n: Int = 80) -> String {
        let one = s.replacingOccurrences(of: "\n", with: " ")
        return one.count > n ? String(one.prefix(n)) + "…" : one
    }

    /// 采样点：中心 + 4 圈
    public static func samplePoints(around p: CGPoint, radius: Double) -> [CGPoint] {
        var pts = [p]
        for (frac, n) in [(0.18, 8), (0.45, 12), (0.75, 12), (1.0, 16)] {
            let r = radius * frac
            for i in 0..<n {
                let a = Double(i) / Double(n) * 2 * .pi
                pts.append(CGPoint(x: p.x + CGFloat(r * cos(a)), y: p.y + CGFloat(r * sin(a))))
            }
        }
        return pts
    }

    /// 从命中元素往上找可点击的祖先
    func clickableAncestor(of hit: AXUIElement) -> (AXUIElement, String)? {
        var cur: AXUIElement? = hit
        var steps = 0
        while let el = cur, steps < 8 {
            let r = AX.role(el)
            if AXProbe.stopRoles.contains(r) { return nil }
            if AXProbe.isClickable(el, role: r) { return (el, r) }
            cur = AX.element(el, "AXParent")
            steps += 1
        }
        return nil
    }

    /// 指针所在的软件、窗口标题和网页地址
    public func context(at p: CGPoint) -> ScreenContext {
        var ctx = ScreenContext()
        guard let hit = AX.hitPatient(system, p) else { return ctx }
        if let pid = AX.pid(hit), let app = NSRunningApplication(processIdentifier: pid) {
            ctx.appName = app.localizedName
            ctx.bundleId = app.bundleIdentifier
        }
        var cur: AXUIElement? = hit
        var steps = 0
        while let el = cur, steps < 60 {
            let r = AX.role(el)
            if r == "AXWebArea", ctx.url == nil { ctx.url = AX.url(el) }
            if r == "AXWindow" { ctx.windowTitle = AX.string(el, "AXTitle"); break }
            cur = AX.element(el, "AXParent")
            steps += 1
        }
        if ctx.windowTitle == nil, let pid = AX.pid(hit) {
            let appEl = AXUIElementCreateApplication(pid)
            if let w = AX.element(appEl, "AXFocusedWindow") { ctx.windowTitle = AX.string(w, "AXTitle") }
        }
        return ctx
    }

    /// 枚举指针附近的可点击元素，按距离排序，最多 maxCount 个，编号 c1…cN
    public func scan(at p: CGPoint, radius: Double = 150, maxCount: Int = 20) -> Scan {
        let t0 = CFAbsoluteTimeGetCurrent()
        let ctx = context(at: p)
        var seen = Set<AXKey>()
        var found: [(AXUIElement, String, CGRect)] = []
        let pts = AXProbe.samplePoints(around: p, radius: radius)
        for q in pts {
            guard let hit = AX.hit(system, q), let (el, role) = clickableAncestor(of: hit) else { continue }
            let key = AXKey(el: el)
            if seen.contains(key) { continue }
            // 命中点必须落在这个祖先的边框里：有些软件的 AX 树里，祖先边框和实际绘制位置对不上
            guard let f = AX.frame(el), f.width > 0, f.height > 0, Geometry.distance(q, f) <= 6 else { continue }
            seen.insert(key)
            found.append((el, role, f))
        }
        let sorted = found
            .map { (el: $0.0, role: $0.1, frame: $0.2, d: Geometry.distance(p, $0.2)) }
            .sorted { $0.d < $1.d }
            .prefix(maxCount)
        var infos: [CandidateInfo] = []
        var elements: [String: AXUIElement] = [:]
        for (i, c) in sorted.enumerated() {
            let id = "c\(i + 1)"
            let sub = AX.string(c.el, "AXSubrole")
            infos.append(CandidateInfo(id: id, role: c.role, kind: AXProbe.kind(for: c.role, subrole: sub),
                                       label: AXProbe.label(of: c.el, role: c.role), frame: c.frame,
                                       distance: (c.d * 10).rounded() / 10,
                                       direction: Geometry.direction(from: p, to: c.frame)))
            elements[id] = c.el
        }
        return Scan(context: ctx, candidates: infos, elements: elements,
                    elapsedMs: (CFAbsoluteTimeGetCurrent() - t0) * 1000, samples: pts.count)
    }

    /// 圈选区域里看得到的文字（给灵感条目和 Jev 分类当上下文）
    public func texts(in rect: CGRect, maxItems: Int = 12) -> [String] {
        var out: [String] = []
        var seen = Set<AXKey>()
        let n = 4
        for i in 0..<n {
            for j in 0..<n {
                let q = CGPoint(x: rect.minX + rect.width * (CGFloat(i) + 0.5) / CGFloat(n),
                                y: rect.minY + rect.height * (CGFloat(j) + 0.5) / CGFloat(n))
                guard var el = AX.hit(system, q) else { continue }
                if AX.pid(el) == getpid() { continue }   // 本 App 自己的窗口不算圈内内容
                for _ in 0..<3 {
                    let key = AXKey(el: el)
                    if !seen.contains(key) {
                        seen.insert(key)
                        let r = AX.role(el)
                        if AXProbe.stopRoles.contains(r) { break }
                        let s = AXProbe.label(of: el, role: r)
                        if s != r, !out.contains(s), s.count > 1 { out.append(s) }
                    }
                    guard let parent = AX.element(el, "AXParent") else { break }
                    el = parent
                }
                if out.count >= maxItems { return out }
            }
        }
        return out
    }
}
