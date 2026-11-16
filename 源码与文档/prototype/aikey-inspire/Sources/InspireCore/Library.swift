import Foundation
import CoreGraphics

/// 一条灵感：圈住的截图 + 用户说明的意图 + 来源
public struct InspirationItem: Codable, Identifiable, Equatable {
    public var id: String
    public var createdAt: Date
    public var intent: String
    public var category: String?
    public var categorySource: String?
    public var categoryProbabilities: [String: Double]?
    public var appName: String?
    public var bundleId: String?
    public var windowTitle: String?
    public var url: String?
    public var texts: [String]
    public var rect: [Double]?
    public var imageFile: String?

    public init(intent: String, context: ScreenContext, texts: [String], rect: CGRect?) {
        id = UUID().uuidString
        createdAt = Date()
        self.intent = intent
        appName = context.appName
        bundleId = context.bundleId
        windowTitle = context.windowTitle
        url = context.url
        self.texts = texts
        if let r = rect { self.rect = [Double(r.minX), Double(r.minY), Double(r.width), Double(r.height)] }
    }

    /// 丢给 agent 时用的文字
    public func promptText(imagePath: String?) -> String {
        var lines = ["【灵感】\(intent.isEmpty ? "（未写意图）" : intent)"]
        if let c = category { lines.append("类别：\(CategoryQuestion.displayName(c))") }
        let src = [appName, windowTitle].compactMap { $0 }.joined(separator: " · ")
        if !src.isEmpty { lines.append("来源：\(src)") }
        if let u = url { lines.append("链接：\(u)") }
        if !texts.isEmpty { lines.append("圈内文字：\(texts.prefix(6).joined(separator: " / "))") }
        if let p = imagePath { lines.append("截图：\(p)") }
        return lines.joined(separator: "\n")
    }
}

/// 灵感库：~/Library/Application Support/AIKeyInspire/Library/<id>/{item.json, shot.png}
public final class LibraryStore {
    public let root: URL
    private let enc: JSONEncoder = {
        let e = JSONEncoder()
        e.outputFormatting = [.prettyPrinted, .sortedKeys]
        e.dateEncodingStrategy = .iso8601
        return e
    }()
    private let dec: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()

    /// 删除时移到废纸篓；测试里用 false，直接删临时目录
    public var useTrash = true

    public init(root: URL? = nil) {
        self.root = root ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("AIKeyInspire/Library", isDirectory: true)
        try? FileManager.default.createDirectory(at: self.root, withIntermediateDirectories: true)
    }

