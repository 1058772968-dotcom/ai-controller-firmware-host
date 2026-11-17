import ApplicationServices
import AppKit

// MARK: - 一次读多个属性的节点

/// 一个界面元素的常用属性，用 AXUIElementCopyMultipleAttributeValues 一次读完（网页里节点多，逐个读太慢）
public struct AXNode {
    public let el: AXUIElement
    public var role = ""
    public var subrole: String?
    public var title: String?
    public var desc: String?
    public var value: String?
    public var valueNumber: Int?
    public var help: String?
    public var domId: String?
    public var classes: [String] = []
    public var frame: CGRect?
    public var children: [AXUIElement] = []
    public var selected: Bool?

    /// 给人看的文字。浏览器里标题和描述常常是同一句：重复的、被包含的只留一份
    public var text: String {
        var out: [String] = []
        for s in [title, desc, value, help].compactMap({ $0 }) where !out.contains(where: { $0.contains(s) }) {
            out.removeAll { s.contains($0) }
            out.append(s)
        }
        return out.joined(separator: " ")
    }
    /// 网页的 id 和 class（Chrome 系浏览器会通过辅助功能暴露）
    public var classText: String { ([domId].compactMap { $0 } + classes).joined(separator: " ") }

    static let names = ["AXRole", "AXSubrole", "AXTitle", "AXDescription", "AXValue", "AXHelp",
                        "AXDOMIdentifier", "AXDOMClassList", "AXPosition", "AXSize", "AXChildren", "AXSelected"]

    public static func read(_ el: AXUIElement) -> AXNode {
        var n = AXNode(el: el)
        var out: CFArray?
        guard AXUIElementCopyMultipleAttributeValues(el, names as CFArray, AXCopyMultipleAttributeOptions(rawValue: 0), &out) == .success,
              let arr = (out as NSArray?) as? [AnyObject] else { return n }
        func v(_ i: Int) -> AnyObject? {
            guard i < arr.count else { return nil }
            let x = arr[i]
            if CFGetTypeID(x) == AXValueGetTypeID(), AXValueGetType(x as! AXValue) == .axError { return nil }
            return x
        }
        func str(_ i: Int) -> String? {
            guard let s = v(i) as? String else { return nil }
            let t = AX.clean(s)
            return t.isEmpty ? nil : t
        }
        n.role = str(0) ?? ""
        n.subrole = str(1)
        n.title = str(2)
        n.desc = str(3)
        if let s = v(4) as? String {
            let t = AX.clean(s)
            if !t.isEmpty && t.count <= 120 { n.value = t }
        } else if let num = v(4) as? NSNumber {
            n.valueNumber = num.intValue
        }
        n.help = str(5)
        n.domId = str(6)
        n.classes = (v(7) as? [String]) ?? []
        if let p = v(8), let s = v(9), CFGetTypeID(p) == AXValueGetTypeID(), CFGetTypeID(s) == AXValueGetTypeID() {
            var pt = CGPoint.zero, sz = CGSize.zero
            if AXValueGetValue(p as! AXValue, .cgPoint, &pt), AXValueGetValue(s as! AXValue, .cgSize, &sz) {
                n.frame = CGRect(origin: pt, size: sz)
            }
        }
        n.children = (v(10) as? [AXUIElement]) ?? []
        n.selected = v(11) as? Bool
        return n
    }

    static let buttonRoles: Set<String> = ["AXButton", "AXLink", "AXCheckBox", "AXRadioButton", "AXMenuButton", "AXPopUpButton", "AXToggle"]
    static let looseRoles: Set<String> = ["AXGroup", "AXImage", "AXStaticText", "AXGenericElement", "AXUnknown", "AXCell"]

    /// 像一个可以按的小东西
    var buttonish: Bool {
        guard let f = frame, f.width >= 6, f.height >= 6 else { return false }
        if AXNode.buttonRoles.contains(role) { return f.width <= 420 && f.height <= 180 }
        if AXNode.looseRoles.contains(role) { return f.width <= 240 && f.height <= 120 }
        return false
    }
}

