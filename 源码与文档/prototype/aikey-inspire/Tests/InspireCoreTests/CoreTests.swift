import XCTest
import CoreGraphics
@testable import InspireCore

final class CoreTests: XCTestCase {
    private func cand(_ id: String, _ label: String, x: Double, y: Double, w: Double = 60, h: Double = 24, from p: CGPoint) -> CandidateInfo {
        let f = CGRect(x: x, y: y, width: w, height: h)
        return CandidateInfo(id: id, role: "AXButton", kind: "button", label: label, frame: f,
                             distance: Geometry.distance(p, f), direction: Geometry.direction(from: p, to: f))
    }

    private func snapshot() -> ClickSnapshot {
        let p = CGPoint(x: 100, y: 100)
        return ClickSnapshot(
            context: ScreenContext(appName: "Google Chrome", bundleId: "com.google.Chrome", windowTitle: "小红书", url: "https://www.xiaohongshu.com/explore"),
            pointer: PointerMotion(x: 100, y: 100, dx: 120, dy: 0, speed: 240, text: "moved right about 120 px in the last 0.5 s, then stopped"),
            candidates: [cand("c1", "收藏", x: 90, y: 90, from: p), cand("c2", "评论", x: 180, y: 90, from: p), cand("c3", "分享", x: 20, y: 90, w: 40, from: p)],
            userGoal: "收藏这篇笔记")
    }

    /// 请求体符合 POST /v1/systemone：model/state/questions；问题按 id；choice 的 criteria 含每个候选和 none
    func testRequestBodyShape() throws {
        let body = ClickQuestions.requestBody(snapshot())
        XCTAssertEqual(body["model"] as? String, "jev-latest")
        let state = try XCTUnwrap(body["state"] as? [String: Any])
        XCTAssertEqual(state["user_goal"] as? String, "收藏这篇笔记")
        XCTAssertEqual(state["page_url"] as? String, "https://www.xiaohongshu.com/explore")
        let cands = try XCTUnwrap(state["candidates"] as? [[String: Any]])
        XCTAssertEqual(cands.map { $0["id"] as? String }, ["c1", "c2", "c3"])
        XCTAssertEqual(cands[0]["distance_px"] as? Int, 0)
        XCTAssertEqual(cands[0]["direction_from_pointer"] as? String, "under_pointer")
        let qs = try XCTUnwrap(body["questions"] as? [String: Any])
        let target = try XCTUnwrap(qs["target"] as? [String: Any])
        XCTAssertEqual(target["type"] as? String, "choice")
        let crit = try XCTUnwrap(target["criteria"] as? [String: String])
        XCTAssertEqual(Set(crit.keys), ["c1", "c2", "c3", "none"])
        XCTAssertEqual(crit["c1"], "button “收藏”")
        XCTAssertEqual((qs["about_to_click"] as? [String: Any])?["type"] as? String, "noul")
        // 能被编码成 JSON（没有 NaN、不支持的类型）
        XCTAssertTrue(JSONSerialization.isValidJSONObject(body))
        // 指令里引用的路径都在 state 里
        let instr = try XCTUnwrap(target["instructions"] as? String)
        for path in ["candidates", "pointer", "user_goal", "window_title"] {
            XCTAssertTrue(instr.contains("`\(path)"), path)
        }
    }

