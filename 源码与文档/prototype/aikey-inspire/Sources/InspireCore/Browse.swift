import ApplicationServices
import AppKit

// 浏览部分：B2 目标模式（给信息流卡片标相关度）、B3 下一条相关的、B7 关闭弹窗。
// 先把网页看得见的部分读成一棵轻量的树（PageNode），再在树上用纯逻辑找卡片和关闭按钮，
// 这样查找规则可以脱离浏览器写单元测试。Jev 只判断“多相关 / 是不是推广 / 哪个是关闭”。

// MARK: - 网页快照

public final class PageNode {
    public var role: String
    public var subrole: String?
    /// 标题、描述、值、帮助合在一起
    public var text: String
    /// 网页的 id 和 class
    public var classes: String
    public var frame: CGRect?
    public var children: [PageNode] = []
    public var el: AXUIElement?

    public init(_ role: String, subrole: String? = nil, text: String = "", classes: String = "", frame: CGRect? = nil,
                children: [PageNode] = [], el: AXUIElement? = nil) {
        self.role = role; self.subrole = subrole; self.text = text; self.classes = classes
        self.frame = frame; self.children = children; self.el = el
    }

    /// 前序遍历
    public func walk(_ f: (PageNode) -> Void) {
        f(self)
        for c in children { c.walk(f) }
    }

    var classTokens: [String] {
        classes.lowercased().split(whereSeparator: { $0 == " " || $0 == "-" || $0 == "_" }).map(String.init)
    }
}

public enum PageSnapshot {
    /// 从网页根节点广度遍历，只读 clip 范围里看得见的部分（屏幕外、网页可视区外的整棵子树跳过）
    public static func take(_ root: AXUIElement, clip: CGRect, maxNodes: Int = 5000,
                            maxSeconds: Double = 1.5) -> (root: PageNode, nodes: Int, truncated: Bool) {
        let t0 = CFAbsoluteTimeGetCurrent()
        func make(_ n: AXNode) -> PageNode {
            PageNode(n.role, subrole: n.subrole, text: n.text, classes: n.classText, frame: n.frame, el: n.el)
        }
        let rootNode = AXNode.read(root)
        let top = make(rootNode)
        var queue: [(PageNode, [AXUIElement], Int)] = [(top, rootNode.children, 0)]
        var head = 0
        var nodes = 1
        var truncated = false
        while head < queue.count {
            let (parent, kids, depth) = queue[head]
            head += 1
            for k in kids {
                if nodes >= maxNodes || (nodes % 50 == 0 && CFAbsoluteTimeGetCurrent() - t0 > maxSeconds) { truncated = true; break }
                let n = AXNode.read(k)
                nodes += 1
                if let f = n.frame, f.width > 1, f.height > 1, !f.intersects(clip) { continue }
                let pn = make(n)
                parent.children.append(pn)
                if depth < 60 && !n.children.isEmpty { queue.append((pn, n.children, depth + 1)) }
            }
            if truncated { break }
        }
        return (top, nodes, truncated)
    }
}

/// 找网页根节点：指针下的网页；指针下不是网页时，用前台应用焦点窗口里的网页
public enum WebRoot {
    public struct Found {
        public var root: AXUIElement
        public var context: ScreenContext
        public var frame: CGRect?
    }

