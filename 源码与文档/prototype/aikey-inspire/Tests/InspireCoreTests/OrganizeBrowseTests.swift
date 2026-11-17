import XCTest
import CoreGraphics
@testable import InspireCore

/// 灵感库整理（K2–K6）和浏览（B2、B3、B7）的纯逻辑
final class OrganizeBrowseTests: XCTestCase {
    private func item(_ intent: String, url: String? = nil, title: String? = nil, texts: [String] = [],
                      tags: [String]? = nil, project: String? = nil, category: String? = nil, daysAgo: Double = 0) -> InspirationItem {
        var it = InspirationItem(intent: intent, context: ScreenContext(appName: "Google Chrome", windowTitle: title, url: url),
                                 texts: texts, rect: nil)
        it.tags = tags
        it.project = project
        it.category = category
        it.createdAt = Date(timeIntervalSinceNow: -daysAgo * 86400)
        return it
    }

    private func tempStore() -> LibraryStore {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("inspire-test-\(UUID().uuidString)")
        let s = LibraryStore(root: dir)
        s.useTrash = false
        return s
    }

    // MARK: K2

    func testHashtagsExtract() {
        let r = Hashtags.extract("这个排版好看 #PPT #奶油风，放进参考")
        XCTAssertEqual(r.tags, ["PPT", "奶油风"])
        XCTAssertEqual(r.intent, "这个排版好看 ，放进参考")
        XCTAssertEqual(Hashtags.extract("没有标签").tags, [])
        XCTAssertEqual(Hashtags.extract("全角＃配色 也行").tags, ["配色"])
        XCTAssertEqual(Hashtags.parseList("PPT, 奶油风 配色、PPT"), ["PPT", "奶油风", "配色"])
    }

    /// 旧版 item.json（没有新字段）还能读出来
    func testOldItemJSONStillDecodes() throws {
        let json = """
        {"id":"A1","createdAt":"2026-11-16T07:00:00Z","intent":"旧条目","texts":["一段字"],"category":"copy","categorySource":"jev"}
        """
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        let it = try d.decode(InspirationItem.self, from: Data(json.utf8))
        XCTAssertEqual(it.intent, "旧条目")
        XCTAssertNil(it.tags)
        XCTAssertEqual(it.uses, 0)
        XCTAssertFalse(it.isArchived)
        XCTAssertNil(it.pendingDuplicate)
    }

    func testSimilarityPrefersSameNote() {
        let a = item("配色好看", url: "https://www.xiaohongshu.com/explore/abc123?xsec_token=1", title: "奶油风客厅",
                     texts: ["奶油风客厅配色分享", "米白 + 原木"])
        let same = item("这个配色收一下", url: "https://www.xiaohongshu.com/explore/abc123?xsec_token=2", title: "奶油风客厅",
                        texts: ["奶油风客厅配色分享", "米白 + 原木"])
        let other = item("排版", url: "https://www.google.com/search?q=ppt", title: "PPT 排版", texts: ["极简 PPT 排版技巧"])
        XCTAssertEqual(Similarity.normalizedURL(a.url), Similarity.normalizedURL(same.url))
        XCTAssertGreaterThan(Similarity.score(a, same), 0.75)
        XCTAssertLessThan(Similarity.score(a, other), 0.2)
        let c = Similarity.candidates(for: a, in: [a, same, other])
        XCTAssertEqual(c.map(\.item.id), [same.id])
        // 两个不同的 Google 搜索页不算同一页
        XCTAssertNil(Similarity.pathKey("https://www.google.com/search?q=a"))
    }