    /// 解析官方文档格式的回复
    func testParseResponse() throws {
        let json = """
        {"model":"jev-1.13.0","answers":{
          "target":{"type":"choice","choice":"c1","confidence":0.42,"probabilities":{"c1":0.61,"c2":0.35,"c3":0.0,"none":0.04}},
          "about_to_click":{"type":"noul","noul":0.83}},
         "usage":{"input_tokens":328,"output_tokens":34}}
        """
        let a = try ClickQuestions.parse(Data(json.utf8))
        XCTAssertEqual(a.choice, "c1")
        XCTAssertEqual(a.confidence, 0.42)
        XCTAssertEqual(a.probabilities["c2"], 0.35)
        XCTAssertEqual(a.aboutToClick, 0.83)
        XCTAssertEqual(a.model, "jev-1.13.0")
        XCTAssertEqual(a.inputTokens, 328)
        XCTAssertThrowsError(try ClickQuestions.parse(Data(#"{"answers":{}}"#.utf8)))
    }

    /// 模拟预判：概率和为 1，指针正下方的元素胜出
    func testMockPrefersUnderPointer() {
        let a = ClickQuestions.mock(snapshot())
        XCTAssertEqual(a.choice, "c1")
        XCTAssertEqual(a.probabilities.values.reduce(0, +), 1, accuracy: 1e-9)
        XCTAssertEqual(Set(a.probabilities.keys), ["c1", "c2", "c3", "none"])
        XCTAssertEqual(a.model, "mock")
    }

    /// 飞书标题里的零宽字符要去掉，中文和普通空格保留
    func testCleanStripsInvisibleFormatChars() {
        let raw = "\u{200C}\u{2062}\u{200B}光标交互\u{FEFF} 脚本\u{2064}\u{200D}"
        XCTAssertEqual(AX.clean(raw), "光标交互 脚本")
        XCTAssertEqual(AX.clean("\u{200B}\u{2060}"), "")
        XCTAssertEqual(AX.clean("Google 搜索"), "Google 搜索")
    }

    // MARK: F1 快速搜索

    func testSearchPlanDestinations() {
        func plan(_ t: String, _ url: String? = nil) -> SearchPlan { QuickSearch.plan(input: t, currentURL: url) }
        XCTAssertEqual(plan("小红书 奶油风客厅").destination.name, "小红书")
        XCTAssertEqual(plan("小红书 奶油风客厅").query, "奶油风客厅")
        XCTAssertEqual(plan("在小红书上搜奶油风").query, "奶油风")
        XCTAssertEqual(plan("帮我搜一下B站上搜机械键盘").destination.name, "B 站")
        XCTAssertEqual(plan("帮我搜一下B站上搜机械键盘").query, "机械键盘")
        XCTAssertEqual(plan("x: claude").destination.name, "推特")
        // 纯英文前缀后面必须有空格或冒号：xiaomi 不是推特
        XCTAssertEqual(plan("xiaomi 14").destination.name, "Google")
        XCTAssertEqual(plan("xiaomi 14").query, "xiaomi 14")
        // 没点名：按当前网站
        let cur = plan("机械键盘", "https://www.bilibili.com/video/BV1xx")
        XCTAssertEqual(cur.destination.name, "B 站")
        XCTAssertTrue(cur.reason.contains("当前网站"))
        XCTAssertEqual(plan("机械键盘", "https://www.xiaohongshu.com/explore/abc").destination.name, "小红书")
        XCTAssertEqual(plan("机械键盘", "https://example.com/").destination.name, "Google")
        XCTAssertEqual(plan("机械键盘", nil).destination.name, "Google")
        // 页内、灵感库
        XCTAssertEqual(plan("页内 价格").destination, .inPage)
        XCTAssertEqual(plan("页内 价格").query, "价格")
        XCTAssertEqual(plan("灵感库 配色").destination, .library)
        // 单个“在”“搜”不当口头语去掉
        XCTAssertEqual(plan("在家健身").query, "在家健身")
        XCTAssertEqual(plan("搜狗输入法").query, "搜狗输入法")
    }

    func testSearchURLEncoding() {
        let p = QuickSearch.plan(input: "小红书 a&b=c #配色", currentURL: nil)
        let u = p.url!.absoluteString
        XCTAssertTrue(u.hasPrefix("https://www.xiaohongshu.com/search_result?keyword="), u)
        XCTAssertFalse(u.contains("&b="), "& 必须编码：\(u)")
        XCTAssertTrue(u.contains("%26") && u.contains("%3D") && u.contains("%23"), u)
        XCTAssertEqual(QuickSearch.url(QuickSearch.defaultSite, "a b")!.absoluteString, "https://www.google.com/search?q=a%20b")
    }

    // MARK: F3 快捷互动

    func testActionLabelMatching() {
        XCTAssertTrue(ActionLabels.matches(.like, text: "点赞 1.2万", classes: ""))
        XCTAssertTrue(ActionLabels.matches(.like, text: "1.2万", classes: "like-wrapper"))          // 只有数字，靠 class
        XCTAssertTrue(ActionLabels.matches(.collect, text: "", classes: "collect-wrapper"))
        XCTAssertTrue(ActionLabels.matches(.coin, text: "投币", classes: "video-coin"))
        XCTAssertTrue(ActionLabels.matches(.follow, text: "+ 关注", classes: ""))
        XCTAssertFalse(ActionLabels.matches(.follow, text: "关注者 128", classes: ""))
        XCTAssertFalse(ActionLabels.matches(.like, text: "猜你喜欢", classes: ""))
        // 太长的文字多半是正文，不当按钮
        XCTAssertFalse(ActionLabels.matches(.like, text: String(repeating: "这是一段很长的正文，里面提到了赞", count: 3), classes: ""))
    }

    func testActionAlreadyDone() {
        XCTAssertEqual(ActionLabels.alreadyDone(.like, text: "取消点赞", classes: "", selected: nil, valueNumber: nil), true)
        XCTAssertEqual(ActionLabels.alreadyDone(.follow, text: "Following", classes: "", selected: nil, valueNumber: nil), true)
        XCTAssertEqual(ActionLabels.alreadyDone(.like, text: "1.2万", classes: "video-like on", selected: nil, valueNumber: nil), true)
        XCTAssertEqual(ActionLabels.alreadyDone(.like, text: "1.2万", classes: "like-wrapper like-active", selected: nil, valueNumber: nil), true)
        XCTAssertEqual(ActionLabels.alreadyDone(.collect, text: "收藏", classes: "", selected: true, valueNumber: nil), true)
        XCTAssertNil(ActionLabels.alreadyDone(.like, text: "点赞 32", classes: "like-wrapper", selected: nil, valueNumber: nil))
        // “button” 里含 on，但不是独立的 on 词
        XCTAssertNil(ActionLabels.alreadyDone(.like, text: "赞", classes: "like-button", selected: nil, valueNumber: nil))
    }

    func testActionQuestionAndMock() throws {
        func c(_ id: String, _ label: String, _ d: Double, comment: Bool) -> ActionCandidate {
            ActionCandidate(id: id, role: "AXButton", label: label, classes: "", x: 0, y: 0, w: 40, h: 20,
                            distance: d, direction: "down", inComment: comment, alreadyDone: nil)
        }
        let cands = [c("b1", "赞 3", 10, comment: true), c("b2", "点赞 1.2万", 80, comment: false)]
        XCTAssertEqual(ActionQuestions.mock(cands), "b2", "评论区外的优先")
        XCTAssertEqual(ActionQuestions.mock([c("b1", "赞", 5, comment: true)]), "b1")
        XCTAssertEqual(ActionQuestions.mock([]), "none")
        let body = ActionQuestions.requestBody(.like, context: ScreenContext(appName: "Chrome", windowTitle: "笔记"), pointer: .zero, candidates: cands)
        XCTAssertTrue(JSONSerialization.isValidJSONObject(body))
        let q = try XCTUnwrap((body["questions"] as? [String: Any])?["target"] as? [String: Any])
        XCTAssertEqual(Set(((q["criteria"] as? [String: String]) ?? [:]).keys), ["b1", "b2", "none"])
        let st = try XCTUnwrap(body["state"] as? [String: Any])
        XCTAssertEqual((st["candidates"] as? [[String: Any]])?.first?["in_comment_area"] as? Bool, true)
        let r = try ActionQuestions.parse(Data(#"{"answers":{"target":{"type":"choice","choice":"b2","confidence":0.9,"probabilities":{"b1":0.05,"b2":0.93,"none":0.02}}}}"#.utf8))
        XCTAssertEqual(r.choice, "b2")
        XCTAssertEqual(r.probabilities["b2"], 0.93)
    }

    func testFlipDirectionWords() {
        XCTAssertTrue(ImageNav.means(.next, text: "", classes: "arrow-controller right"))
        XCTAssertTrue(ImageNav.means(.prev, text: "", classes: "arrow-controller left"))
        XCTAssertFalse(ImageNav.means(.prev, text: "", classes: "arrow-controller right"))
        XCTAssertTrue(ImageNav.means(.next, text: "下一张", classes: ""))
        XCTAssertTrue(ImageNav.means(.next, text: "", classes: "swiper-button-next"))
        XCTAssertFalse(ImageNav.means(.next, text: "", classes: "swiper-button-prev"))
        XCTAssertFalse(ImageNav.means(.next, text: "", classes: "float-right"), "只有 right 没有导航类词，不算")
    }

    func testDirection() {
        XCTAssertEqual(Geometry.direction(dx: 10, dy: 0), "right")
        XCTAssertEqual(Geometry.direction(dx: 0, dy: 10), "down")      // AX 坐标 y 向下
        XCTAssertEqual(Geometry.direction(dx: -10, dy: -10), "upper-left")
        XCTAssertEqual(Geometry.distance(CGPoint(x: 0, y: 0), CGRect(x: 3, y: 4, width: 10, height: 10)), 5, accuracy: 1e-9)
    }

    /// 停留检测：移动后停住触发一次；一直不动、原地小抖动都不再触发；再移动后可再次触发
    func testDwellFiresOncePerStop() {
        var d = DwellDetector(dwellSeconds: 0.5, stillRadius: 6, armDistance: 24)
        var t = 0.0, fires = 0
        func step(_ x: CGFloat, _ y: CGFloat) { if d.feed(CGPoint(x: x, y: y), at: t) { fires += 1 }; t += 0.05 }
        for i in 0..<10 { step(CGFloat(i * 10), 0) }          // 向右移动 90 px
        for _ in 0..<20 { step(90, 0) }                       // 停 1 s
        XCTAssertEqual(fires, 1)
        for i in 0..<60 { step(90 + CGFloat(i % 2) * 3, 0) }  // 原地 ±3 px 抖动 3 s（模拟陀螺仪）
        XCTAssertEqual(fires, 1, "静止抖动不应重新触发")
        let m = d.motion()
        XCTAssertTrue(m.text.contains("barely") || m.text.contains("moved"))
        for i in 0..<10 { step(90, CGFloat(i * 10)) }         // 向下移动
        for _ in 0..<20 { step(90, 90) }
        XCTAssertEqual(fires, 2)
        XCTAssertEqual(d.motion().text.contains("down"), true, d.motion().text)
    }

    func testCategoryRequestAndMock() throws {
        let body = CategoryQuestion.requestBody(intent: "这个配色想用在卡片上", context: ScreenContext(appName: "Chrome", windowTitle: "小红书"), texts: ["奶油色"])
        let q = try XCTUnwrap((body["questions"] as? [String: Any])?["category"] as? [String: Any])
        XCTAssertEqual((q["criteria"] as? [String: String])?.count, CategoryQuestion.options.count)
        XCTAssertTrue(JSONSerialization.isValidJSONObject(body))
        XCTAssertEqual(CategoryQuestion.mock(intent: "这个配色想用在卡片上"), "color")
        XCTAssertEqual(CategoryQuestion.mock(intent: "随便看看"), "other")
    }

    func testLibraryRoundTripAndTrash() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("inspire-test-\(UUID().uuidString)")
        let store = LibraryStore(root: dir)
        store.useTrash = false
        let item = InspirationItem(intent: "配色", context: ScreenContext(appName: "Chrome", url: "https://example.com"),
                                   texts: ["a"], rect: CGRect(x: 1, y: 2, width: 3, height: 4))
        let png = Data([0x89, 0x50, 0x4E, 0x47])
        let saved = try store.save(item, png: png)
        XCTAssertEqual(store.all().count, 1)
        XCTAssertEqual(try Data(contentsOf: XCTUnwrap(store.imageURL(saved))), png)
        var u = saved
        u.category = "color"
        try store.update(u)
        XCTAssertEqual(store.all().first?.category, "color")
        XCTAssertTrue(saved.promptText(imagePath: "/x.png").contains("链接：https://example.com"))
        try store.delete(id: saved.id)
        XCTAssertEqual(store.all().count, 0)
        try? FileManager.default.removeItem(at: dir)
    }
}