    public static func locate(near p: CGPoint) -> Found? {
        let system = AXUIElementCreateSystemWide()
        AXUIElementSetMessagingTimeout(system, 0.6)
        var web: AXUIElement?
        var window: AXUIElement?
        if let hit = AX.hitPatient(system, p), AX.pid(hit) != getpid() {
            var cur: AXUIElement? = hit
            var steps = 0
            while let el = cur, steps < 80 {
                let r = AX.role(el)
                if r == "AXWebArea", web == nil { web = el }
                if r == "AXWindow" { window = el; break }
                cur = AX.element(el, "AXParent")
                steps += 1
            }
        }
        if web == nil, let app = NSWorkspace.shared.frontmostApplication, app.processIdentifier != getpid() {
            let appEl = AXUIElementCreateApplication(app.processIdentifier)
            AXUIElementSetMessagingTimeout(appEl, 0.4)
            if let w = AX.element(appEl, "AXFocusedWindow") {
                window = w
                var queue = [w]
                var head = 0
                while head < queue.count && head < 400 {
                    let el = queue[head]
                    head += 1
                    if AX.role(el) == "AXWebArea" { web = el; break }
                    queue.append(contentsOf: AX.children(el))
                }
            }
        }
        guard let root = web else { return nil }
        var ctx = ScreenContext()
        if let pid = AX.pid(root), let app = NSRunningApplication(processIdentifier: pid) {
            ctx.appName = app.localizedName
            ctx.bundleId = app.bundleIdentifier
        }
        ctx.url = AX.url(root)
        ctx.windowTitle = window.flatMap { AX.string($0, "AXTitle") } ?? AX.string(root, "AXTitle")
        return Found(root: root, context: ctx, frame: AX.frame(root))
    }

    /// 网页可视区：网页框和所有屏幕的交集
    public static func viewport(_ f: Found) -> CGRect {
        let screens = visibleScreensAX()
        guard let wf = f.frame, wf.width > 10, wf.height > 10 else { return screens }
        let v = wf.intersection(screens)
        return v.isNull ? screens : v
    }
}

// MARK: - B2 信息流卡片

public struct PageCard: Equatable {
    public var id: String
    public var frame: CGRect
    /// 卡片里的文字（标题、作者、点赞数、图片说明），最多 160 字
    public var text: String
    public var title: String
    public var hasImage: Bool
    public var el: AXUIElement?

    public init(id: String, frame: CGRect, text: String, title: String, hasImage: Bool, el: AXUIElement?) {
        self.id = id; self.frame = frame; self.text = text; self.title = title; self.hasImage = hasImage; self.el = el
    }

    public static func == (a: PageCard, b: PageCard) -> Bool {
        a.id == b.id && a.frame == b.frame && a.text == b.text && a.title == b.title && a.hasImage == b.hasImage
    }
}

public enum CardFinder {
    struct Stats { var textLen = 0; var media = 0; var headings = 0; var links = 0 }

    static let textRoles: Set<String> = ["AXStaticText", "AXHeading", "AXLink", "AXImage", "AXButton"]
    static let articleSubroles: Set<String> = ["AXDocumentArticle", "AXArticle"]

    static func stats(_ n: PageNode, _ memo: inout [ObjectIdentifier: Stats]) -> Stats {
        if let s = memo[ObjectIdentifier(n)] { return s }
        var s = Stats()
        if textRoles.contains(n.role) { s.textLen += n.text.count }
        if n.role == "AXImage", let f = n.frame, f.width >= 60, f.height >= 60 { s.media += 1 }
        if n.role == "AXHeading" { s.headings += 1 }
        if n.role == "AXLink" { s.links += 1 }
        for c in n.children {
            let cs = stats(c, &memo)
            s.textLen += cs.textLen; s.media += cs.media; s.headings += cs.headings; s.links += cs.links
        }
        memo[ObjectIdentifier(n)] = s
        return s
    }

    /// 尺寸像一张卡片、有字，并且有图片 / 标题 / 链接之一
    static func cardLike(_ n: PageNode, _ s: Stats, viewport: CGRect) -> Bool {
        guard let f = n.frame, f.width >= 90, f.height >= 60,
              f.width <= min(980, viewport.width * 0.96), f.height <= 1100 else { return false }
        return (s.media > 0 || s.headings > 0) ? s.textLen >= 4 : (s.links > 0 && s.textLen >= 12)
    }

