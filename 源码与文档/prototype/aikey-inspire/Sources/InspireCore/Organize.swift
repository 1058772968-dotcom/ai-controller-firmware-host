import Foundation

// 灵感库整理：K2 标签 / 项目 / 去重，K3 筛选与按任务召回，K4 多条打包，K6 回到原处。
// 纯逻辑，不碰界面；Jev 只做判断（选哪个、是不是、多相关），执行都在代码里。

// MARK: - 意图里的 #标签

public enum Hashtags {
    /// “这个排版好看 #PPT #奶油风” → 意图“这个排版好看”，标签 ["PPT", "奶油风"]
    public static func extract(_ intent: String) -> (intent: String, tags: [String]) {
        var tags: [String] = []
        var kept: [String] = []
        let stops: Set<Character> = [" ", "\n", "\t", "#", "＃", "，", ",", "。", "；", ";", "、"]
        var i = intent.startIndex
        var buf = ""
        while i < intent.endIndex {
            let c = intent[i]
            if c == "#" || c == "＃" {
                var j = intent.index(after: i)
                var tag = ""
                while j < intent.endIndex, !stops.contains(intent[j]) { tag.append(intent[j]); j = intent.index(after: j) }
                if !tag.isEmpty {
                    if !tags.contains(tag) { tags.append(tag) }
                    i = j
                    continue
                }
            }
            buf.append(c)
            i = intent.index(after: i)
        }
        kept.append(buf)
        let clean = kept.joined().replacingOccurrences(of: "  ", with: " ").trimmingCharacters(in: .whitespacesAndNewlines)
        return (clean, tags)
    }

    /// “PPT, 奶油风 配色” → ["PPT", "奶油风", "配色"]
    public static func parseList(_ s: String) -> [String] {
        var out: [String] = []
        for t in s.split(whereSeparator: { " ,，、;；\n#＃".contains($0) }) {
            let x = String(t).trimmingCharacters(in: .whitespaces)
            if !x.isEmpty && !out.contains(x) { out.append(x) }
        }
        return out
    }
}

// MARK: - 本地相似度（去重前先在代码里挑出最像的几条，再问 Jev）

public enum Similarity {
    /// 网址去掉 #片段 和常见跟踪参数，host 小写
    public static func normalizedURL(_ s: String?) -> String? {
        guard let s, var c = URLComponents(string: s), let host = c.host?.lowercased() else { return nil }
        c.fragment = nil
        let drop: Set<String> = ["xsec_token", "xsec_source", "spm_id_from", "vd_source", "share_source", "utm_source", "utm_medium",
                                 "utm_campaign", "from", "source", "s", "t"]
        c.queryItems = c.queryItems?.filter { !drop.contains($0.name.lowercased()) }
        if c.queryItems?.isEmpty == true { c.queryItems = nil }
        c.host = host
        return c.string
    }

    static func pathKey(_ s: String?) -> String? {
        guard let s, let c = URLComponents(string: s), let host = c.host?.lowercased() else { return nil }
        let path = c.path
        return path.count > 8 ? host + path : nil   // “/search”“/” 这种路径太短，不能说明是同一页
    }

    /// 连续两个字（去掉空白和标点，小写）组成的集合：中文按字、英文按字母，粗但够用
    public static func bigrams(_ s: String) -> Set<String> {
        let chars = Array(s.lowercased().unicodeScalars.filter { CharacterSet.alphanumerics.contains($0) }.map(Character.init))
        guard chars.count >= 2 else { return chars.isEmpty ? [] : [String(chars)] }
        var out = Set<String>()
        for i in 0..<(chars.count - 1) { out.insert(String([chars[i], chars[i + 1]])) }
        return out
    }

    public static func jaccard(_ a: Set<String>, _ b: Set<String>) -> Double {
        guard !a.isEmpty, !b.isEmpty else { return 0 }
        return Double(a.intersection(b).count) / Double(a.union(b).count)
    }

