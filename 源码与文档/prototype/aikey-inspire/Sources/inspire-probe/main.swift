// 命令行探针：在终端里验证候选枚举、模拟预判、请求体和截图，不需要装 App。
// 用法：
//   inspire-probe scan [x y]          指针（或给定点）附近的可点击元素 + 模拟预判 + Jev 请求体
//   inspire-probe watch [秒]          跟随指针，每次停留触发一次扫描（默认 20 秒）
//   inspire-probe capture x y w h out.png   截一块屏幕
//   inspire-probe texts x y w h       区域内看得到的文字
//   inspire-probe jev [x y]           真发一次 Jev 请求（需要钥匙串或环境变量里有 Key）
//   inspire-probe demo                四个人造场景发给 Jev，看格式、延迟和大致行为
import AppKit
import InspireCore

let args = Array(CommandLine.arguments.dropFirst())
let cmd = args.first ?? "scan"

func point(_ a: ArraySlice<String>) -> CGPoint {
    if a.count >= 2, let x = Double(a[a.startIndex]), let y = Double(a[a.startIndex + 1]) { return CGPoint(x: x, y: y) }
    return ScreenGeometry.mouseAX()
}

func pretty(_ o: Any) -> String {
    guard let d = try? JSONSerialization.data(withJSONObject: o, options: [.prettyPrinted, .sortedKeys]) else { return "\(o)" }
    return String(data: d, encoding: .utf8) ?? ""
}

func printScan(_ s: AXProbe.Scan, at p: CGPoint, motion: PointerMotion? = nil) -> ClickSnapshot {
    print("位置 (\(Int(p.x)), \(Int(p.y)))  采样 \(s.samples) 点  耗时 \(String(format: "%.1f", s.elapsedMs)) ms")
    print("上下文：\(s.context.summary)")
    for c in s.candidates {
        print(String(format: "  %@  %-18@ %6.1f px  %-12@ %@", c.id, c.kind as NSString, c.distance, c.direction as NSString, c.label))
    }
    let m = motion ?? PointerMotion(x: Double(p.x), y: Double(p.y), dx: 0, dy: 0, speed: 0, text: "barely moved in the last 0.5 s before stopping")
    return ClickSnapshot(context: s.context, pointer: m, candidates: s.candidates, userGoal: ProcessInfo.processInfo.environment["GOAL"])
}

guard AX.trusted else {
    print("当前进程没有辅助功能权限（AXIsProcessTrusted = false）。在 系统设置 → 隐私与安全性 → 辅助功能 里给运行它的终端打勾。")
    exit(2)
}