    public func all() -> [InspirationItem] {
        let dirs = (try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []
        return dirs.compactMap { d in
            guard let data = try? Data(contentsOf: d.appendingPathComponent("item.json")) else { return nil }
            return try? dec.decode(InspirationItem.self, from: data)
        }.sorted { $0.createdAt > $1.createdAt }
    }

    @discardableResult
    public func save(_ item: InspirationItem, png: Data?) throws -> InspirationItem {
        var it = item
        let dir = root.appendingPathComponent(it.id, isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        if let png {
            try png.write(to: dir.appendingPathComponent("shot.png"))
            it.imageFile = "shot.png"
        }
        try enc.encode(it).write(to: dir.appendingPathComponent("item.json"))
        return it
    }

    public func update(_ item: InspirationItem) throws {
        let dir = root.appendingPathComponent(item.id, isDirectory: true)
        try enc.encode(item).write(to: dir.appendingPathComponent("item.json"))
    }

    /// 移到废纸篓（可恢复），不直接抹掉
    public func delete(id: String) throws {
        let dir = root.appendingPathComponent(id, isDirectory: true)
        if useTrash { try FileManager.default.trashItem(at: dir, resultingItemURL: nil) }
        else { try FileManager.default.removeItem(at: dir) }
    }

    public func imageURL(_ item: InspirationItem) -> URL? {
        guard let f = item.imageFile else { return nil }
        return root.appendingPathComponent(item.id, isDirectory: true).appendingPathComponent(f)
    }
}

/// 圈选后给灵感打类别：一个 Choice，带“其他”
public enum CategoryQuestion {
    public static let options: [(id: String, zh: String, desc: String)] = [
        ("color", "配色", "Color: a color palette, color pairing or gradient worth reusing"),
        ("layout", "排版", "Layout: page composition, typography or information hierarchy"),
        ("product_form", "产品造型", "Product form: industrial design, physical shape, material or finish of an object"),
        ("interaction", "交互", "Interaction: a UI flow, control, animation or way of operating software"),
        ("copy", "文案", "Copy: a headline, slogan, wording or way of phrasing"),
        ("photo", "摄影构图", "Photography: camera angle, lighting or composition of a photo"),
        ("material", "素材", "Asset: an image, icon, texture or illustration to reuse directly"),
        ("other", "其他", "Other: none of the above"),
    ]

    public static func displayName(_ id: String) -> String { options.first { $0.id == id }?.zh ?? id }

    public static func requestBody(intent: String, context: ScreenContext, texts: [String], model: String = ClickQuestions.model) -> [String: Any] {
        var state: [String: Any] = [
            "user_intent": intent,
            "app": context.appName ?? "unknown",
            "visible_text_inside_circle": Array(texts.prefix(12)),
        ]
        if let t = context.windowTitle { state["page_title"] = t }
        if let u = context.url { state["page_url"] = u }
        var criteria: [String: String] = [:]
        for o in options { criteria[o.id] = o.desc }
        return [
            "model": model,
            "state": state,
            "questions": [
                "category": [
                    "type": "choice",
                    "instructions": "The user circled part of the screen as inspiration and described why in `user_intent`. What kind of inspiration is it? Use `visible_text_inside_circle` and the page as supporting context.",
                    "criteria": criteria,
                ] as [String: Any],
            ] as [String: Any],
        ]
    }

    public static func parse(_ data: Data) throws -> (String, [String: Double]) {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let a = (root["answers"] as? [String: Any])?["category"] as? [String: Any],
              let c = a["choice"] as? String else { throw ClickQuestions.ParseError.malformed("回复里没有 answers.category.choice") }
        var p: [String: Double] = [:]
        for (k, v) in (a["probabilities"] as? [String: Any]) ?? [:] { if let d = (v as? NSNumber)?.doubleValue { p[k] = d } }
        return (c, p)
    }

    /// 没有 Key 时按关键词猜，仅供界面联调
    public static func mock(intent: String) -> String {
        let rules: [(String, [String])] = [
            ("color", ["颜色", "配色", "色"]), ("layout", ["排版", "版式", "字体", "布局"]),
            ("product_form", ["造型", "外观", "材质", "形状"]), ("interaction", ["交互", "动效", "按钮", "流程"]),
            ("copy", ["文案", "标题", "slogan", "口号"]), ("photo", ["构图", "拍", "光线", "照片"]),
            ("material", ["素材", "图标", "纹理", "插画"]),
        ]
        for (id, words) in rules where words.contains(where: { intent.localizedCaseInsensitiveContains($0) }) { return id }
        return "other"
    }
}

/// 追加写 JSONL：~/Library/Logs/AIKeyInspire/<name>.jsonl
public final class JSONLLog {
    public let url: URL
    private let q = DispatchQueue(label: "aikey.inspire.log")

    public static var directory: URL {
        FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask)[0].appendingPathComponent("Logs/AIKeyInspire", isDirectory: true)
    }

    public init(name: String, directory: URL? = nil) {
        let dir = directory ?? JSONLLog.directory
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        url = dir.appendingPathComponent("\(name).jsonl")
    }

    public func append(_ obj: [String: Any]) {
        q.async {
            var o = obj
            o["ts"] = ISO8601DateFormatter().string(from: Date())
            guard JSONSerialization.isValidJSONObject(o),
                  var line = try? JSONSerialization.data(withJSONObject: o, options: [.sortedKeys]) else { return }
            line.append(0x0A)
            if let h = try? FileHandle(forWritingTo: self.url) {
                h.seekToEndOfFile(); h.write(line); try? h.close()
            } else {
                try? line.write(to: self.url)
            }
        }
    }
}