    static func contentText(_ it: InspirationItem) -> String { ([it.windowTitle ?? ""] + it.texts).joined(separator: " ") }

    /// 0–1：同一网址 0.45，同一路径 0.3；再加圈内文字 / 标题的重合度（0.4）和意图重合度（0.15）
    public static func score(_ a: InspirationItem, _ b: InspirationItem) -> Double {
        var s = 0.0
        if let ua = normalizedURL(a.url), ua == normalizedURL(b.url) { s += 0.45 }
        else if let pa = pathKey(a.url), pa == pathKey(b.url) { s += 0.3 }
        s += 0.4 * jaccard(bigrams(contentText(a)), bigrams(contentText(b)))
        s += 0.15 * jaccard(bigrams(a.intent), bigrams(b.intent))
        return min(1, s)
    }

    /// 和新条目最像的几条（不含自己），相似度至少 threshold
    public static func candidates(for item: InspirationItem, in library: [InspirationItem], limit: Int = 3,
                                  threshold: Double = 0.3) -> [(item: InspirationItem, score: Double)] {
        library.filter { $0.id != item.id }
            .map { ($0, score(item, $0)) }
            .filter { $0.1 >= threshold }
            .sorted { $0.1 > $1.1 }
            .prefix(limit)
            .map { (item: $0.0, score: $0.1) }
    }
}

// MARK: - J6 + J7：入库时一次请求判断 类别 / 项目 / 标签 / 是否重复

public struct OrganizeResult: Equatable {
    public var category: String
    public var categoryProbabilities: [String: Double]
    public var project: String?
    public var projectProbability: Double?
    public var tags: [String]
    public var tagProbabilities: [String: Double]
    public var duplicateOf: String?
    public var duplicateProbability: Double?
    public var source: String
}

public enum OrganizeQuestions {
    public static let tagThreshold = 0.6
    public static let duplicateThreshold = 0.7
    public static let projectThreshold = 0.5
    public static let maxTags = 12