    static func visibleFraction(_ f: CGRect, _ viewport: CGRect) -> Double {
        let i = f.intersection(viewport)
        guard !i.isNull, f.width > 0, f.height > 0 else { return 0 }
        return Double(i.width * i.height / (f.width * f.height))
    }

    /// 先找 article（推特的推文、很多博客）；没有就找“一组至少 3 个、宽度相近的兄弟卡片”（小红书、B 站、搜索结果）
    public static func find(_ root: PageNode, viewport: CGRect, max: Int = 16) -> [PageCard] {
        var memo: [ObjectIdentifier: Stats] = [:]
        var picked: [PageNode] = []

        func articles(_ n: PageNode) {
            if let sr = n.subrole, articleSubroles.contains(sr), let f = n.frame, f.width >= 90, f.height >= 40 {
                picked.append(n)
                return   // 只取最外层
            }
            n.children.forEach(articles)
        }
        articles(root)

        if picked.isEmpty {
            func lists(_ n: PageNode) {
                if n.children.count >= 3 {
                    let q = n.children.filter { cardLike($0, stats($0, &memo), viewport: viewport) }
                    if q.count >= 3 {
                        let widths = q.compactMap { $0.frame?.width }.sorted()
                        let m = widths[widths.count / 2]
                        let similar = q.filter { ($0.frame?.width ?? 0) >= m * 0.6 && ($0.frame?.width ?? 0) <= m * 1.6 }
                        if similar.count >= 3 {
                            picked.append(contentsOf: similar)
                            for c in n.children where !similar.contains(where: { $0 === c }) { lists(c) }
                            return
                        }
                    }
                }
                n.children.forEach(lists)
            }
            lists(root)
        }

        let visible = picked.filter { n in n.frame.map { visibleFraction($0, viewport) >= 0.3 } ?? false }
            .sorted { a, b in
                let fa = a.frame!, fb = b.frame!
                let ra = Int(fa.minY / 24), rb = Int(fb.minY / 24)
                return ra != rb ? ra < rb : fa.minX < fb.minX
            }
            .prefix(max)
        return visible.enumerated().map { i, n in
            let (text, title) = cardText(n)
            return PageCard(id: "k\(i + 1)", frame: n.frame!, text: text, title: title,
                            hasImage: stats(n, &memo).media > 0, el: n.el)
        }
    }

    /// 卡片文字：按出现顺序去重，用 “ · ” 连起来；标题取第一个标题，否则第一个够长的链接文字
    static func cardText(_ n: PageNode) -> (String, String) {
        var parts: [String] = []
        var heading: String?
        var link: String?
        n.walk { c in
            guard textRoles.contains(c.role) else { return }
            let t = c.text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !t.isEmpty else { return }
            if c.role == "AXHeading", heading == nil { heading = t }
            if c.role == "AXLink", link == nil, t.count >= 4 { link = t }
            if !parts.contains(where: { $0 == t || $0.contains(t) }) { parts.append(t) }
        }
        let all = parts.joined(separator: " · ")
        let text = all.count > 160 ? String(all.prefix(160)) + "…" : all
        let title = heading ?? link ?? parts.first ?? ""
        return (text, title.count > 40 ? String(title.prefix(40)) + "…" : title)
    }
}

/// J2：每张卡片一个 Score（和目标多相关）+ 一个 Noul（是不是推广），一次请求并行
public struct CardJudgement: Equatable, Codable {
    public var score: Double
    public var confidence: Double?
    public var ad: Double?
    public init(score: Double, confidence: Double? = nil, ad: Double? = nil) {
        self.score = score; self.confidence = confidence; self.ad = ad
    }
    /// 推广（Noul ≥ 0.6）不论分数都算无关
    public var isAd: Bool { (ad ?? 0) >= 0.6 }
    public var relevant: Bool { !isAd && score >= 1.5 }
    public var dim: Bool { isAd || score < 0.75 }
    public var label: String { isAd ? "推广" : RecallQuestions.levelName(score) }
}