    func testOrganizeRequestParseAndApply() throws {
        var it = item("这个排版好看，放进 PPT 参考", title: "极简 PPT", texts: ["标题 32 号字"], tags: ["极简"])
        it.projectSource = nil
        let dup = item("排版参考", title: "极简 PPT", texts: ["标题 32 号字"])
        let projects = ["AI 控制器宣传 PPT", "官网改版"]
        let vocab = ["奶油风", "PPT"]
        let body = OrganizeQuestions.requestBody(item: it, projects: projects, vocabulary: vocab, similar: [dup])
        XCTAssertTrue(JSONSerialization.isValidJSONObject(body))
        let qs = try XCTUnwrap(body["questions"] as? [String: Any])
        XCTAssertEqual(Set(qs.keys), ["category", "project", "tag_0", "tag_1", "dup_0"])
        XCTAssertEqual((qs["tag_1"] as? [String: Any])?["type"] as? String, "noul")
        let pc = try XCTUnwrap((qs["project"] as? [String: Any])?["criteria"] as? [String: String])
        XCTAssertEqual(Set(pc.keys), ["p0", "p1", "none"])
        // 指令里引用的路径都在 state 里
        let state = try XCTUnwrap(body["state"] as? [String: Any])
        XCTAssertNotNil(state["new_item"]); XCTAssertNotNil(state["user_projects"]); XCTAssertNotNil(state["similar_saved_items"])
        XCTAssertTrue(((qs["dup_0"] as? [String: Any])?["instructions"] as? String)?.contains("`similar_saved_items[0]`") ?? false)

        let reply = """
        {"answers":{"category":{"type":"choice","choice":"layout","probabilities":{"layout":0.9,"other":0.1}},
          "project":{"type":"choice","choice":"p0","probabilities":{"p0":0.8,"p1":0.1,"none":0.1}},
          "tag_0":{"type":"noul","noul":0.1},"tag_1":{"type":"noul","noul":0.93},
          "dup_0":{"type":"noul","noul":0.82}}}
        """
        let r = try OrganizeQuestions.parse(Data(reply.utf8), projects: projects, vocabulary: vocab, similar: [dup])
        XCTAssertEqual(r.category, "layout")
        XCTAssertEqual(r.project, "AI 控制器宣传 PPT")
        XCTAssertEqual(r.tags, ["PPT"])
        XCTAssertEqual(r.duplicateOf, dup.id)
        let applied = OrganizeQuestions.apply(r, to: it)
        XCTAssertEqual(applied.tags, ["极简", "PPT"])
        XCTAssertEqual(applied.autoTags, ["PPT"])
        XCTAssertEqual(applied.projectSource, "jev")
        XCTAssertEqual(applied.pendingDuplicate, dup.id)
        // 用户自己定了项目：不覆盖
        var mine = it
        mine.project = "官网改版"; mine.projectSource = "user"
        XCTAssertEqual(OrganizeQuestions.apply(r, to: mine).project, "官网改版")
        // 用户否认过重复：不再标
        var dismissed = it
        dismissed.duplicateDismissed = true
        XCTAssertNil(OrganizeQuestions.apply(r, to: dismissed).pendingDuplicate)
        // 没有项目列表时不问项目
        let noProj = OrganizeQuestions.requestBody(item: it, projects: [], vocabulary: [], similar: [])
        XCTAssertEqual(Set((noProj["questions"] as? [String: Any])?.keys ?? [:].keys), ["category"])
    }

    func testOrganizeMock() {
        let it = item("PPT 封面配色 奶油风", title: "AI 控制器宣传 PPT 参考")
        let r = OrganizeQuestions.mock(item: it, projects: ["AI 控制器宣传 PPT"], vocabulary: ["奶油风", "摄影"], similar: [])
        XCTAssertEqual(r.project, "AI 控制器宣传 PPT")
        XCTAssertEqual(r.tags, ["奶油风"])
        XCTAssertEqual(r.category, "color")
        XCTAssertNil(r.duplicateOf)
    }

    func testVocabularyMostUsedFirst() {
        let lib = [item("a", tags: ["PPT", "配色"]), item("b", tags: ["PPT"]), item("c", tags: ["摄影"])]
        let target = item("d", tags: ["摄影"])
        XCTAssertEqual(OrganizeQuestions.vocabulary(lib, excluding: target), ["PPT", "配色"])
    }