/// 所有屏幕合起来的可见范围（AX 坐标）
public func visibleScreensAX() -> CGRect {
    NSScreen.screens.map { ScreenGeometry.axToCocoa($0.frame) }   // 换算是对称的，同一个函数可以反过来用
        .reduce(CGRect.null) { $0.union($1) }
}

// MARK: - F3 快捷互动

public enum QuickAction: String, CaseIterable, Codable {
    case like, collect, coin, follow

    public var zh: String {
        switch self {
        case .like: return "点赞"
        case .collect: return "收藏"
        case .coin: return "投币"
        case .follow: return "关注"
        }
    }

    /// 能撤销、只影响自己：说了就做，几秒内可撤销；其余先预览再确认
    public var undoable: Bool { self == .like || self == .collect }

    var textWords: [String] {
        switch self {
        case .like: return ["点赞", "赞", "喜欢", "like"]
        case .collect: return ["收藏", "书签", "collect", "bookmark", "favorite", "favourite"]
        case .coin: return ["投币", "硬币", "coin"]
        case .follow: return ["关注", "follow"]
        }
    }

    var classWords: [String] {
        switch self {
        case .like: return ["like"]
        case .collect: return ["collect", "fav", "bookmark", "star"]
        case .coin: return ["coin"]
        case .follow: return ["follow"]
        }
    }

    var excludeWords: [String] {
        switch self {
        case .follow: return ["关注者", "粉丝", "followers", "关注了", "关注的人"]
        case .like: return ["猜你喜欢", "你可能喜欢", "likes you"]
        default: return []
        }
    }

    var doneWords: [String] {
        switch self {
        case .like: return ["已赞", "已点赞", "取消点赞", "取消赞", "unlike", "liked"]
        case .collect: return ["已收藏", "取消收藏", "remove bookmark", "bookmarked", "remove from bookmarks"]
        case .coin: return ["已投币"]
        case .follow: return ["已关注", "取消关注", "互相关注", "following", "unfollow"]
        }
    }
}

public enum ActionLabels {
    /// 文字或 class 里有这个动作的词；文字太长的（多半是正文）不算
    public static func matches(_ a: QuickAction, text: String, classes: String) -> Bool {
        let t = text.lowercased(), c = classes.lowercased()
        if a.excludeWords.contains(where: { t.contains($0.lowercased()) }) { return false }
        if t.count <= 40, a.textWords.contains(where: { t.contains($0.lowercased()) }) { return true }
        return a.classWords.contains(where: { c.contains($0) })
    }

    /// 是否已经做过。true = 看出来做过了；nil = 看不出来
    public static func alreadyDone(_ a: QuickAction, text: String, classes: String, selected: Bool?, valueNumber: Int?) -> Bool? {
        let t = text.lowercased()
        if a.doneWords.contains(where: { t.contains($0.lowercased()) }) { return true }
        let tokens = classes.lowercased().split(separator: " ").map(String.init)
        if tokens.contains(where: { $0 == "on" || $0 == "active" || $0.hasSuffix("-active") || $0.hasPrefix("is-active")
            || $0.contains("liked") || $0.contains("collected") || $0 == "selected" }) { return true }
        if selected == true { return true }
        if valueNumber == 1 { return true }   // 复选框式按钮：1 = 选中
        return nil
    }
}

public struct ActionCandidate: Codable, Equatable {
    public var id: String
    public var role: String
    public var label: String
    public var classes: String
    public var x: Double, y: Double, w: Double, h: Double
    public var distance: Double
    public var direction: String
    public var inComment: Bool
    public var alreadyDone: Bool?

    public var frame: CGRect { CGRect(x: x, y: y, width: w, height: h) }
}

public struct ActionScan {
    public var action: QuickAction
    public var context: ScreenContext
    public var candidates: [ActionCandidate]
    public var elements: [String: AXUIElement]
    public var nodes: Int
    public var elapsedMs: Double
    public var truncated: Bool
    public var root: String
}

public enum PageScanner {
    static let commentWords = ["评论", "comment", "回复", "reply", "replies", "弹幕"]