public enum CardQuestions {
    public static let levels = [
        "Unrelated to what the user is looking for",
        "Loosely related: same broad topic, but not what the user is looking for",
        "Relevant: likely worth opening for what the user is looking for",
        "Exactly what the user is looking for",
    ]
    public static let adWords = ["广告", "推广", "赞助", "sponsored", "promoted"]

    public static func cacheKey(goal: String, card: PageCard) -> String { goal + "\u{1}" + card.text }

    public static func requestBody(goal: String, context: ScreenContext, cards: [PageCard],
                                   model: String = ClickQuestions.model) -> [String: Any] {
        var page: [String: Any] = ["app": context.appName ?? "unknown"]
        if let t = context.windowTitle { page["title"] = t }
        if let u = context.url { page["url"] = u }
        var qs: [String: Any] = [:]
        for i in cards.indices {
            qs["rel_\(i)"] = [
                "type": "score",
                "instructions": "The user is browsing a feed or result list looking for `goal`. How well does `cards[\(i)]` match what they are looking for? Judge from `cards[\(i)].text` (title, author, counts, image descriptions) and the page.",
                "criteria": levels,
            ] as [String: Any]
            qs["ad_\(i)"] = [
                "type": "noul",
                "instructions": "Is `cards[\(i)]` an advertisement or paid promotion (sponsored post, 广告, 推广) rather than ordinary content?",
            ] as [String: Any]
        }
        return ["model": model,
                "state": ["goal": goal, "page": page,
                          "cards": cards.map { ["text": $0.text, "has_image": $0.hasImage] as [String: Any] }],
                "questions": qs]
    }

    /// 卡片下标 → 判断
    public static func parse(_ data: Data, count: Int) throws -> [Int: CardJudgement] {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let answers = root["answers"] as? [String: Any] else { throw ClickQuestions.ParseError.malformed("回复里没有 answers") }
        var out: [Int: CardJudgement] = [:]
        for i in 0..<count {
            guard let r = answers["rel_\(i)"] as? [String: Any], let s = (r["score"] as? NSNumber)?.doubleValue else { continue }
            let ad = ((answers["ad_\(i)"] as? [String: Any])?["noul"] as? NSNumber)?.doubleValue
            out[i] = CardJudgement(score: s, confidence: (r["confidence"] as? NSNumber)?.doubleValue, ad: ad)
        }
        guard !out.isEmpty else { throw ClickQuestions.ParseError.malformed("回复里没有 rel_* 的 score") }
        return out
    }

    /// 没有 Key 时：目标和卡片文字的二字重合度；带“广告 / 推广”字样的算推广（只供界面联调）
    public static func mock(goal: String, cards: [PageCard]) -> [Int: CardJudgement] {
        let g = Similarity.bigrams(goal)
        var out: [Int: CardJudgement] = [:]
        for (i, c) in cards.enumerated() {
            let overlap = g.isEmpty ? 0 : Double(g.intersection(Similarity.bigrams(c.text)).count) / Double(g.count)
            let ad = adWords.contains { c.text.lowercased().contains($0) } ? 0.9 : 0.05
            out[i] = CardJudgement(score: min(3, (overlap * 5 * 10).rounded() / 10), ad: ad)
        }
        return out
    }

    /// B3：指针下方第一张相关卡片（同一行时取右边的）；没有就返回 nil
    public static func next(after p: CGPoint, cards: [PageCard], judgements: [String: CardJudgement]) -> PageCard? {
        let rel = cards.filter { judgements[$0.id]?.relevant == true }
        let current = rel.first { $0.frame.contains(p) }
        return rel.filter { c in
            if let cur = current {
                if c.id == cur.id { return false }
                let sameRow = abs(c.frame.minY - cur.frame.minY) < 24
                return sameRow ? c.frame.minX > cur.frame.minX : c.frame.minY > cur.frame.minY
            }
            return c.frame.midY > p.y + 8
        }.sorted { a, b in
            let ra = Int(a.frame.minY / 24), rb = Int(b.frame.minY / 24)
            return ra != rb ? ra < rb : a.frame.minX < b.frame.minX
        }.first
    }
}