    func testProjectsMergeAndUsage() throws {
        let s = tempStore()
        defer { try? FileManager.default.removeItem(at: s.root) }
        try s.saveProjects(["PPT", " 官网 ", "PPT", ""])
        XCTAssertEqual(s.projects(), ["PPT", "官网"])
        XCTAssertEqual(s.all().count, 0, "_meta 目录不能被当成条目")

        var orig = item("配色好看", url: "https://x.com/a", tags: ["配色"])
        orig = try s.save(orig, png: nil)
        var dup = item("再收一次", url: "https://x.com/a", tags: ["奶油风"])
        dup.duplicateOf = orig.id
        dup = try s.save(dup, png: Data([1, 2, 3, 4]))
        s.markUsed([dup.id])
        let merged = try s.merge(duplicate: dup.id, into: orig.id)
        XCTAssertEqual(merged.intent, "配色好看；再收一次")
        XCTAssertEqual(merged.tags, ["配色", "奶油风"])
        XCTAssertEqual(merged.uses, 1)
        XCTAssertEqual(merged.imageFile, "shot.png", "原条目没截图时把重复条目的截图挪过来")
        XCTAssertEqual(s.all().map(\.id), [orig.id])
        s.markUsed([orig.id])
        XCTAssertEqual(s.item(id: orig.id)?.uses, 2)
        XCTAssertNotNil(s.item(id: orig.id)?.lastUsedAt)
    }

    // MARK: K3

    func testLibraryQuery() {
        var a = item("奶油风配色", url: "https://www.xiaohongshu.com/explore/1", tags: ["配色"], project: "PPT", category: "color")
        let b = item("PPT 排版", url: "https://www.google.com/search?q=x", category: "layout", daysAgo: 10)
        var c = item("旧的", category: "copy", daysAgo: 40)
        c.archived = true
        a.useCount = 2
        let all = [a, b, c]
        var q = LibraryQuery()
        XCTAssertEqual(q.apply(all).map(\.intent), ["奶油风配色", "PPT 排版"], "默认不显示归档")
        q.showArchived = true
        XCTAssertEqual(q.apply(all).count, 3)
        q = LibraryQuery(); q.category = "layout"
        XCTAssertEqual(q.apply(all).map(\.intent), ["PPT 排版"])
        q = LibraryQuery(); q.project = LibraryQuery.noProject
        XCTAssertEqual(q.apply(all).map(\.intent), ["PPT 排版"])
        q = LibraryQuery(); q.source = "小红书"
        XCTAssertEqual(q.apply(all).map(\.intent), ["奶油风配色"])
        q = LibraryQuery(); q.days = 7
        XCTAssertEqual(q.apply(all).map(\.intent), ["奶油风配色"])
        q = LibraryQuery(); q.unusedOnly = true
        XCTAssertEqual(q.apply(all).map(\.intent), ["PPT 排版"])
        q = LibraryQuery(); q.text = "配色 奶油"
        XCTAssertEqual(q.apply(all).map(\.intent), ["奶油风配色"], "空格分开的几个词都要出现")
        XCTAssertEqual(LibraryQuery.sourceName(b), "Google")
        XCTAssertTrue(LibraryQuery().isEmpty)
    }