    /// 从指针所在窗口的网页（没有网页就是整个窗口）开始广度遍历，只看屏幕上看得见的部分，找某个动作的按钮
    public static func findActionButtons(_ a: QuickAction, near p: CGPoint, maxNodes: Int = 6000,
                                         maxSeconds: Double = 1.5, maxCandidates: Int = 15) -> ActionScan {
        let t0 = CFAbsoluteTimeGetCurrent()
        let system = AXUIElementCreateSystemWide()
        AXUIElementSetMessagingTimeout(system, 0.6)   // 用户主动按的一次性动作，可以多等一会儿
        let ctx = AXProbe(timeout: 0.6).context(at: p)
        var root: AXUIElement?
        var rootName = "无"
        if let hit = AX.hitPatient(system, p) {
            var cur: AXUIElement? = hit
            var steps = 0
            var window: AXUIElement?
            while let el = cur, steps < 80 {
                let r = AX.role(el)
                if r == "AXWebArea" { root = el; rootName = "网页"; break }
                if r == "AXWindow" { window = el; break }
                cur = AX.element(el, "AXParent")
                steps += 1
            }
            if root == nil, let w = window { root = w; rootName = "窗口" }
        }
        guard let start = root else {
            return ActionScan(action: a, context: ctx, candidates: [], elements: [:], nodes: 0,
                              elapsedMs: (CFAbsoluteTimeGetCurrent() - t0) * 1000, truncated: false, root: rootName)
        }
        return findActionButtons(a, root: start, rootName: rootName, near: p, context: ctx, started: t0,
                                 maxNodes: maxNodes, maxSeconds: maxSeconds, maxCandidates: maxCandidates)
    }

    /// 从给定的根节点开始找（测试页、或已经知道是哪个网页时用；不做命中测试，不受窗口遮挡影响）
    public static func findActionButtons(_ a: QuickAction, root start: AXUIElement, rootName: String, near p: CGPoint,
                                         context ctx: ScreenContext, started t0: Double = CFAbsoluteTimeGetCurrent(),
                                         maxNodes: Int = 6000, maxSeconds: Double = 1.5, maxCandidates: Int = 15) -> ActionScan {
        let visible = visibleScreensAX()
        var queue: [(AXUIElement, Bool, Int)] = [(start, false, 0)]
        var head = 0
        var nodes = 0
        var truncated = false
        var found: [(AXNode, Bool)] = []
        while head < queue.count {
            if nodes >= maxNodes || (nodes % 50 == 0 && CFAbsoluteTimeGetCurrent() - t0 > maxSeconds) { truncated = true; break }
            let (el, inComment, depth) = queue[head]
            head += 1
            let n = AXNode.read(el)
            nodes += 1
            if let f = n.frame, f.width > 1, f.height > 1, !f.intersects(visible) { continue }   // 屏幕外的整棵子树不看
            let low = (n.text + " " + n.classText).lowercased()
            let ic = inComment || (!n.children.isEmpty && (n.frame?.height ?? 0) > 60 && commentWords.contains { low.contains($0) })
            if n.buttonish, ActionLabels.matches(a, text: n.text, classes: n.classText) {
                found.append((n, ic))
            }
            if depth < 70 { for c in n.children { queue.append((c, ic, depth + 1)) } }
        }
        // 同一个按钮常被外层 div 和里层 svg 都匹配上：中心靠得很近的只留先遇到的（外层）
        var kept: [(AXNode, Bool)] = []
        for (n, ic) in found {
            guard let f = n.frame else { continue }
            if kept.contains(where: { k in
                guard let g = k.0.frame else { return false }
                return hypot(g.midX - f.midX, g.midY - f.midY) < 10
            }) { continue }
            kept.append((n, ic))
        }
        let sorted = kept.map { (n: $0.0, ic: $0.1, d: Geometry.distance(p, $0.0.frame!)) }.sorted { $0.d < $1.d }.prefix(maxCandidates)
        var cands: [ActionCandidate] = []
        var els: [String: AXUIElement] = [:]
        for (i, c) in sorted.enumerated() {
            let id = "b\(i + 1)"
            let f = c.n.frame!
            cands.append(ActionCandidate(id: id, role: c.n.role, label: AXProbe.clip(c.n.text, 60), classes: AXProbe.clip(c.n.classText, 80),
                                         x: Double(f.minX), y: Double(f.minY), w: Double(f.width), h: Double(f.height),
                                         distance: (c.d * 10).rounded() / 10, direction: Geometry.direction(from: p, to: f),
                                         inComment: c.ic,
                                         alreadyDone: ActionLabels.alreadyDone(a, text: c.n.text, classes: c.n.classText,
                                                                               selected: c.n.selected, valueNumber: c.n.valueNumber)))
            els[id] = c.n.el
        }
        return ActionScan(action: a, context: ctx, candidates: cands, elements: els, nodes: nodes,
                          elapsedMs: (CFAbsoluteTimeGetCurrent() - t0) * 1000, truncated: truncated, root: rootName)
    }

