import Foundation

/// F1 随处快速搜索：决定去哪搜、搜什么、打开哪个网址。纯逻辑，不碰界面。
public struct SearchSite: Equatable {
    public let id: String
    public let name: String
    /// 用来认出“当前在这个网站”
    public let hosts: [String]
    /// 输入里的点名写法，比如“小红书 奶油风”“xhs 奶油风”
    public let prefixes: [String]
    /// 搜索结果网址，{q} 换成编码后的搜索词（格式未逐个核实，见功能定义 F1）
    public let template: String
}

public enum SearchDestination: Equatable {
    case site(SearchSite)
    case inPage
    case library

    public var name: String {
        switch self {
        case .site(let s): return s.name
        case .inPage: return "当前页面内查找"
        case .library: return "灵感库"
        }
    }
}

public struct SearchPlan: Equatable {
    public var destination: SearchDestination
    public var query: String
    /// 为什么去这里（调试用）
    public var reason: String

    public var url: URL? {
        if case .site(let s) = destination { return QuickSearch.url(s, query) }
        return nil
    }
}

public enum QuickSearch {
    public static let sites: [SearchSite] = [
        SearchSite(id: "xiaohongshu", name: "小红书", hosts: ["xiaohongshu.com", "xhslink.com"],
                   prefixes: ["小红书", "红书", "xhs"], template: "https://www.xiaohongshu.com/search_result?keyword={q}"),
        SearchSite(id: "bilibili", name: "B 站", hosts: ["bilibili.com", "b23.tv"],
                   prefixes: ["哔哩哔哩", "b站", "bili", "bilibili"], template: "https://search.bilibili.com/all?keyword={q}"),
        SearchSite(id: "x", name: "推特", hosts: ["x.com", "twitter.com"],
                   prefixes: ["推特", "twitter", "x"], template: "https://x.com/search?q={q}"),
        SearchSite(id: "zhihu", name: "知乎", hosts: ["zhihu.com"],
                   prefixes: ["知乎", "zh"], template: "https://www.zhihu.com/search?type=content&q={q}"),
        SearchSite(id: "douyin", name: "抖音", hosts: ["douyin.com"],
                   prefixes: ["抖音", "dy"], template: "https://www.douyin.com/search/{q}"),
        SearchSite(id: "youtube", name: "YouTube", hosts: ["youtube.com", "youtu.be"],
                   prefixes: ["youtube", "油管", "yt"], template: "https://www.youtube.com/results?search_query={q}"),
        SearchSite(id: "baidu", name: "百度", hosts: ["baidu.com"],
                   prefixes: ["百度", "bd"], template: "https://www.baidu.com/s?wd={q}"),
        SearchSite(id: "google", name: "Google", hosts: ["google.com", "google.com.hk"],
                   prefixes: ["谷歌", "google", "g"], template: "https://www.google.com/search?q={q}"),
    ]

    public static var defaultSite: SearchSite { sites.first { $0.id == "google" }! }

    static let inPagePrefixes = ["页内", "这页里", "这页", "本页", "find"]
    static let libraryPrefixes = ["灵感库", "我收过的", "灵感", "库"]
    /// 句首的口头语（语音转写里常见；打字时一般没有）
    /// 只收多字口头语：单个“搜”“在”可能是搜索词的一部分（“搜狗输入法”“在家健身”）
    static let leadFillers = ["帮我搜索一下", "帮我搜一下", "帮我搜索", "帮我查一下", "帮我搜", "帮我找", "搜索一下", "搜一下", "查一下", "找一下"]
    /// 网站名后面的连接词：“小红书上搜”“B站里找”
    static let joinFillers = ["上搜索", "上搜", "里搜", "里找", "上找", "搜索", "搜", "上", "里", "找", "：", ":", "，", ","]

    static func stripLeading(_ s: String, _ words: [String]) -> String {
        var t = s.trimmingCharacters(in: .whitespaces)
        var changed = true
        while changed {
            changed = false
            for w in words where t.lowercased().hasPrefix(w.lowercased()) {
                t = String(t.dropFirst(w.count)).trimmingCharacters(in: .whitespaces)
                changed = true
                break
            }
        }
        return t
    }

    /// 输入以 prefix 开头：中文前缀可以直接接内容；纯英文前缀（如 x、g、xhs）后面必须是空格或冒号，免得“xiaomi”被当成推特
    static func matchPrefix(_ s: String, _ prefix: String) -> String? {
        guard s.lowercased().hasPrefix(prefix.lowercased()) else { return nil }
        let rest = String(s.dropFirst(prefix.count))
        let asciiPrefix = prefix.unicodeScalars.allSatisfy { $0.isASCII }
        if asciiPrefix {
            guard let c = rest.first, c == " " || c == ":" || c == "：" else { return nil }
        }
        return rest
    }

    public static func host(of urlString: String?) -> String? {
        guard let u = urlString, let h = URL(string: u)?.host?.lowercased() else { return nil }
        return h
    }

    public static func site(forURL urlString: String?) -> SearchSite? {
        guard let h = host(of: urlString) else { return nil }
        return sites.first { s in s.hosts.contains { h == $0 || h.hasSuffix("." + $0) } }
    }

    public static func plan(input: String, currentURL: String?) -> SearchPlan {
        var t = stripLeading(input.replacingOccurrences(of: "\n", with: " "), leadFillers)
        // “在小红书上搜…”：只有“在”后面紧跟点名时才去掉“在”
        if t.hasPrefix("在") {
            let rest = String(t.dropFirst())
            let named = inPagePrefixes + libraryPrefixes + sites.flatMap(\.prefixes)
            if named.contains(where: { matchPrefix(rest, $0) != nil }) { t = rest }
        }
        for p in inPagePrefixes {
            if let rest = matchPrefix(t, p) {
                return SearchPlan(destination: .inPage, query: stripLeading(rest, joinFillers), reason: "点名“\(p)”")
            }
        }
        for p in libraryPrefixes {
            if let rest = matchPrefix(t, p) {
                return SearchPlan(destination: .library, query: stripLeading(rest, joinFillers), reason: "点名“\(p)”")
            }
        }
        for s in sites {
            for p in s.prefixes.sorted(by: { $0.count > $1.count }) {
                if let rest = matchPrefix(t, p) {
                    return SearchPlan(destination: .site(s), query: stripLeading(rest, joinFillers), reason: "点名“\(p)”")
                }
            }
        }
        if let s = site(forURL: currentURL) {
            return SearchPlan(destination: .site(s), query: t, reason: "当前网站是\(s.name)")
        }
        return SearchPlan(destination: .site(defaultSite), query: t,
                          reason: currentURL == nil ? "没读到当前网址，用默认搜索引擎" : "当前网站不在列表里，用默认搜索引擎")
    }

    /// 查询参数里要编码 & + = # ? / 这些字符
    public static func encode(_ q: String) -> String {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&+=#?/")
        return q.addingPercentEncoding(withAllowedCharacters: allowed) ?? q
    }

    public static func url(_ s: SearchSite, _ q: String) -> URL? {
        URL(string: s.template.replacingOccurrences(of: "{q}", with: encode(q)))
    }
}