switch cmd {
case "scan":
    let p = point(args.dropFirst())
    let s = AXProbe().scan(at: p)
    let snap = printScan(s, at: p)
    let m = ClickQuestions.mock(snap)
    print("模拟预判：\(m.choice)  置信度 \(m.confidence ?? 0)")
    if let out = ProcessInfo.processInfo.environment["CAPTURE_C1"], let c1 = s.candidates.first {
        // 坐标自检：截 c1 自己的边框，画面里应该正好是这个元素
        let sem = DispatchSemaphore(value: 0)
        ScreenCapture.png(rectAX: c1.frame.insetBy(dx: -4, dy: -4)) { d, via, err in
            if let d { try? d.write(to: URL(fileURLWithPath: out)); print("c1 边框截图（\(via)）→ \(out)：应当是 \(c1.kind) “\(c1.label)” \(c1.frame)") }
            else { print("截图失败：\(err ?? "")") }
            sem.signal()
        }
        sem.wait()
    }
    if ProcessInfo.processInfo.environment["NO_BODY"] == nil {
        print("Jev 请求体：")
        print(pretty(ClickQuestions.requestBody(snap)))
    }

case "watch":
    let secs = Double(args.dropFirst().first ?? "20") ?? 20
    var dwell = DwellDetector()
    let probe = AXProbe()
    let t0 = Date()
    print("跟随指针 \(Int(secs)) 秒：移动后停住约 0.55 秒触发一次")
    while Date().timeIntervalSince(t0) < secs {
        let p = ScreenGeometry.mouseAX()
        if dwell.feed(p, at: Date().timeIntervalSince1970) {
            let mo = dwell.motion()
            print("\n— 触发：\(mo.text)")
            let snap = printScan(probe.scan(at: p), at: p, motion: mo)
            let m = ClickQuestions.mock(snap)
            let label = snap.candidates.first { $0.id == m.choice }?.label ?? "无"
            print("模拟预判：\(m.choice) \(label)  置信度 \(m.confidence ?? 0)")
        }
        Thread.sleep(forTimeInterval: 0.05)
    }

case "capture":
    guard args.count >= 6, let x = Double(args[1]), let y = Double(args[2]), let w = Double(args[3]), let h = Double(args[4]) else {
        print("用法：inspire-probe capture x y w h out.png"); exit(1)
    }
    let sem = DispatchSemaphore(value: 0)
    ScreenCapture.png(rectAX: CGRect(x: x, y: y, width: w, height: h)) { data, via, err in
        if let data {
            try? data.write(to: URL(fileURLWithPath: args[5]))
            let rep = NSBitmapImageRep(data: data)
            print("截图成功（\(via)）：\(rep?.pixelsWide ?? 0)×\(rep?.pixelsHigh ?? 0) 像素，\(data.count) 字节 → \(args[5])")
        } else {
            print("截图失败（\(via)）：\(err ?? "未知")")
        }
        sem.signal()
    }
    sem.wait()

case "texts":
    guard args.count >= 5, let x = Double(args[1]), let y = Double(args[2]), let w = Double(args[3]), let h = Double(args[4]) else {
        print("用法：inspire-probe texts x y w h"); exit(1)
    }
    let r = CGRect(x: x, y: y, width: w, height: h)
    let probe = AXProbe()
    print("上下文：\(probe.context(at: CGPoint(x: r.midX, y: r.midY)).summary)")
    for t in probe.texts(in: r) { print("  · \(t)") }

case "jev":
    guard let (key, src) = KeyStore.load() else { print("没有 Key：先在 App 里保存，或设置 TYPESAFE_API_KEY"); exit(3) }
    print("Key 来源：\(src)")
    let p = point(args.dropFirst())
    let snap = printScan(AXProbe().scan(at: p), at: p)
    let sem = DispatchSemaphore(value: 0)
    let t0 = Date()
    JevClient(key: key).systemOne(ClickQuestions.requestBody(snap)) { r in
        let ms = Date().timeIntervalSince(t0) * 1000
        switch r {
        case .success(let d):
            do {
                let a = try ClickQuestions.parse(d)
                print(String(format: "Jev（%.0f ms，%@）：%@ 置信度 %.2f，about_to_click %.2f", ms, a.model ?? "?", a.choice, a.confidence ?? -1, a.aboutToClick ?? -1))
                for (k, v) in a.probabilities.sorted(by: { $0.value > $1.value }) { print(String(format: "  %@ %.3f", k, v)) }
            } catch { print("解析失败：\(error)") }
        case .failure(let e): print("请求失败（\(Int(ms)) ms）：\(e)")
        }
        sem.signal()
    }
    sem.wait()

case "demo":
    guard let (key, src) = KeyStore.load() else { print("没有 Key"); exit(3) }
    print("Key 来源：\(src)（人造场景，不含真实屏幕内容）")
    func c(_ id: String, _ kind: String, _ label: String, _ x: Double, _ y: Double, _ w: Double, _ h: Double, _ p: CGPoint) -> CandidateInfo {
        let f = CGRect(x: x, y: y, width: w, height: h)
        return CandidateInfo(id: id, role: "AXButton", kind: kind, label: label, frame: f,
                             distance: Geometry.distance(p, f), direction: Geometry.direction(from: p, to: f))
    }
    let xhs = ScreenContext(appName: "Google Chrome", windowTitle: "奶油风客厅配色参考 - 小红书", url: "https://www.xiaohongshu.com/explore/demo")
    let g = ScreenContext(appName: "Google Chrome", windowTitle: "Google", url: "https://www.google.com/")
    struct Case { let name: String; let expect: String; let snap: ClickSnapshot }
    let p1 = CGPoint(x: 595, y: 800)   // 点赞右边 5 px、收藏左边 5 px
    let row: (CGPoint) -> [CandidateInfo] = { p in [
        c("c1", "button", "点赞 1.2万", 520, 788, 70, 26, p), c("c2", "button", "收藏 3456", 600, 788, 70, 26, p),
        c("c3", "button", "评论 218", 680, 788, 70, 26, p), c("c4", "button", "分享", 760, 788, 50, 26, p),
        c("c5", "link", "关注 设计师小林", 900, 120, 90, 30, p)] }
    let p3 = CGPoint(x: 700, y: 452)
    let cases = [
        Case(name: "有目标：收藏这篇笔记，指针停在点赞和收藏之间", expect: "c2",
             snap: ClickSnapshot(context: xhs, pointer: PointerMotion(x: 595, y: 800, dx: 140, dy: 10, speed: 280,
                    text: "moved right about 140 px in the last 0.5 s, then stopped"), candidates: row(p1), userGoal: "收藏这篇笔记")),
        Case(name: "无目标：指针正停在“评论”上", expect: "c3",
             snap: ClickSnapshot(context: xhs, pointer: PointerMotion(x: 720, y: 800, dx: 90, dy: 0, speed: 180,
                    text: "moved right about 90 px in the last 0.5 s, then stopped"), candidates: row(CGPoint(x: 720, y: 800)), userGoal: nil)),
        Case(name: "Google：要搜东西，指针在两个按钮之间偏下", expect: "c1",
             snap: ClickSnapshot(context: g, pointer: PointerMotion(x: 700, y: 452, dx: 0, dy: 160, speed: 320,
                    text: "moved down about 160 px in the last 0.5 s, then stopped"),
                    candidates: [c("c1", "button", "Google 搜索", 610, 460, 120, 36, p3), c("c2", "button", "手气不错", 745, 460, 110, 36, p3),
                                 c("c3", "search field", "搜索", 400, 380, 600, 46, p3), c("c4", "link", "Gmail", 1200, 20, 50, 24, p3)],
                    userGoal: "搜索 奶油风配色")),
        Case(name: "在读正文：指针几乎没动，离按钮都远", expect: "none",
             snap: ClickSnapshot(context: xhs, pointer: PointerMotion(x: 600, y: 500, dx: 2, dy: 3, speed: 7,
                    text: "barely moved in the last 0.5 s before stopping"), candidates: row(CGPoint(x: 600, y: 500)), userGoal: nil)),
    ]
    let client = JevClient(key: key)
    var hits = 0
    for k in cases {
        let sem = DispatchSemaphore(value: 0)
        let t0 = Date()
        client.systemOne(ClickQuestions.requestBody(k.snap)) { r in
            let ms = Date().timeIntervalSince(t0) * 1000
            switch r {
            case .success(let d):
                if let a = try? ClickQuestions.parse(d) {
                    let ok = a.choice == k.expect
                    if ok { hits += 1 }
                    let lab = k.snap.candidates.first { $0.id == a.choice }?.label ?? "都不是"
                    let top = a.probabilities.sorted { $0.value > $1.value }.prefix(3).map { String(format: "%@ %.2f", $0.key, $0.value) }.joined(separator: "  ")
                    print(String(format: "%@ %@\n    → %@（%@）期望 %@ · 置信度 %.2f · 要点击 %.2f · %.0f ms · %@ · 输入 %d tok\n    前三：%@",
                                 ok ? "✓" : "✗", k.name, a.choice, lab, k.expect, a.confidence ?? -1, a.aboutToClick ?? -1, ms,
                                 a.model ?? "?", a.inputTokens ?? -1, top))
                } else { print("✗ \(k.name)：解析失败 \(String(data: d, encoding: .utf8)?.prefix(200) ?? "")") }
            case .failure(let e): print("✗ \(k.name)：\(e)（\(Int(ms)) ms）")
            }
            sem.signal()
        }
        sem.wait()
    }
    print("命中 \(hits)/\(cases.count)（人造场景，只说明请求格式和大致行为，不是命中率）")

default:
    print("未知命令：\(cmd)")
    exit(1)
}