    func testRecallRequestParseMock() throws {
        let items = (0..<10).map { item("灵感 \($0)") }
        XCTAssertEqual(RecallQuestions.batches(items).map(\.count), [8, 2])
        let body = RecallQuestions.requestBody(task: "做 PPT", items: Array(items.prefix(2)))
        XCTAssertTrue(JSONSerialization.isValidJSONObject(body))
        let r0 = try XCTUnwrap((body["questions"] as? [String: Any])?["r_0"] as? [String: Any])
        XCTAssertEqual(r0["type"] as? String, "score")
        XCTAssertEqual((r0["criteria"] as? [String])?.count, 4)
        let reply = """
        {"answers":{"r_0":{"type":"score","score":2.6,"confidence":0.7,"probabilities":{"0":0,"1":0.1,"2":0.2,"3":0.7}},
                    "r_1":{"type":"score","score":0.2}}}
        """
        let s = try RecallQuestions.parse(Data(reply.utf8), items: Array(items.prefix(2)))
        XCTAssertEqual(s[items[0].id], 2.6)
        XCTAssertEqual(s[items[1].id], 0.2)
        XCTAssertEqual(RecallQuestions.levelName(2.6), "正是")
        let m = RecallQuestions.mock(task: "PPT 排版", items: [item("这个 PPT 排版好看"), item("拍照构图")])
        XCTAssertGreaterThan(m.values.max() ?? 0, 1.5)
        XCTAssertEqual(m.values.min(), 0)
    }

    // MARK: K4 / K6

    func testPackGroupsByCategory() throws {
        let a = item("封面配色", url: "https://a.com", tags: ["PPT"], project: "PPT", category: "color")
        let b = item("目录排版", category: "layout")
        let c = item("没分类")
        let text = InspirationPack.text([b, a, c], task: "重做 PPT") { $0.id == a.id ? "/tmp/a.png" : nil }
        XCTAssertTrue(text.hasPrefix("【灵感参考】共 3 条，用于：重做 PPT"))
        let color = try XCTUnwrap(text.range(of: "## 配色（1）")), layout = try XCTUnwrap(text.range(of: "## 排版（1）"))
        XCTAssertLessThan(color.lowerBound, layout.lowerBound, "按类别选项的顺序分组")
        XCTAssertTrue(text.contains("1. 封面配色"))
        XCTAssertTrue(text.contains("   项目：PPT　标签：PPT"))
        XCTAssertFalse(text.contains("类别：配色"), "已经按类别分组，每条里不再重复类别")
        XCTAssertTrue(text.contains("截图：/tmp/a.png"))
        XCTAssertTrue(text.contains("## 其他（1）"))

        let s = tempStore()
        defer { try? FileManager.default.removeItem(at: s.root) }
        let saved = try s.save(a, png: Data([9, 9]))
        let out = try s.exportPack([saved, b], task: nil, to: s.root.appendingPathComponent("_packs"))
        let files = try FileManager.default.contentsOfDirectory(atPath: out.path).sorted()
        XCTAssertEqual(files, ["01-封面配色.png", "灵感参考.md"])
        let md = try String(contentsOf: out.appendingPathComponent("灵感参考.md"), encoding: .utf8)
        XCTAssertTrue(md.contains("截图：01-封面配色.png"))
    }

    func testSourceLinkTextFragment() {
        let it = item("x", url: "https://example.com/post/1", title: "标题", texts: ["标题", "点赞 12", "这一段讲的是奶油风的配色方法…"])
        XCTAssertEqual(SourceLink.snippet(it.texts, excluding: it.windowTitle), "这一段讲的是奶油风的配色方法")
        let u = SourceLink.url(for: it)?.absoluteString ?? ""
        XCTAssertTrue(u.hasPrefix("https://example.com/post/1#:~:text=%E8%BF%99"), u)
        XCTAssertEqual(SourceLink.encode("a-b,c&d"), "a%2Db%2Cc%26d")
        // 已有 #片段、或不是网页：原样打开
        XCTAssertEqual(SourceLink.url(for: item("x", url: "https://a.com/#top", texts: ["一段足够长的文字"]))?.absoluteString, "https://a.com/#top")
        XCTAssertNil(SourceLink.url(for: item("x")))
    }

    // MARK: B2 / B3