    /// 词表里最常用的标签（不含条目已有的），最多 maxTags 个
    public static func vocabulary(_ library: [InspirationItem], excluding item: InspirationItem? = nil) -> [String] {
        var count: [String: Int] = [:]
        for it in library where it.id != item?.id { for t in it.tagList { count[t, default: 0] += 1 } }
        let have = Set(item?.tagList ?? [])
        return count.filter { !have.contains($0.key) }.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }
            .prefix(maxTags).map(\.key)
    }

    static func itemState(_ it: InspirationItem, maxTexts: Int = 10) -> [String: Any] {
        var o: [String: Any] = ["user_intent": it.intent, "app": it.appName ?? "unknown",
                                "visible_text_inside_circle": Array(it.texts.prefix(maxTexts))]
        if let t = it.windowTitle { o["page_title"] = t }
        if let u = it.url { o["page_url"] = u }
        if !it.tagList.isEmpty { o["user_tags"] = it.tagList }
        return o
    }

    /// 问题 id：category、project、tag_0…、dup_0…（id 只给代码用，模型看不到）
    public static func requestBody(item: InspirationItem, projects: [String], vocabulary: [String],
                                   similar: [InspirationItem], askProject: Bool = true,
                                   model: String = ClickQuestions.model) -> [String: Any] {
        var state: [String: Any] = ["new_item": itemState(item)]
        var qs: [String: Any] = [:]

        var criteria: [String: String] = [:]
        for o in CategoryQuestion.options { criteria[o.id] = o.desc }
        qs["category"] = [
            "type": "choice",
            "instructions": "The user circled part of the screen as inspiration (`new_item`) and described why in `new_item.user_intent`. What kind of inspiration is it? Use `new_item.visible_text_inside_circle` and the page as supporting context.",
            "criteria": criteria,
        ] as [String: Any]

        if askProject && !projects.isEmpty {
            state["user_projects"] = projects
            var pc: [String: String] = [:]
            for (i, p) in projects.enumerated() { pc["p\(i)"] = "It is a reference for the user's project “\(p)”" }
            pc["none"] = "It does not clearly belong to any of `user_projects`"
            qs["project"] = [
                "type": "choice",
                "instructions": "Which of the user's projects (`user_projects`) did the user save `new_item` for? Judge mainly from `new_item.user_intent`; the page and circled text are supporting context.",
                "criteria": pc,
            ] as [String: Any]
        }

        for (i, t) in vocabulary.prefix(maxTags).enumerated() {
            qs["tag_\(i)"] = [
                "type": "noul",
                "instructions": "The user labels saved inspirations with their own tags. Does the tag “\(t)” apply to `new_item`, judging from `new_item.user_intent`, the page and the circled text?",
            ] as [String: Any]
        }

        if !similar.isEmpty {
            state["similar_saved_items"] = similar.map { s -> [String: Any] in
                var o = itemState(s, maxTexts: 6)
                o["saved_at"] = ISO8601DateFormatter().string(from: s.createdAt)
                return o
            }
            for i in similar.indices {
                qs["dup_\(i)"] = [
                    "type": "noul",
                    "instructions": "Is `new_item` the same inspiration as `similar_saved_items[\(i)]` saved again: the same note, image, product or passage from the same source? A different item on a similar topic is not the same.",
                ] as [String: Any]
            }
        }
        return ["model": model, "state": state, "questions": qs]
    }

    public static func parse(_ data: Data, projects: [String], vocabulary: [String], similar: [InspirationItem]) throws -> OrganizeResult {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let answers = root["answers"] as? [String: Any],
              let cat = answers["category"] as? [String: Any], let c = cat["choice"] as? String else {
            throw ClickQuestions.ParseError.malformed("回复里没有 answers.category.choice")
        }
        func probs(_ a: [String: Any]?) -> [String: Double] {
            var p: [String: Double] = [:]
            for (k, v) in (a?["probabilities"] as? [String: Any]) ?? [:] { if let d = (v as? NSNumber)?.doubleValue { p[k] = d } }
            return p
        }
        var r = OrganizeResult(category: c, categoryProbabilities: probs(cat), project: nil, projectProbability: nil,
                               tags: [], tagProbabilities: [:], duplicateOf: nil, duplicateProbability: nil, source: "jev")
        if let pj = answers["project"] as? [String: Any], let choice = pj["choice"] as? String, choice != "none",
           choice.hasPrefix("p"), let i = Int(choice.dropFirst()), i < projects.count {
            let p = probs(pj)[choice] ?? 0
            r.projectProbability = p
            if p >= projectThreshold { r.project = projects[i] }
        }
        for (i, t) in vocabulary.prefix(maxTags).enumerated() {
            if let n = ((answers["tag_\(i)"] as? [String: Any])?["noul"] as? NSNumber)?.doubleValue {
                r.tagProbabilities[t] = n
                if n >= tagThreshold { r.tags.append(t) }
            }
        }
        var best: (Int, Double)?
        for i in similar.indices {
            if let n = ((answers["dup_\(i)"] as? [String: Any])?["noul"] as? NSNumber)?.doubleValue, n > (best?.1 ?? -1) { best = (i, n) }
        }
        if let (i, n) = best {
            r.duplicateProbability = n
            if n >= duplicateThreshold { r.duplicateOf = similar[i].id }
        }
        return r
    }

    /// 没有 Key 时：类别按关键词；项目名、标签出现在意图 / 标题 / 圈内文字里就算；相似度 ≥ 0.75 算重复
    public static func mock(item: InspirationItem, projects: [String], vocabulary: [String],
                            similar: [(item: InspirationItem, score: Double)]) -> OrganizeResult {
        let hay = ([item.intent, item.windowTitle ?? ""] + item.texts).joined(separator: " ")
        let project = projects.first { hay.localizedCaseInsensitiveContains($0) }
        let tags = vocabulary.filter { hay.localizedCaseInsensitiveContains($0) }
        let dup = similar.first.flatMap { $0.score >= 0.75 ? $0 : nil }
        return OrganizeResult(category: CategoryQuestion.mock(intent: item.intent), categoryProbabilities: [:],
                              project: project, projectProbability: nil, tags: tags, tagProbabilities: [:],
                              duplicateOf: dup?.item.id, duplicateProbability: similar.first?.score, source: "mock")
    }

    /// 把整理结果写回条目：用户自己定的项目 / 标签不动，只补自动的
    public static func apply(_ r: OrganizeResult, to item: InspirationItem) -> InspirationItem {
        var it = item
        it.category = r.category
        it.categorySource = r.source
        it.categoryProbabilities = r.categoryProbabilities.isEmpty ? nil : r.categoryProbabilities
        if it.projectSource != "user", let p = r.project { it.project = p; it.projectSource = r.source }
        var tags = it.tagList
        var auto = it.autoTags ?? []
        for t in r.tags where !tags.contains(t) { tags.append(t); auto.append(t) }
        it.tags = tags.isEmpty ? nil : tags
        it.autoTags = auto.isEmpty ? nil : auto
        if it.duplicateDismissed != true {
            it.duplicateOf = r.duplicateOf
            it.duplicateProbability = r.duplicateProbability
        }
        it.organizedAt = Date()
        return it
    }
}

