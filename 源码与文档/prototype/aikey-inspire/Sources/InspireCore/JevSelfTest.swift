import Foundation
import CoreGraphics

/// 用人造数据把整理（J6+J7）、召回（J8）、卡片相关度（J2）、关闭弹窗（J9）四种请求各发一次给 Jev，
/// 看请求格式对不对、延迟和输入 token。不含真实屏幕和灵感库内容。
/// 探针 `inspire-probe demo2` 和 App 启动参数 `--jev-selftest` 都用它（App 能直接读自己钥匙串里的 Key）。
public enum JevSelfTest {
    public static func run(key: String, output: @escaping (String) -> Void, done: @escaping () -> Void) {
        let client = JevClient(key: key)
        var steps: [(String, [String: Any], (Data) throws -> String)] = []
        func call(_ name: String, _ body: [String: Any], _ check: @escaping (Data) throws -> String) { steps.append((name, body, check)) }
        func mk(_ intent: String, _ title: String, _ url: String, _ texts: [String], tags: [String]? = nil, project: String? = nil, cat: String? = nil) -> InspirationItem {
            var it = InspirationItem(intent: intent, context: ScreenContext(appName: "Google Chrome", windowTitle: title, url: url), texts: texts, rect: nil)
            it.tags = tags; it.project = project; it.category = cat
            return it
        }
        // J6 + J7：新条目和一条几乎一样的旧条目
        let new = mk("这个排版好看，放进 PPT 参考", "极简风 PPT 排版：封面这样做更高级 - 小红书", "https://www.xiaohongshu.com/explore/demo1",
                     ["极简风 PPT 排版", "封面留白 + 大标题"])
        let old = mk("PPT 封面排版参考", "极简风 PPT 排版：封面这样做更高级 - 小红书", "https://www.xiaohongshu.com/explore/demo1?xsec_token=x",
                     ["极简风 PPT 排版", "封面留白 + 大标题"], tags: ["PPT"])
        let projects = ["AI 控制器宣传 PPT", "官网改版"]
        let vocab = ["PPT", "奶油风", "摄影"]
        call("J6+J7 整理（类别、项目、3 个标签、1 个疑似重复）",
             OrganizeQuestions.requestBody(item: new, projects: projects, vocabulary: vocab, similar: [old])) { d in
            let r = try OrganizeQuestions.parse(d, projects: projects, vocabulary: vocab, similar: [old])
            let tp = r.tagProbabilities.sorted { $0.key < $1.key }.map { String(format: "%@ %.2f", $0.key, $0.value) }.joined(separator: " ")
            return "类别 \(r.category) · 项目 \(r.project ?? "无")（\(String(format: "%.2f", r.projectProbability ?? -1))）· 标签 \(r.tags)（\(tp)）· 重复 \(r.duplicateOf != nil)（\(String(format: "%.2f", r.duplicateProbability ?? -1))）"
        }
        // J8：一个任务、8 条灵感
        let lib = [
            mk("这个排版好看，放进 PPT 参考", "极简风 PPT 排版", "https://www.xiaohongshu.com/a", ["封面留白 + 大标题"], tags: ["PPT"], cat: "layout"),
            mk("奶油风配色，客厅可以用", "奶油风客厅配色", "https://www.xiaohongshu.com/b", ["米白 + 原木"], cat: "color"),
            mk("科技感配色，深蓝 + 荧光绿，适合产品发布", "科技发布会配色", "https://www.xiaohongshu.com/c", ["深蓝背景"], cat: "color"),
            mk("露营装备清单", "周末露营", "https://www.xiaohongshu.com/d", ["帐篷", "天幕"], cat: "other"),
            mk("手持设备的握持姿势拍法", "产品摄影", "https://www.xiaohongshu.com/e", ["45 度侧光"], cat: "photo"),
            mk("数据页的图表排版，信息层级清楚", "PPT 数据页", "https://www.google.com/f", ["一页一个结论"], tags: ["PPT"], cat: "layout"),
            mk("发布会口号：让电脑听懂你的手", "文案合集", "https://x.com/g", ["slogan"], cat: "copy"),
            mk("Python 自动化办公", "教程", "https://www.bilibili.com/h", ["pandas"], cat: "other"),
        ]
        call("J8 召回（8 条，一批）", RecallQuestions.requestBody(task: "根据我的参考重新生成 AI 控制器发布会 PPT", items: lib)) { d in
            let s = try RecallQuestions.parse(d, items: lib)
            return lib.map { String(format: "%.1f %@", s[$0.id] ?? -1, String($0.intent.prefix(12))) }.joined(separator: " | ")
        }
        // J2：目标 + 6 张卡片
        let cards = ["奶油风客厅配色｜米白 + 原木，越看越舒服 · 小林的家", "极简风 PPT 排版：封面这样做更高级 · 设计课代表",
                     "广告 · 新款云朵沙发限时 5 折 · 某某家居旗舰店 · 广告", "奶油风卧室墙面怎么选色？三套方案对比 · 阿花装修记",
                     "周末露营装备清单 · 户外老王", "奶油风小户型厨房改造前后对比 · 住进小房子"].enumerated().map { i, t in
            PageCard(id: "k\(i + 1)", frame: .zero, text: t, title: t, hasImage: true, el: nil)
        }
        call("J2 卡片相关度（6 张 × Score + 推广 Noul）",
             CardQuestions.requestBody(goal: "奶油风配色", context: ScreenContext(appName: "Google Chrome", windowTitle: "奶油风 - 小红书搜索"), cards: cards)) { d in
            let j = try CardQuestions.parse(d, count: cards.count)
            return cards.indices.map { i in String(format: "%@ %.1f 推广%.2f", j[i]?.label ?? "?", j[i]?.score ?? -1, j[i]?.ad ?? -1) }.joined(separator: " | ")
        }
        // J9：登录墙
        let pop = PopupScan(dialogs: [CGRect(x: 400, y: 160, width: 400, height: 240)], dialogText: "登录后查看更多精彩内容 扫码或手机号登录",
                            candidates: [CloseCandidate(id: "x1", role: "AXLink", label: "暂不登录", classes: "later", x: 600, y: 330, w: 80, h: 40, inDialog: true, kind: .decline),
                                         CloseCandidate(id: "x2", role: "AXButton", label: "", classes: "close-button", x: 760, y: 172, w: 28, h: 28, inDialog: true, kind: .close),
                                         CloseCandidate(id: "x3", role: "AXButton", label: "取消", classes: "", x: 420, y: 330, w: 80, h: 40, inDialog: true, kind: .cancel)],
                            elements: [:])
        call("J9 关闭弹窗（3 个候选）", CloseQuestions.requestBody(pop, context: ScreenContext(appName: "Google Chrome", windowTitle: "小红书"))) { d in
            let a = try CloseQuestions.parse(d)
            return "选 \(a.choice) 置信度 \(String(format: "%.2f", a.confidence ?? -1))"
        }

        func next(_ i: Int) {
            guard i < steps.count else { done(); return }
            let (name, body, check) = steps[i]
            let t0 = Date()
            client.systemOne(body) { r in
                let ms = Date().timeIntervalSince(t0) * 1000
                switch r {
                case .success(let d):
                    let usage = ((try? JSONSerialization.jsonObject(with: d)) as? [String: Any])?["usage"] as? [String: Any]
                    let tok = (usage?["input_tokens"] as? NSNumber)?.intValue ?? -1
                    do { output(String(format: "✓ %@ · %.0f ms · 输入 %d tok\n    %@", name, ms, tok, try check(d))) }
                    catch { output("✗ \(name)：解析失败 \(error) \(String(data: d, encoding: .utf8)?.prefix(300) ?? "")") }
                case .failure(let e): output("✗ \(name)：\(e)（\(Int(ms)) ms）")
                }
                next(i + 1)
            }
        }
        next(0)
    }
}