    /// 小红书式信息流：一列卡片（封面图 + 标题 + 作者），外加导航和一个推广卡
    private func feedTree() -> (PageNode, CGRect) {
        let vp = CGRect(x: 0, y: 100, width: 1200, height: 800)
        func card(_ x: Double, _ y: Double, _ title: String, _ author: String) -> PageNode {
            PageNode("AXGroup", classes: "note-item", frame: CGRect(x: x, y: y, width: 240, height: 360), children: [
                PageNode("AXLink", classes: "cover", frame: CGRect(x: x, y: y, width: 240, height: 300), children: [
                    PageNode("AXImage", text: "", frame: CGRect(x: x, y: y, width: 240, height: 300)),
                ]),
                PageNode("AXLink", text: title, classes: "title", frame: CGRect(x: x, y: y + 305, width: 240, height: 20)),
                PageNode("AXStaticText", text: author, frame: CGRect(x: x + 30, y: y + 330, width: 80, height: 16)),
                PageNode("AXImage", text: "", frame: CGRect(x: x, y: y + 330, width: 20, height: 20)),   // 头像太小，不算图片
            ])
        }
        let nav = PageNode("AXGroup", frame: CGRect(x: 0, y: 100, width: 160, height: 400), children: [
            PageNode("AXLink", text: "发现", frame: CGRect(x: 10, y: 110, width: 140, height: 40)),
            PageNode("AXLink", text: "发布", frame: CGRect(x: 10, y: 160, width: 140, height: 40)),
            PageNode("AXLink", text: "通知", frame: CGRect(x: 10, y: 210, width: 140, height: 40)),
        ])
        let feed = PageNode("AXGroup", classes: "feeds-container", frame: CGRect(x: 200, y: 100, width: 1000, height: 3000), children: [
            card(200, 120, "奶油风客厅配色 | 米白原木", "小林"),
            card(460, 120, "广告 · 新款沙发限时折扣", "某品牌"),
            card(720, 120, "极简 PPT 排版技巧", "设计课"),
            card(200, 500, "奶油风卧室墙面配色", "阿花"),
            card(460, 2000, "屏幕外的卡片", "不该出现"),
        ])
        return (PageNode("AXWebArea", frame: vp, children: [nav, feed]), vp)
    }

    func testCardFinderFeed() {
        let (root, vp) = feedTree()
        let cards = CardFinder.find(root, viewport: vp)
        XCTAssertEqual(cards.map(\.title), ["奶油风客厅配色 | 米白原木", "广告 · 新款沙发限时折扣", "极简 PPT 排版技巧", "奶油风卧室墙面配色"])
        XCTAssertEqual(cards.map(\.id), ["k1", "k2", "k3", "k4"])
        XCTAssertTrue(cards[0].hasImage)
        XCTAssertEqual(cards[0].text, "奶油风客厅配色 | 米白原木 · 小林")
    }

    func testCardFinderArticlesAndResults() {
        let vp = CGRect(x: 0, y: 0, width: 1000, height: 900)
        let tweets = PageNode("AXWebArea", frame: vp, children: [
            PageNode("AXGroup", frame: CGRect(x: 300, y: 0, width: 600, height: 2000), children: (0..<3).map { i in
                PageNode("AXGroup", frame: CGRect(x: 300, y: Double(i) * 250, width: 600, height: 240), children: [
                    PageNode("AXGroup", subrole: "AXDocumentArticle", frame: CGRect(x: 300, y: Double(i) * 250, width: 600, height: 240), children: [
                        PageNode("AXStaticText", text: "推文 \(i) 讲配色", frame: CGRect(x: 360, y: Double(i) * 250 + 40, width: 400, height: 20)),
                    ]),
                ])
            }),
        ])
        XCTAssertEqual(CardFinder.find(tweets, viewport: vp).map(\.text), ["推文 0 讲配色", "推文 1 讲配色", "推文 2 讲配色"])

        // 搜索结果：没有图片，靠标题
        func result(_ i: Int) -> PageNode {
            let y = 100 + Double(i) * 150
            let heading = PageNode("AXHeading", text: "结果标题 \(i)", frame: CGRect(x: 100, y: y, width: 400, height: 30))
            let link = PageNode("AXLink", frame: CGRect(x: 100, y: y, width: 400, height: 30), children: [heading])
            let snippet = PageNode("AXStaticText", text: "摘要文字摘要文字 \(i)", frame: CGRect(x: 100, y: y + 40, width: 600, height: 40))
            return PageNode("AXGroup", frame: CGRect(x: 100, y: y, width: 650, height: 130), children: [link, snippet])
        }
        let list = PageNode("AXGroup", frame: CGRect(x: 100, y: 100, width: 650, height: 600), children: [result(0), result(1), result(2)])
        let results = PageNode("AXWebArea", frame: vp, children: [list])
        let r: [PageCard] = CardFinder.find(results, viewport: vp)
        XCTAssertEqual(r.map(\.title), ["结果标题 0", "结果标题 1", "结果标题 2"])
        XCTAssertFalse(r[0].hasImage)
    }