// MARK: - J8：按任务召回（每条灵感一个 Score，分批并行）

public enum RecallQuestions {
    /// 四级相关度，0 = 无关 … 3 = 正是要找的
    public static let levels = [
        "Unrelated: the saved inspiration has nothing to do with the task",
        "Loosely related: same broad topic, but the user would probably not use it for this task",
        "Relevant: the user could reasonably use it as a reference for this task",
        "Exactly what the task needs: it directly matches what the task asks for",
    ]
    public static let levelNames = ["无关", "沾边", "相关", "正是"]
    public static let batchSize = 8
    public static let maxItems = 48

    public static func levelName(_ score: Double) -> String { levelNames[min(3, max(0, Int(score.rounded())))] }

    static func itemState(_ it: InspirationItem) -> [String: Any] {
        var o: [String: Any] = ["intent": it.intent.isEmpty ? "(no intent written)" : it.intent,
                                "visible_text": Array(it.texts.prefix(4))]
        if let c = it.category { o["category"] = CategoryQuestion.options.first { $0.id == c }?.desc.components(separatedBy: ":").first ?? c }
        if let p = it.project { o["project"] = p }
        if !it.tagList.isEmpty { o["tags"] = it.tagList }
        if let t = it.windowTitle { o["source_title"] = t }
        return o
    }

    /// 一批：state.items[k]，问题 id r_<k>
    public static func requestBody(task: String, items: [InspirationItem], model: String = ClickQuestions.model) -> [String: Any] {
        var qs: [String: Any] = [:]
        for i in items.indices {
            qs["r_\(i)"] = [
                "type": "score",
                "instructions": "The user is working on `task` and wants useful references from their saved inspiration library. How useful is the saved inspiration `items[\(i)]` for this task? Judge mainly from `items[\(i)].intent` (why the user saved it), with its category, tags, project and visible text as support.",
                "criteria": levels,
            ] as [String: Any]
        }
        return ["model": model, "state": ["task": task, "items": items.map(itemState)], "questions": qs]
    }

    public static func batches(_ items: [InspirationItem]) -> [[InspirationItem]] {
        let capped = Array(items.prefix(maxItems))
        return stride(from: 0, to: capped.count, by: batchSize).map { Array(capped[$0..<min($0 + batchSize, capped.count)]) }
    }

