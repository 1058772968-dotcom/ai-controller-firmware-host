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