// MARK: - B7 关闭弹窗

public struct CloseCandidate: Equatable, Codable {
    public enum Kind: String, Codable { case close, decline, positional, cancel }
    public var id: String
    public var role: String
    public var label: String
    public var classes: String
    public var x: Double, y: Double, w: Double, h: Double
    public var inDialog: Bool
    public var kind: Kind
    public var frame: CGRect { CGRect(x: x, y: y, width: w, height: h) }

    public init(id: String, role: String, label: String, classes: String, x: Double, y: Double, w: Double, h: Double,
                inDialog: Bool, kind: Kind) {
        self.id = id; self.role = role; self.label = label; self.classes = classes
        self.x = x; self.y = y; self.w = w; self.h = h; self.inDialog = inDialog; self.kind = kind
    }
}

public struct PopupScan {
    public var dialogs: [CGRect]
    /// 弹窗里的文字（前 120 字），给 Jev 当上下文
    public var dialogText: String
    public var candidates: [CloseCandidate]
    public var elements: [String: AXUIElement]

    public init(dialogs: [CGRect], dialogText: String, candidates: [CloseCandidate], elements: [String: AXUIElement]) {
        self.dialogs = dialogs; self.dialogText = dialogText; self.candidates = candidates; self.elements = elements
    }
}

public enum PopupFinder {
    static let dialogSubroles: Set<String> = ["AXApplicationDialog", "AXApplicationAlertDialog", "AXDialog", "AXSystemDialog", "AXFloatingWindow"]
    static let dialogClassWords: Set<String> = ["modal", "dialog", "popup", "overlay", "mask", "lightbox", "drawer"]
    /// 完全等于这些（去掉空格、小写后）才算
    static let closeWords: Set<String> = ["关闭", "×", "✕", "✖", "╳", "x", "close", "关闭弹窗", "关闭广告", "关掉", "closedialog", "closemodal"]
    static let declineWords: Set<String> = ["暂不登录", "以后再说", "下次再说", "稍后再说", "跳过", "我知道了", "知道了", "不感兴趣", "残忍拒绝",
                                            "不用了", "暂不", "暂不需要", "dismiss", "notnow", "nothanks", "skip", "maybelater", "later", "gotit"]
    static let cancelWords: Set<String> = ["取消", "cancel"]
    static let closeClassWords: Set<String> = ["close", "dismiss", "closebtn", "closebutton"]
    /// 出现这些字的按钮一律不按：关闭弹窗不能变成关注、删除、提交
    static let dangerWords = ["评论", "关注", "订阅", "删除", "发布", "提交", "确定", "确认", "购买", "支付", "登录", "注册",
                              "follow", "subscribe", "delete", "submit", "buy", "login", "signin", "signup", "register"]
    static let buttonRoles: Set<String> = ["AXButton", "AXLink", "AXCheckBox", "AXMenuButton", "AXPopUpButton"]
    static let looseRoles: Set<String> = ["AXGroup", "AXImage", "AXStaticText", "AXGenericElement", "AXUnknown"]