    /// 返回 条目 id → 分数（0–3）
    public static func parse(_ data: Data, items: [InspirationItem]) throws -> [String: Double] {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let answers = root["answers"] as? [String: Any] else { throw ClickQuestions.ParseError.malformed("回复里没有 answers") }
        var out: [String: Double] = [:]
        for (i, it) in items.enumerated() {
            if let s = ((answers["r_\(i)"] as? [String: Any])?["score"] as? NSNumber)?.doubleValue { out[it.id] = s }
        }
        guard !out.isEmpty else { throw ClickQuestions.ParseError.malformed("回复里没有 r_* 的 score") }
        return out
    }

    /// 没有 Key 时：任务和条目文字的二字重合度，映射到 0–3（只供界面联调）
    public static func mock(task: String, items: [InspirationItem]) -> [String: Double] {
        let t = Similarity.bigrams(task)
        var out: [String: Double] = [:]
        for it in items {
            let hay = Similarity.bigrams(([it.intent, it.project ?? "", it.windowTitle ?? ""] + it.tagList + it.texts).joined(separator: " "))
            let overlap = t.isEmpty ? 0 : Double(t.intersection(hay).count) / Double(t.count)
            out[it.id] = min(3, (overlap * 6 * 10).rounded() / 10)
        }
        return out
    }
}

// MARK: - K3 筛选（时间、来源、类别这类由代码做，不问模型）

public struct LibraryQuery: Equatable {
    public static let noProject = "__none__"

    public var text = ""
    public var category: String?
    /// 项目名；noProject = 没归属的
    public var project: String?
    public var tag: String?
    public var source: String?
    /// 最近几天
    public var days: Int?
    public var unusedOnly = false
    public var duplicatesOnly = false
    public var showArchived = false

    public init() {}

    public var isEmpty: Bool { self == LibraryQuery() }

    /// 来源显示名：已知网站用网站名，否则用域名，再没有就用软件名
    public static func sourceName(_ it: InspirationItem) -> String {
        if let s = QuickSearch.site(forURL: it.url) { return s.name }
        if let h = QuickSearch.host(of: it.url) { return h.hasPrefix("www.") ? String(h.dropFirst(4)) : h }
        return it.appName ?? "未知"
    }

    public func matches(_ it: InspirationItem, now: Date = Date()) -> Bool {
        if !showArchived && it.isArchived { return false }
        if let c = category, it.category != c { return false }
        if let p = project {
            if p == LibraryQuery.noProject { if it.project != nil { return false } }
            else if it.project != p { return false }
        }
        if let t = tag, !it.tagList.contains(t) { return false }
        if let s = source, LibraryQuery.sourceName(it) != s { return false }
        if let d = days, now.timeIntervalSince(it.createdAt) > Double(d) * 86400 { return false }
        if unusedOnly && it.uses > 0 { return false }
        if duplicatesOnly && it.pendingDuplicate == nil { return false }
        let f = text.trimmingCharacters(in: .whitespaces).lowercased()
        if !f.isEmpty {
            let hay = ([it.intent, it.appName ?? "", it.windowTitle ?? "", it.url ?? "", it.project ?? "",
                        CategoryQuestion.displayName(it.category ?? "")] + it.tagList + it.texts).joined(separator: " ").lowercased()
            // 空格分开的几个词都要出现
            for w in f.split(separator: " ") where !hay.contains(w) { return false }
        }
        return true
    }

    public func apply(_ items: [InspirationItem], now: Date = Date()) -> [InspirationItem] { items.filter { matches($0, now: now) } }
}

// MARK: - K4 多条打包给 agent