    /// 重新读一个按钮的状态（执行后回读用）
    public static func state(of el: AXUIElement, _ a: QuickAction) -> (label: String, done: Bool?) {
        let n = AXNode.read(el)
        return (AXProbe.clip(n.text + (n.classText.isEmpty ? "" : " [\(n.classText)]"), 80),
                ActionLabels.alreadyDone(a, text: n.text, classes: n.classText, selected: n.selected, valueNumber: n.valueNumber))
    }
}

/// J11：在候选按钮里选“主内容的那个”，不是评论区里的
public enum ActionQuestions {
    public static let noneId = "none"

    public static func requestBody(_ a: QuickAction, context: ScreenContext, pointer: CGPoint, candidates: [ActionCandidate],
                                   model: String = ClickQuestions.model) -> [String: Any] {
        var state: [String: Any] = [
            "requested_action": a.zh,
            "app": context.appName ?? "unknown",
            "pointer": ["x": Int(pointer.x), "y": Int(pointer.y)],
            "candidates": candidates.map { c -> [String: Any] in
                var o: [String: Any] = ["id": c.id, "role": c.role, "label": c.label, "classes": c.classes,
                                        "distance_px": Int(c.distance.rounded()), "direction_from_pointer": c.direction,
                                        "size_px": "\(Int(c.w))x\(Int(c.h))", "in_comment_area": c.inComment]
                if let d = c.alreadyDone { o["already_done_hint"] = d }
                return o
            },
        ]
        if let t = context.windowTitle { state["window_title"] = t }
        if let u = context.url { state["page_url"] = u }
        var criteria: [String: String] = [:]
        for c in candidates { criteria[c.id] = "\(c.role) “\(c.label.isEmpty ? c.classes : c.label)”" }
        criteria[noneId] = "None of these is the \(a.zh) button of the main content"
        return [
            "model": model,
            "state": state,
            "questions": [
                "target": [
                    "type": "choice",
                    "instructions": """
                    The user pressed a shortcut to \(a.zh) (`requested_action`) the main content they are looking at: the note, video or post \
                    nearest the pointer, not a comment, a reply or a recommended item. Which candidate in `candidates` is that button? \
                    Prefer candidates outside `in_comment_area`, use `label` and `classes` to tell the action buttons apart, and use \
                    `distance_px` to pick the one belonging to the content near the pointer. Choose none if no candidate is that button.
                    """,
                    "criteria": criteria,
                ] as [String: Any],
            ] as [String: Any],
        ]
    }

    public static func parse(_ data: Data) throws -> (choice: String, probabilities: [String: Double], confidence: Double?) {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let t = (root["answers"] as? [String: Any])?["target"] as? [String: Any],
              let c = t["choice"] as? String else { throw ClickQuestions.ParseError.malformed("回复里没有 answers.target.choice") }
        var p: [String: Double] = [:]
        for (k, v) in (t["probabilities"] as? [String: Any]) ?? [:] { if let d = (v as? NSNumber)?.doubleValue { p[k] = d } }
        return (c, p, (t["confidence"] as? NSNumber)?.doubleValue)
    }

    /// 没有 Key 时：评论区外最近的那个；全在评论区就取最近的
    public static func mock(_ candidates: [ActionCandidate]) -> String {
        (candidates.first { !$0.inComment } ?? candidates.first)?.id ?? noneId
    }
}

// MARK: - F2 图片翻页

public enum FlipDirection: String { case next, prev }