    static func normalized(_ s: String) -> String {
        s.lowercased().replacingOccurrences(of: " ", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func isDialog(_ n: PageNode) -> Bool {
        guard let f = n.frame, f.width >= 160, f.height >= 80 else { return false }
        return strongDialog(n) || n.classTokens.contains { dialogClassWords.contains($0) }
    }

    /// 网页明确标了 role=dialog（或系统表单）；只靠 class / id 猜的算弱
    static func strongDialog(_ n: PageNode) -> Bool {
        if let sr = n.subrole, dialogSubroles.contains(sr) { return true }
        return n.role == "AXSheet"
    }

    static func area(_ n: PageNode) -> CGFloat { n.frame.map { $0.width * $0.height } ?? .greatestFiniteMagnitude }

    static func buttonish(_ n: PageNode) -> Bool {
        guard let f = n.frame, f.width >= 6, f.height >= 6 else { return false }
        if buttonRoles.contains(n.role) { return f.width <= 360 && f.height <= 120 }
        if looseRoles.contains(n.role) { return f.width <= 160 && f.height <= 80 }
        return false
    }

    /// 这个按钮是不是“关掉 / 拒绝”。返回类型；nil = 不是
    public static func closeKind(text: String, classes: String) -> CloseCandidate.Kind? {
        let t = normalized(text)
        if dangerWords.contains(where: { t.contains($0) }) && !declineWords.contains(t) { return nil }
        if closeWords.contains(t) { return .close }
        if declineWords.contains(t) { return .decline }
        if cancelWords.contains(t) { return .cancel }
        if t.hasPrefix("关闭") && t.count <= 6 { return .close }
        let tokens = classes.lowercased().split(whereSeparator: { $0 == " " || $0 == "-" || $0 == "_" }).map(String.init)
        if tokens.contains(where: { closeClassWords.contains($0) }) && t.count <= 6 { return .close }
        return nil
    }

    public static func find(_ root: PageNode, viewport: CGRect, maxCandidates: Int = 10) -> PopupScan {
        var dialogs: [PageNode] = []
        var found: [(PageNode, Bool, CloseCandidate.Kind)] = []
        var positional: [(PageNode, PageNode)] = []
        func visit(_ n: PageNode, _ dialog: PageNode?) {
            var d = dialog
            // 弹窗套弹窗（比如 id 叫 modal-root 的外层包着 role=dialog 的框）：用里面更具体的那个
            if isDialog(n), let f = n.frame, f.intersects(viewport) {
                if let outer = d {
                    if (strongDialog(n) && !strongDialog(outer)) || area(n) < area(outer) * 0.7 { dialogs.append(n); d = n }
                } else { dialogs.append(n); d = n }
            }
            if buttonish(n), n.frame.map({ $0.intersects(viewport) }) ?? false {
                if let k = closeKind(text: n.text, classes: n.classes) {
                    found.append((n, d != nil, k))
                } else if let dd = d, n.text.trimmingCharacters(in: .whitespaces).isEmpty,
                          let f = n.frame, let df = dd.frame, f.width <= 48, f.height <= 48,
                          f.minX >= df.maxX - 90, f.maxY <= df.minY + 90 {
                    positional.append((n, dd))   // 弹窗右上角没有文字的小按钮，多半是“×”
                }
            }
            for c in n.children { visit(c, d) }
        }
        visit(root, nil)

        // 有弹窗时只看弹窗里的；没有弹窗时只收明确的“关闭”
        var list: [(PageNode, Bool, CloseCandidate.Kind)]
        if !dialogs.isEmpty {
            list = found.filter { $0.1 }
            for (n, _) in positional where !list.contains(where: { $0.0 === n }) { list.append((n, true, .positional)) }
        } else {
            list = found.filter { $0.2 == .close && ($0.0.frame.map { $0.width <= 64 && $0.height <= 64 } ?? false) }
        }
        // 外层 div 和里层图标都匹配时只留一个（中心靠得很近）
        var kept: [(PageNode, Bool, CloseCandidate.Kind)] = []
        for x in list {
            guard let f = x.0.frame else { continue }
            if kept.contains(where: { k in k.0.frame.map { hypot($0.midX - f.midX, $0.midY - f.midY) < 10 } ?? false }) { continue }
            kept.append(x)
        }
        let order: [CloseCandidate.Kind: Int] = [.close: 0, .decline: 1, .positional: 2, .cancel: 3]
        // 最具体的弹窗：明确标了 dialog 的优先，再取最小的
        let main = dialogs.min { a, b in strongDialog(a) != strongDialog(b) ? strongDialog(a) : area(a) < area(b) }
        let anchor = main?.frame.map { CGPoint(x: $0.maxX, y: $0.minY) } ?? CGPoint(x: viewport.maxX, y: viewport.minY)
        kept.sort { a, b in
            if a.1 != b.1 { return a.1 }
            if a.2 != b.2 { return order[a.2]! < order[b.2]! }
            return Geometry.distance(anchor, a.0.frame!) < Geometry.distance(anchor, b.0.frame!)
        }
        var cands: [CloseCandidate] = []
        var els: [String: AXUIElement] = [:]
        for (i, x) in kept.prefix(maxCandidates).enumerated() {
            let f = x.0.frame!
            let id = "x\(i + 1)"
            cands.append(CloseCandidate(id: id, role: x.0.role, label: AXProbe.clip(x.0.text, 40), classes: AXProbe.clip(x.0.classes, 60),
                                        x: Double(f.minX), y: Double(f.minY), w: Double(f.width), h: Double(f.height),
                                        inDialog: x.1, kind: x.2))
            if let el = x.0.el { els[id] = el }
        }
        var dialogText = ""
        if let d = main {
            var parts: [String] = []
            d.walk { c in
                if c.role == "AXStaticText" || c.role == "AXHeading", !c.text.isEmpty, !parts.contains(c.text) { parts.append(c.text) }
            }
            dialogText = AXProbe.clip(parts.joined(separator: " "), 120)
        }
        // 外层包着里层时只报里层（数量用来回读“弹窗还在不在”）
        let inner = dialogs.filter { a in !dialogs.contains { b in b !== a && (a.frame.map { f in b.frame.map { f.contains($0) } ?? false } ?? false) } }
        return PopupScan(dialogs: inner.compactMap(\.frame), dialogText: dialogText, candidates: cands, elements: els)
    }
}

/// J9：弹窗里哪个按钮是“关闭 / 暂不登录”
public enum CloseQuestions {
    public static func requestBody(_ scan: PopupScan, context: ScreenContext, model: String = ClickQuestions.model) -> [String: Any] {
        var state: [String: Any] = [
            "app": context.appName ?? "unknown",
            "popup_text": scan.dialogText,
            "candidates": scan.candidates.map { c -> [String: Any] in
                ["id": c.id, "role": c.role, "label": c.label, "classes": c.classes, "inside_popup": c.inDialog,
                 "size_px": "\(Int(c.w))x\(Int(c.h))",
                 "position": c.kind == .positional ? "small unlabeled button at the popup's top-right corner" : "labeled"]
            },
        ]
        if let t = context.windowTitle { state["page_title"] = t }
        if let u = context.url { state["page_url"] = u }
        var criteria: [String: String] = [:]
        for c in scan.candidates { criteria[c.id] = "\(c.role) “\(c.label.isEmpty ? c.classes : c.label)”" }
        criteria["none"] = "None of these dismisses the popup"
        return [
            "model": model, "state": state,
            "questions": ["target": [
                "type": "choice",
                "instructions": "A popup, login wall or promotion covers the page (`popup_text`). The user wants it gone without logging in, subscribing, buying or confirming anything. Which candidate in `candidates` closes or declines it (close, ×, not now, 暂不登录, skip)? Prefer candidates `inside_popup`.",
                "criteria": criteria,
            ] as [String: Any]],
        ]
    }

    public static func parse(_ data: Data) throws -> (choice: String, confidence: Double?) {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let t = (root["answers"] as? [String: Any])?["target"] as? [String: Any],
              let c = t["choice"] as? String else { throw ClickQuestions.ParseError.malformed("回复里没有 answers.target.choice") }
        return (c, (t["confidence"] as? NSNumber)?.doubleValue)
    }

    /// 没有 Key、或只有一个候选时：排好序的第一个
    public static func mock(_ scan: PopupScan) -> String { scan.candidates.first?.id ?? "none" }
}