public enum InspirationPack {
    /// 按类别分组的一段提示：图片路径 + 意图 + 链接 + 圈内文字
    public static func text(_ items: [InspirationItem], task: String?, imagePath: (InspirationItem) -> String?) -> String {
        var out: [String] = []
        let t = task?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        out.append("【灵感参考】共 \(items.count) 条" + (t.isEmpty ? "" : "，用于：\(t)"))
        out.append("下面是我圈选收藏的参考，每条写了我当时为什么收它。截图在给出的路径里。")
        var n = 0
        for (cat, group) in grouped(items) {
            out.append("")
            out.append("## \(CategoryQuestion.displayName(cat))（\(group.count)）")
            for it in group {
                n += 1
                out.append("\(n). \(it.intent.isEmpty ? "（未写意图）" : it.intent)")
                // 已经按类别分组了：去掉每条里重复的“类别：…”
                let catLine = "类别：\(CategoryQuestion.displayName(cat))"
                for line in it.detailLines(imagePath: imagePath(it)) where line != catLine {
                    out.append("   " + (line.hasPrefix(catLine + "　") ? String(line.dropFirst(catLine.count + 1)) : line))
                }
            }
        }
        return out.joined(separator: "\n")
    }

    /// 按类别分组，组的顺序和类别选项一致；组内保持原顺序
    public static func grouped(_ items: [InspirationItem]) -> [(String, [InspirationItem])] {
        let order = CategoryQuestion.options.map(\.id)
        var groups: [String: [InspirationItem]] = [:]
        for it in items { groups[it.category ?? "other", default: []].append(it) }
        return groups.sorted { (order.firstIndex(of: $0.key) ?? 99) < (order.firstIndex(of: $1.key) ?? 99) }.map { ($0.key, $0.value) }
    }
}

extension LibraryStore {
    /// 导出成文件夹：每条一张截图（按顺序编号）+ 一份说明，整个文件夹可以拖进 agent
    public func exportPack(_ items: [InspirationItem], task: String?, to dir: URL, now: Date = Date()) throws -> URL {
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd-HHmmss"
        let out = dir.appendingPathComponent("灵感参考-\(f.string(from: now))", isDirectory: true)
        try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        var names: [String: String] = [:]
        var n = 0
        for (_, group) in InspirationPack.grouped(items) {
            for it in group {
                n += 1
                guard let src = imageURL(it) else { continue }
                let short = it.intent.prefix(12).replacingOccurrences(of: "/", with: "-").replacingOccurrences(of: ":", with: "-")
                let name = String(format: "%02d-%@.png", n, short.isEmpty ? "灵感" : short)
                try? FileManager.default.copyItem(at: src, to: out.appendingPathComponent(name))
                names[it.id] = name
            }
        }
        let md = InspirationPack.text(items, task: task) { names[$0.id] }
        try md.write(to: out.appendingPathComponent("灵感参考.md"), atomically: true, encoding: .utf8)
        return out
    }
}

// MARK: - K6 回到原处：网页加文字片段 #:~:text=，打开后直接滚到圈过的那段

public enum SourceLink {
    /// 挑一段最可能在页面上连续出现的文字：按空格和省略号拆开，取最长的一段（6–50 字）
    public static func snippet(_ texts: [String], excluding title: String?) -> String? {
        var best = ""
        for t in texts where t != title {
            for seg in t.components(separatedBy: CharacterSet(charactersIn: " …\n")) {
                let s = seg.trimmingCharacters(in: .whitespacesAndNewlines)
                if s.count >= 6 && s.count > best.count { best = s }
            }
        }
        guard !best.isEmpty else { return nil }
        return best.count > 50 ? String(best.prefix(50)) : best
    }

    /// 文字片段里 - , & 也要编码；只放行 ASCII 字母数字（CharacterSet.alphanumerics 含汉字，不能用）
    public static func encode(_ s: String) -> String {
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._~")
        return s.addingPercentEncoding(withAllowedCharacters: allowed) ?? s
    }

    public static func url(for it: InspirationItem) -> URL? {
        guard let u = it.url, let base = URL(string: u) else { return nil }
        guard let scheme = base.scheme?.lowercased(), scheme == "http" || scheme == "https", !u.contains("#"),
              let s = snippet(it.texts, excluding: it.windowTitle) else { return base }
        return URL(string: u + "#:~:text=" + encode(s)) ?? base
    }
}