public struct FlipButton {
    public var element: AXUIElement
    public var label: String
    public var frame: CGRect
}

public enum ImageNav {
    static func words(_ d: FlipDirection) -> [String] {
        d == .next ? ["下一张", "下一个", "下一页", "下一", "后一张", "next", "arrow-right", "right-arrow", "swiper-button-next", "btn-right", "icon-right"]
                   : ["上一张", "上一个", "上一页", "上一", "前一张", "prev", "previous", "arrow-left", "left-arrow", "swiper-button-prev", "btn-left", "icon-left"]
    }

    /// 指针下往上找一个够大的容器（图集、轮播），在里面找“上一张 / 下一张”按钮
    public static func findButton(_ d: FlipDirection, near p: CGPoint, maxNodes: Int = 800) -> (button: FlipButton?, container: String, nodes: Int) {
        let system = AXUIElementCreateSystemWide()
        AXUIElementSetMessagingTimeout(system, 0.6)
        guard let hit = AX.hitPatient(system, p) else { return (nil, "指针下读不到元素", 0) }
        var cur: AXUIElement? = hit
        var container: AXUIElement?
        var containerDesc = "无"
        var steps = 0
        while let el = cur, steps < 10 {
            let r = AX.role(el)
            if r == "AXWebArea" || r == "AXWindow" { break }
            if let f = AX.frame(el), f.width >= 240, f.height >= 160 { container = el; containerDesc = "\(r) \(Int(f.width))×\(Int(f.height))" }
            if container != nil && steps >= 3 { break }
            cur = AX.element(el, "AXParent")
            steps += 1
        }
        guard let root = container else { return (nil, containerDesc, 0) }
        let r = findButton(d, in: root, near: p, maxNodes: maxNodes)
        return (r.button, containerDesc, r.nodes)
    }

    /// 文字或 class 是否表示这个方向。class 按词拆开看：“arrow-controller right”里 arrow 和 right 分属两个词
    public static func means(_ d: FlipDirection, text: String, classes: String) -> Bool {
        let t = text.lowercased()
        if words(d).contains(where: { t.contains($0) }) { return true }
        let tokens = classes.lowercased().split(whereSeparator: { $0 == " " || $0 == "-" || $0 == "_" }).map(String.init)
        let dirWords = d == .next ? ["next", "right"] : ["prev", "previous", "left"]
        let navWords = ["arrow", "btn", "button", "swiper", "control", "controller", "slide", "slider", "carousel", "nav", "icon", "page"]
        if tokens.contains(where: { $0 == "next" || $0 == "prev" || $0 == "previous" }) { return tokens.contains(where: { dirWords.contains($0) }) }
        return tokens.contains(where: { dirWords.contains($0) }) && tokens.contains(where: { navWords.contains($0) })
    }

    /// 在已知容器里找翻页按钮：先按文字 / class，没有就按位置（容器左右边缘、垂直居中的小按钮）
    public static func findButton(_ d: FlipDirection, in root: AXUIElement, near p: CGPoint, maxNodes: Int = 800) -> (button: FlipButton?, nodes: Int) {
        var queue: [AXUIElement] = [root]
        var head = 0
        var labeled: [(AXNode, CGRect)] = []
        var small: [(AXNode, CGRect)] = []
        while head < queue.count && head < maxNodes {
            let n = AXNode.read(queue[head])
            head += 1
            if n.buttonish, let f = n.frame {
                if means(d, text: n.text, classes: n.classText) { labeled.append((n, f)) }
                else if AXNode.buttonRoles.contains(n.role), f.width <= 80, f.height <= 80 { small.append((n, f)) }
            }
            queue.append(contentsOf: n.children)
        }
        func make(_ x: (AXNode, CGRect)) -> FlipButton {
            FlipButton(element: x.0.el, label: AXProbe.clip(x.0.text.isEmpty ? x.0.classText : x.0.text, 40), frame: x.1)
        }
        if let best = labeled.min(by: { Geometry.distance(p, $0.1) < Geometry.distance(p, $1.1) }) { return (make(best), head) }
        // 按位置兜底：找离指针最近的、包含这些小按钮的图片区域很难，直接用根容器的边框
        if let cf = AX.frame(root), cf.width >= 200 {
            let edge = cf.width * 0.18
            let side = small.filter { x in
                let f = x.1
                let inMiddle = f.midY > cf.minY + cf.height * 0.2 && f.midY < cf.maxY - cf.height * 0.2
                let nearEdge = d == .next ? f.maxX >= cf.maxX - edge : f.minX <= cf.minX + edge
                return inMiddle && nearEdge
            }
            if let best = side.min(by: { Geometry.distance(p, $0.1) < Geometry.distance(p, $1.1) }) {
                var b = make(best)
                b.label = "位置判断：" + (b.label.isEmpty ? "无文字按钮" : b.label)
                return (b, head)
            }
        }
        return (nil, head)
    }
}

