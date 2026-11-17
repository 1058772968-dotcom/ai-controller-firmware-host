import AppKit
import SwiftUI
import UniformTypeIdentifiers
import InspireCore

// MARK: - 权限与设置

struct SettingsView: View {
    @ObservedObject var state: AppState
    @State private var keyInput = ""
    @State private var keyMessage = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("AI KEY 灵感圈").font(.title2.bold())
            Text("控制器当鼠标用不需要这个 App；这里加的是点击预判、圈选灵感和灵感库。").foregroundStyle(.secondary)

            GroupBox("系统权限") {
                VStack(alignment: .leading, spacing: 10) {
                    permRow("辅助功能", ok: state.axTrusted,
                            why: "读光标附近的按钮和链接（点击预判、圈内文字），以及“点它”。",
                            request: { AX.requestTrust() },
                            pane: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
                    permRow("屏幕录制", ok: state.screenTrusted,
                            why: "圈选时截下圈住的那一块。没有它也能存，只是没有图。授权后可能要重开 App。",
                            request: { ScreenCapture.requestTrust() },
                            pane: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")
                }.padding(6)
            }

            GroupBox("Jev（TypeSafe）") {
                VStack(alignment: .leading, spacing: 8) {
                    Text("当前：\(state.jevMode)").font(.callout)
                    HStack {
                        SecureField("粘贴 TypeSafe API Key", text: $keyInput).textFieldStyle(.roundedBorder)
                        Button("存到钥匙串") {
                            if KeyStore.save(keyInput) {
                                keyInput = ""
                                state.reloadKey()
                                keyMessage = "已保存"
                            } else { keyMessage = "保存失败" }
                        }.disabled(keyInput.trimmingCharacters(in: .whitespaces).isEmpty)
                        Button("测试连接") { testKey() }.disabled(state.apiKey == nil)
                        Button("删除") { KeyStore.delete(); state.reloadKey(); keyMessage = "已删除（环境变量里的仍会生效）" }
                            .disabled(state.keySource != "钥匙串")
                    }
                    Text(keyMessage.isEmpty ? state.jevStatus : keyMessage).font(.caption).foregroundStyle(.secondary)
                    Text("Key 只存在本机钥匙串，不写日志。没有 Key 时用本地“模拟”预判（只看距离和方向），用来调界面。")
                        .font(.caption).foregroundStyle(.secondary)
                    Text("会发给 TypeSafe 的内容：软件名、窗口标题、网址、光标附近元素的文字和位置、你写的意图。不发截图。")
                        .font(.caption).foregroundStyle(.orange)
                }.padding(6)
            }

            GroupBox("快捷键") {
                VStack(alignment: .leading, spacing: 4) {
                    hk("⌃⌥P", "立刻预判一次（不用等停留）")
                    hk("⌃⌥↩", "点击预判的目标")
                    hk("⌃⌥C", "开始 / 完成圈选（圈选中 Esc 取消）")
                    hk("⌃⌥L", "打开灵感库")
                    hk("⌃⌥D", "调试面板")
                    Divider()
                    hk("⌃⌥S", "快速搜索：可先点名 小红书 / b站 / 推特 / 知乎 / 谷歌 / 页内 / 灵感库")
                    hk("⌃⌥← →", "图片上一张 / 下一张；按住不放连续翻")
                    hk("⌃⌥1", "点赞（指针所在内容）")
                    hk("⌃⌥2", "收藏")
                    hk("⌃⌥3", "投币（先确认）")
                    hk("⌃⌥4", "关注（先确认）")
                    hk("⌃⌥Z", "撤销 5 秒内的点赞 / 收藏")
                    Divider()
                    hk("⌃⌥G", "目标模式开 / 关：给屏上卡片标相关度，无关和推广压暗")
                    hk("⌃⌥N", "跳到下一条相关的（这一屏没有就往下翻）")
                    hk("⌃⌥X", "关闭弹窗（关闭、×、暂不登录）")
                    hk("⌃⌥K", "把灵感库里勾选的几条打包复制给 agent")
                    Toggle("快速搜索后自动打开目标模式（搜索词当目标）", isOn: $state.autoTargetAfterSearch).font(.callout)
                }.padding(6)
            }
        }
        .padding(18)
        .frame(width: 560)
    }

    private func hk(_ k: String, _ d: String) -> some View {
        HStack { Text(k).font(.system(.body, design: .monospaced)).frame(width: 76, alignment: .leading); Text(d) }
    }

