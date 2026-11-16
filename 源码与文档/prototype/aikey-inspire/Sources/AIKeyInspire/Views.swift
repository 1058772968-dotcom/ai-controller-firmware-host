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
                }.padding(6)
            }
        }
        .padding(18)
        .frame(width: 560)
    }

    private func hk(_ k: String, _ d: String) -> some View {
        HStack { Text(k).font(.system(.body, design: .monospaced)).frame(width: 60, alignment: .leading); Text(d) }
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

struct IntentView: View {
    let draft: CircleController.Draft
    var onSave: (String) -> Void
    var onCancel: () -> Void
    @State private var intent = ""
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
            TextField("说明意图，比如：这个配色想用在灵感卡片上", text: $intent, axis: .vertical)
                .lineLimit(2...5)
                .textFieldStyle(.roundedBorder)
                .focused($focused)
                .onSubmit { onSave(intent) }
            HStack {
                Text("↩ 保存").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("取消", action: onCancel).keyboardShortcut(.cancelAction)
                Button("存进灵感库") { onSave(intent) }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(16)
        .frame(width: 560)
        .onAppear { focused = true }
    }
}

// MARK: - 灵感库

struct LibraryView: View {
    @ObservedObject var state: AppState
    private let cols = [GridItem(.adaptive(minimum: 230), spacing: 12)]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("灵感库（\(state.library.count)）").font(.title3.bold())
                Spacer()
                Text("把卡片拖进 agent 的对话框；或点“复制”后粘贴").font(.caption).foregroundStyle(.secondary)
                Button("打开文件夹") { NSWorkspace.shared.open(state.store.root) }
            }
            if state.library.isEmpty {
                Spacer()
                Text("还没有灵感。按 ⌃⌥C 开始圈选，移动光标圈住喜欢的内容，再按 ⌃⌥C。").foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity)
                Spacer()
            } else {
                ScrollView {
                    LazyVGrid(columns: cols, spacing: 12) {
                        ForEach(state.library) { item in card(item) }
                    }.padding(2)
                }
            }
        }
        .padding(14)
        .frame(minWidth: 760, minHeight: 520)
    }

    private func card(_ item: InspirationItem) -> some View {
        let url = state.store.imageURL(item)
        return VStack(alignment: .leading, spacing: 6) {
            ZStack {
                RoundedRectangle(cornerRadius: 6).fill(Color.gray.opacity(0.12))
                if let url, let img = NSImage(contentsOf: url) {
                    Image(nsImage: img).resizable().scaledToFit().clipShape(RoundedRectangle(cornerRadius: 6))
                } else {
                    Text("无截图").font(.caption).foregroundStyle(.secondary)
                }
            }.frame(height: 140)
            Text(item.intent.isEmpty ? "（未写意图）" : item.intent).font(.callout.bold()).lineLimit(2)
            HStack(spacing: 6) {
                if let c = item.category {
                    Text(CategoryQuestion.displayName(c) + (item.categorySource == "jev" ? "" : "·模拟"))
                        .font(.caption2).padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Capsule().fill(Color.accentColor.opacity(0.18)))
                }
                Text([item.appName, item.windowTitle].compactMap { $0 }.joined(separator: " · "))
                    .font(.caption2).foregroundStyle(.secondary).lineLimit(1)
            }
            HStack {
                Button("复制") { copy(item) }
                if let u = item.url, let link = URL(string: u) { Button("打开来源") { NSWorkspace.shared.open(link) } }
                Spacer()
                Button(role: .destructive) { delete(item) } label: { Image(systemName: "trash") }
            }.font(.caption)
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 8).stroke(Color.gray.opacity(0.25)))
        .onDrag { provider(item) }
    }

    /// 拖出去：图片文件 + 一段说明文字（接收方取它能用的那种）
    private func provider(_ item: InspirationItem) -> NSItemProvider {
        let url = state.store.imageURL(item)
        let p = NSItemProvider()
        if let url {
            p.registerFileRepresentation(forTypeIdentifier: UTType.png.identifier, fileOptions: [], visibility: .all) { done in
                done(url, false, nil)
                return nil
            }
            p.suggestedName = "灵感-\(item.intent.prefix(12))"
        }
        p.registerObject(item.promptText(imagePath: url?.path) as NSString, visibility: .all)
        return p
    }

    private func copy(_ item: InspirationItem) {
        let url = state.store.imageURL(item)
        let pb = NSPasteboard.general
        pb.clearContents()
        var objs: [NSPasteboardWriting] = []
        if let url, let img = NSImage(contentsOf: url) { objs.append(img) }
        objs.append(item.promptText(imagePath: url?.path) as NSString)
        pb.writeObjects(objs)
    }

    private func delete(_ item: InspirationItem) {
        try? state.store.delete(id: item.id)
        state.reloadLibrary()
    }
}