    func testCardQuestionsAndNext() throws {
        let (root, vp) = feedTree()
        let cards = CardFinder.find(root, viewport: vp)
        let body = CardQuestions.requestBody(goal: "奶油风配色", context: ScreenContext(appName: "Chrome", windowTitle: "小红书"), cards: cards)
        XCTAssertTrue(JSONSerialization.isValidJSONObject(body))
        let qs = try XCTUnwrap(body["questions"] as? [String: Any])
        XCTAssertEqual(qs.count, cards.count * 2)
        XCTAssertEqual((qs["rel_0"] as? [String: Any])?["type"] as? String, "score")
        XCTAssertEqual((qs["ad_3"] as? [String: Any])?["type"] as? String, "noul")
        let reply = """
        {"answers":{"rel_0":{"type":"score","score":2.8},"ad_0":{"type":"noul","noul":0.02},
                    "rel_1":{"type":"score","score":1.9},"ad_1":{"type":"noul","noul":0.95},
                    "rel_2":{"type":"score","score":0.1},"ad_2":{"type":"noul","noul":0.01},
                    "rel_3":{"type":"score","score":2.2},"ad_3":{"type":"noul","noul":0.03}}}
        """
        let j = try CardQuestions.parse(Data(reply.utf8), count: cards.count)
        XCTAssertTrue(j[0]!.relevant)
        XCTAssertTrue(j[1]!.isAd); XCTAssertFalse(j[1]!.relevant); XCTAssertEqual(j[1]!.label, "推广")
        XCTAssertTrue(j[2]!.dim)
        var byId: [String: CardJudgement] = [:]
        for (i, c) in cards.enumerated() { byId[c.id] = j[i] }
        // 指针在第一张卡上：下一条相关的跳过推广和无关的，到下一行的 k4
        let p = CGPoint(x: cards[0].frame.midX, y: cards[0].frame.midY)
        XCTAssertEqual(CardQuestions.next(after: p, cards: cards, judgements: byId)?.id, "k4")
        // 指针在 k4 上：后面没有了
        XCTAssertNil(CardQuestions.next(after: CGPoint(x: cards[3].frame.midX, y: cards[3].frame.midY), cards: cards, judgements: byId))
        // 指针在卡片上方的空白：第一张相关的
        XCTAssertEqual(CardQuestions.next(after: CGPoint(x: 10, y: 105), cards: cards, judgements: byId)?.id, "k1")

        let m = CardQuestions.mock(goal: "奶油风配色", cards: cards)
        XCTAssertTrue(m[0]!.relevant)
        XCTAssertTrue(m[1]!.isAd)
        XCTAssertFalse(m[2]!.relevant)
    }

    // MARK: B7