// MARK: - 发输入

public enum InputPoster {
    /// 先用辅助功能“按下”；不支持就在元素中心点一下，再把光标挪回原处
    @discardableResult
    public static func press(_ el: AXUIElement, frame: CGRect?) -> String {
        if AXUIElementPerformAction(el, "AXPress" as CFString) == .success { return "AXPress" }
        guard let f = frame else { return "failed" }
        click(at: CGPoint(x: f.midX, y: f.midY))
        return "mouse_click"
    }

    public static func click(at pt: CGPoint) {
        let back = ScreenGeometry.mouseAX()
        let src = CGEventSource(stateID: .hidSystemState)
        for type in [CGEventType.mouseMoved, .leftMouseDown, .leftMouseUp] {
            CGEvent(mouseEventSource: src, mouseType: type, mouseCursorPosition: pt, mouseButton: .left)?.post(tap: .cghidEventTap)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.06) {
            CGWarpMouseCursorPosition(back)
            CGAssociateMouseAndMouseCursorPosition(1)
        }
    }

    public static func key(_ code: CGKeyCode, flags: CGEventFlags = []) {
        let src = CGEventSource(stateID: .hidSystemState)
        let down = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: true)
        let up = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: false)
        down?.flags = flags
        up?.flags = flags
        down?.post(tap: .cghidEventTap)
        up?.post(tap: .cghidEventTap)
    }

    public static let left: CGKeyCode = 0x7B, right: CGKeyCode = 0x7C, returnKey: CGKeyCode = 0x24, f: CGKeyCode = 0x03, v: CGKeyCode = 0x09
}

// MARK: - 读前台应用的网址和选中文字

public enum FrontApp {
    /// 前台应用焦点窗口里网页的地址
    public static func webURL(pid: pid_t) -> String? {
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, 0.25)
        guard let win = AX.element(app, "AXFocusedWindow") else { return nil }
        var queue = [win]
        var head = 0
        while head < queue.count && head < 300 {
            let el = queue[head]
            head += 1
            if AX.role(el) == "AXWebArea" { return AX.url(el) }
            queue.append(contentsOf: AX.children(el))
        }
        return AX.string(win, "AXDocument")
    }

    /// 前台应用里当前选中的文字（用来预填搜索词）
    public static func selectedText(pid: pid_t) -> String? {
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, 0.25)
        guard let f = AX.element(app, "AXFocusedUIElement"), let s = AX.string(f, "AXSelectedText") else { return nil }
        return s.count <= 200 ? s : String(s.prefix(200))
    }
}


/// 在所有正在运行的应用里找网址包含某段文字的网页节点（测试页验证用）
public enum WebAreaLocator {
    public static func find(urlContains needle: String, maxNodesPerApp: Int = 4000) -> (AXUIElement, String, CGRect?)? {
        for app in NSWorkspace.shared.runningApplications where app.activationPolicy == .regular {
            let el = AXUIElementCreateApplication(app.processIdentifier)
            AXUIElementSetMessagingTimeout(el, 0.3)
            var queue = AX.children(el)
            var head = 0
            while head < queue.count && head < maxNodesPerApp {
                let n = queue[head]
                head += 1
                if AX.role(n) == "AXWebArea", let u = AX.url(n), u.contains(needle) {
                    return (n, app.localizedName ?? "?", AX.frame(n))
                }
                queue.append(contentsOf: AX.children(n))
            }
        }
        return nil
    }
}