    private func permRow(_ name: String, ok: Bool, why: String, request: @escaping () -> Void, pane: String) -> some View {
        HStack(alignment: .top) {
            Image(systemName: ok ? "checkmark.circle.fill" : "xmark.circle.fill").foregroundStyle(ok ? .green : .red)
            VStack(alignment: .leading, spacing: 2) {
                Text(name + (ok ? "：已授权" : "：未授权")).bold()
                Text(why).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if !ok {
                Button("请求授权") { request() }
                Button("打开系统设置") { if let u = URL(string: pane) { NSWorkspace.shared.open(u) } }
            }
        }
    }

    private func testKey() {
        guard let k = state.apiKey else { return }
        state.jevStatus = "测试中…"
        let t0 = Date()
        JevClient(key: k).listModels { r in
            let ms = Int(Date().timeIntervalSince(t0) * 1000)
            DispatchQueue.main.async {
                switch r {
                case .success(let d):
                    let names = ((try? JSONSerialization.jsonObject(with: d)) as? [String: Any])?["data"] as? [[String: Any]]
                    let list = names?.compactMap { $0["id"] as? String ?? $0["name"] as? String }.prefix(5).joined(separator: ", ") ?? ""
                    state.jevStatus = "连接正常（\(ms) ms）\(list.isEmpty ? "" : "：\(list)")"
                case .failure(let e):
                    state.jevStatus = "连接失败（\(ms) ms）：\(e.description)"
                }
                keyMessage = ""
            }
        }
    }
}

// MARK: - 调试面板

struct DebugView: View {
    @ObservedObject var state: AppState
    var onPredict: () -> Void
    var onClick: () -> Void
    var onMark: (Bool) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Toggle("停留自动预判", isOn: $state.predictionEnabled)
                Toggle("显示全部候选框", isOn: $state.showAllCandidates)
                Spacer()
                Text(state.jevMode).font(.caption).foregroundStyle(.secondary)
            }
            HStack {
                Text("当前目标")
                TextField("可选：比如“发布这篇笔记”“搜索配色”。会作为 user_goal 发给 Jev", text: $state.userGoal)
                    .textFieldStyle(.roundedBorder)
            }
            if !state.axTrusted {
                Text("没有辅助功能权限：找不到候选。到“权限与设置”里授权。").foregroundStyle(.red)
            }
            GroupBox {
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text("第 \(state.predictionCount) 次 · 来源 \(state.source)").bold()
                        Spacer()
                        Text(timing).font(.caption.monospaced())
                    }
                    Text(state.contextText).font(.caption).lineLimit(2)
                    Text("指针：\(state.motionText)").font(.caption).foregroundStyle(.secondary)
                    if !state.lastQuickAction.isEmpty {
                        Text("快捷功能：\(state.lastQuickAction)").font(.caption).foregroundStyle(.blue).lineLimit(2)
                    }
                    if state.targetModeOn {
                        Text("目标模式：\(state.userGoal) · \(state.targetStatus)").font(.caption).foregroundStyle(.green).lineLimit(2)
                    }
                    if let e = state.lastError { Text(e).font(.caption).foregroundStyle(.red).lineLimit(3) }
                    HStack {
                        Text("预判：\(predictedText)")
                        Spacer()
                        if let c = state.confidence { Text(String(format: "置信度 %.2f", c)) }
                        if let n = state.aboutToClick { Text(String(format: "要点击 %.2f", n)) }
                    }.font(.callout)
                }
            }
            Table(state.rows) {
                TableColumn("id") { r in Text(r.id).bold(r.id == state.predicted) }.width(44)
                TableColumn("概率") { r in Text(r.probability.map { String(format: "%.1f%%", $0 * 100) } ?? "—") }.width(60)
                TableColumn("类型", value: \.kind).width(90)
                TableColumn("文字", value: \.label)
                TableColumn("距离") { r in Text(r.id == ClickQuestions.noneId ? "" : String(format: "%.0f", r.distance)) }.width(44)
                TableColumn("方向", value: \.direction).width(90)
            }
            .frame(minHeight: 200)
            HStack {
                Button("立刻预判 ⌃⌥P", action: onPredict)
                Button("点它 ⌃⌥↩", action: onClick).disabled(state.predicted == nil || state.predicted == ClickQuestions.noneId)
                Button("猜对了") { onMark(true) }
                Button("猜错了") { onMark(false) }
                Spacer()
                Button("复制本次请求 JSON") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(state.requestJSON, forType: .string)
                }.disabled(state.requestJSON.isEmpty)
                Button("打开日志") { NSWorkspace.shared.open(JSONLLog.directory) }
            }
        }
        .padding(14)
        .frame(minWidth: 720, minHeight: 460)
    }

    private var predictedText: String {
        guard let p = state.predicted else { return "—" }
        if p == ClickQuestions.noneId { return "都不是" }
        return state.rows.first { $0.id == p }.map { "\($0.id) \($0.kind) “\($0.label)”" } ?? p
    }

    private var timing: String {
        var s: [String] = []
        if let m = state.scanMs { s.append(String(format: "枚举 %.0f ms", m)) }
        if let m = state.jevMs { s.append(String(format: "Jev %.0f ms", m)) }
        return s.joined(separator: " · ")
    }
}