    func testCloseKindWords() {
        XCTAssertEqual(PopupFinder.closeKind(text: "关闭", classes: ""), .close)
        XCTAssertEqual(PopupFinder.closeKind(text: " × ", classes: ""), .close)
        XCTAssertEqual(PopupFinder.closeKind(text: "", classes: "icon-btn close-button"), .close)
        XCTAssertEqual(PopupFinder.closeKind(text: "暂不登录", classes: ""), .decline)
        XCTAssertEqual(PopupFinder.closeKind(text: "Not now", classes: ""), .decline)
        XCTAssertEqual(PopupFinder.closeKind(text: "取消", classes: ""), .cancel)
        for bad in ["取消关注", "登录", "确定", "关闭评论", "立即购买", "close account and delete"] {
            XCTAssertNil(PopupFinder.closeKind(text: bad, classes: "close"), bad)
        }
        XCTAssertNil(PopupFinder.closeKind(text: "", classes: "closed-caption-toggle"), "closed 不是 close")
    }

    func testPopupFinder() {
        let vp = CGRect(x: 0, y: 0, width: 1200, height: 800)
        let dialog = PageNode("AXGroup", subrole: "AXApplicationDialog", frame: CGRect(x: 400, y: 200, width: 400, height: 300), children: [
            PageNode("AXStaticText", text: "登录后查看更多精彩内容", frame: CGRect(x: 420, y: 260, width: 300, height: 20)),
            PageNode("AXButton", text: "登录", frame: CGRect(x: 420, y: 420, width: 160, height: 40)),
            PageNode("AXLink", text: "暂不登录", frame: CGRect(x: 600, y: 420, width: 120, height: 40)),
            PageNode("AXButton", text: "", frame: CGRect(x: 770, y: 205, width: 24, height: 24)),   // 右上角无文字按钮
        ])
        let page = PageNode("AXWebArea", frame: vp, children: [
            PageNode("AXButton", text: "关闭", classes: "sidebar-close", frame: CGRect(x: 10, y: 10, width: 40, height: 20)),   // 弹窗外的，不要
            PageNode("AXButton", text: "取消关注", frame: CGRect(x: 900, y: 100, width: 80, height: 30)),
            dialog,
        ])
        let s = PopupFinder.find(page, viewport: vp)
        XCTAssertEqual(s.dialogs.count, 1)
        XCTAssertEqual(s.candidates.map(\.kind), [.decline, .positional])
        XCTAssertTrue(s.candidates.allSatisfy(\.inDialog))
        XCTAssertEqual(s.dialogText, "登录后查看更多精彩内容")
        XCTAssertEqual(CloseQuestions.mock(s), "x1")
        let body = CloseQuestions.requestBody(s, context: ScreenContext(appName: "Chrome"))
        XCTAssertTrue(JSONSerialization.isValidJSONObject(body))
        let crit = ((body["questions"] as? [String: Any])?["target"] as? [String: Any])?["criteria"] as? [String: String]
        XCTAssertEqual(Set(crit?.keys ?? [:].keys), ["x1", "x2", "none"])
        XCTAssertEqual(try CloseQuestions.parse(Data(#"{"answers":{"target":{"type":"choice","choice":"x2","confidence":0.6}}}"#.utf8)).choice, "x2")

        // 实测：id 叫 modal-root 的大外层包着 role=dialog 的框，用里面那个（右上角规则看的是它）
        let wrapped = PageNode("AXWebArea", frame: vp, children: [
            PageNode("AXGroup", classes: "modal-root", frame: CGRect(x: 0, y: 0, width: 1180, height: 780), children: [dialog]),
        ])
        let w = PopupFinder.find(wrapped, viewport: vp)
        XCTAssertEqual(w.dialogs, [CGRect(x: 400, y: 200, width: 400, height: 300)])
        XCTAssertEqual(w.candidates.map(\.kind), [.decline, .positional])

        // 没有弹窗：只收明确的小“关闭”按钮
        let plain = PageNode("AXWebArea", frame: vp, children: [
            PageNode("AXButton", text: "×", frame: CGRect(x: 1100, y: 20, width: 30, height: 30)),
            PageNode("AXButton", text: "暂不登录", frame: CGRect(x: 900, y: 20, width: 80, height: 30)),
        ])
        XCTAssertEqual(PopupFinder.find(plain, viewport: vp).candidates.map(\.label), ["×"])
    }
}