// MARK: - 意图面板

/// 存进灵感库时选的项目：自动 = 让 Jev 判断
enum ProjectChoice: Hashable {
    case auto, none, named(String)
}

struct IntentView: View {
    let draft: CircleController.Draft
    let projects: [String]
    var onSave: (String, ProjectChoice) -> Void
    var onCancel: () -> Void
    @State private var intent = ""
    @State private var project: ProjectChoice = .auto
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("这条灵感想拿来做什么？").font(.headline)
            if let d = draft.png, let img = NSImage(data: d) {
                Image(nsImage: img).resizable().scaledToFit().frame(maxWidth: 520, maxHeight: 260)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
            }
            if let n = draft.captureNote { Text(n).font(.caption).foregroundStyle(.orange) }
            Text(draft.context.summary.isEmpty ? "来源未知" : draft.context.summary).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            if !draft.texts.isEmpty {
                Text("圈内文字：" + draft.texts.prefix(5).joined(separator: " / ")).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            }
            TextField("说明意图，比如：这个配色想用在灵感卡片上 #奶油风", text: $intent, axis: .vertical)
                .lineLimit(2...5)
                .textFieldStyle(.roundedBorder)
                .focused($focused)
                .onSubmit { onSave(intent, project) }
            if !projects.isEmpty {
                Picker("项目", selection: $project) {
                    Text("自动判断").tag(ProjectChoice.auto)
                    Text("不归属").tag(ProjectChoice.none)
                    ForEach(projects, id: \.self) { p in Text(p).tag(ProjectChoice.named(p)) }
                }
                .frame(maxWidth: 320)
            }
            HStack {
                Text("↩ 保存 · 写 #标签 会变成标签 · 保存后自动判断类别、项目、标签和是否重复").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("取消", action: onCancel).keyboardShortcut(.cancelAction)
                Button("存进灵感库") { onSave(intent, project) }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(16)
        .frame(width: 560)
        .onAppear { focused = true }
    }
}

// 灵感库窗口在 LibraryViews.swift


// MARK: - F1 快速搜索框

struct SearchView: View {
    let currentURL: String?
    var onSubmit: (SearchPlan) -> Void
    var onCancel: () -> Void
    @State private var input: String
    @State private var submitted = false
    @FocusState private var focused: Bool

    init(initial: String, currentURL: String?, onSubmit: @escaping (SearchPlan) -> Void, onCancel: @escaping () -> Void) {
        _input = State(initialValue: initial)
        self.currentURL = currentURL
        self.onSubmit = onSubmit
        self.onCancel = onCancel
    }

    private var plan: SearchPlan { QuickSearch.plan(input: input, currentURL: currentURL) }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField("搜什么？可以先点名：小红书 / b站 / 推特 / 知乎 / 谷歌 / 页内 / 灵感库", text: $input)
                .textFieldStyle(.roundedBorder)
                .font(.title3)
                .focused($focused)
                .onSubmit { submit() }
            HStack(spacing: 4) {
                Text("去向：\(plan.destination.name)").bold()
                Text("（\(plan.reason)）").foregroundStyle(.secondary)
            }
            if !plan.query.isEmpty { Text("搜索词：\(plan.query)") }
            if let u = plan.url { Text(u.absoluteString).font(.caption).foregroundStyle(.secondary).lineLimit(1) }
            HStack {
                Text("↩ 搜索 · esc 取消 · 选中的文字会自动填进来").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("取消", action: onCancel).keyboardShortcut(.cancelAction)
                Button("搜索") { submit() }.disabled(plan.query.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(14)
        .frame(width: 600)
        .onAppear { focused = true }
    }

    private func submit() {
        guard !submitted else { return }
        guard !plan.query.trimmingCharacters(in: .whitespaces).isEmpty else { NSSound.beep(); return }
        submitted = true
        onSubmit(plan)
    }
}

// MARK: - 投币 / 关注前的确认

struct ConfirmView: View {
    let text: String
    var onConfirm: () -> Void
    var onCancel: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("确认一下").font(.headline)
            Text(text).fixedSize(horizontal: false, vertical: true)
            Text("这类操作撤不回或会公开，按 ↩ 确认，esc 取消。投币时网站自己还会再弹一次选币数。")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("取消", action: onCancel).keyboardShortcut(.cancelAction)
                Button("确认", action: onConfirm).keyboardShortcut(.defaultAction)
            }
        }
        .padding(16)
        .frame(width: 420)
    }
}
