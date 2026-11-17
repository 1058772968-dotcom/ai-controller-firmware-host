import AppKit
import SwiftUI
import UniformTypeIdentifiers
import InspireCore

// MARK: - 灵感库（K2 整理、K3 筛选与召回、K4 打包、K5 回流、K6 回到原处）

struct LibraryView: View {
    @ObservedObject var state: AppState
    let actions: LibraryActions
    @State private var editing: InspirationItem?
    @State private var managingProjects = false
    private let cols = [GridItem(.adaptive(minimum: 230), spacing: 12)]
    private static let categoryIds = CategoryQuestion.options.map { $0.id }

    private var filtered: [InspirationItem] {
        let list = state.query.apply(state.library)
        guard !state.recallScores.isEmpty else { return list }
        return list.sorted { (state.recallScores[$0.id] ?? -1) > (state.recallScores[$1.id] ?? -1) }
    }
    /// 召回后最相关的前 5 条（相关度 ≥ 1.5）
    private func topIds(_ list: [InspirationItem]) -> [String] {
        guard !state.recallScores.isEmpty else { return [] }
        return list.filter { (state.recallScores[$0.id] ?? 0) >= 1.5 }.prefix(5).map(\.id)
    }
    private var activeCount: Int { state.library.filter { !$0.isArchived }.count }
    private var sources: [String] { Array(Set(state.library.map { LibraryQuery.sourceName($0) })).sorted() }
    private var allTags: [String] {
        var c: [String: Int] = [:]
        for it in state.library { for t in it.tagList { c[t, default: 0] += 1 } }
        return c.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }.map(\.key)
    }
    private var dupCount: Int { state.library.filter { $0.pendingDuplicate != nil && !$0.isArchived }.count }
    private var unorganized: [String] { state.library.filter { $0.organizedAt == nil && !$0.isArchived }.map(\.id) }
    private var staleCount: Int { AppDelegate.staleItems(state.library).count }

    var body: some View {
        let list = filtered
        let top = topIds(list)
        return VStack(alignment: .leading, spacing: 8) {
            header(list.count)
            filters
            recallBar(top)
            if !state.selection.isEmpty { selectionBar(list) }
            Divider()
            content(list, top: Set(top))
        }
        .padding(14)
        .frame(minWidth: 920, minHeight: 620)
        .sheet(item: $editing) { it in
            ItemEditor(state: state, actions: actions, original: it, onClose: { editing = nil })
        }
        .sheet(isPresented: $managingProjects) {
            ProjectsEditor(state: state, onClose: { managingProjects = false })
        }
    }

    private func header(_ shown: Int) -> some View {
        HStack {
            Text("灵感库（\(shown)/\(activeCount)）").font(.title3.bold())
            TextField("搜索：意图、来源、项目、标签、圈内文字（空格分开多个词）", text: $state.query.text)
                .textFieldStyle(.roundedBorder).frame(maxWidth: 340)
            Spacer()
            Text("勾选后打包给 agent；单张卡片也能直接拖进对话框").font(.caption).foregroundStyle(.secondary)
            Menu("整理") {
                Button("管理项目…") { managingProjects = true }
                Button("让 Jev 整理没整理过的（\(unorganized.count)）") { actions.organize(unorganized) }.disabled(unorganized.isEmpty)
                Button("归档 30 天没用过的（\(staleCount)）") { actions.archiveStale() }.disabled(staleCount == 0)
                Divider()
                Button("打开灵感库文件夹") { NSWorkspace.shared.open(state.store.root) }
            }
            .frame(width: 70)
        }
    }

    private var filters: some View {
        HStack(spacing: 8) {
            Picker("类别", selection: $state.query.category) {
                Text("全部类别").tag(String?.none)
                ForEach(Self.categoryIds, id: \.self) { id in Text(CategoryQuestion.displayName(id)).tag(Optional(id)) }
            }.labelsHidden().frame(width: 110)
            Picker("项目", selection: $state.query.project) {
                Text("全部项目").tag(String?.none)
                Text("未归属").tag(Optional(LibraryQuery.noProject))
                ForEach(state.projects, id: \.self) { p in Text(p).tag(Optional(p)) }
            }.labelsHidden().frame(width: 150)
            Picker("标签", selection: $state.query.tag) {
                Text("全部标签").tag(String?.none)
                ForEach(allTags, id: \.self) { t in Text("#" + t).tag(Optional(t)) }
            }.labelsHidden().frame(width: 110)
            Picker("来源", selection: $state.query.source) {
                Text("全部来源").tag(String?.none)
                ForEach(sources, id: \.self) { s in Text(s).tag(Optional(s)) }
            }.labelsHidden().frame(width: 120)
            Picker("时间", selection: $state.query.days) {
                Text("全部时间").tag(Int?.none)
                Text("今天").tag(Optional(1))
                Text("最近 7 天").tag(Optional(7))
                Text("最近 30 天").tag(Optional(30))
            }.labelsHidden().frame(width: 110)
            Toggle("没用过", isOn: $state.query.unusedOnly)
            Toggle("可能重复（\(dupCount)）", isOn: $state.query.duplicatesOnly)
            Toggle("显示归档", isOn: $state.query.showArchived)
            if !state.query.isEmpty { Button("清除筛选") { state.query = LibraryQuery() } }
            Spacer()
        }
        .font(.callout)
    }

    private func recallBar(_ topIds: [String]) -> some View {
        HStack {
            Image(systemName: "sparkle.magnifyingglass").foregroundStyle(.secondary)
            TextField("按任务召回：比如“根据我的参考重新生成 AI 控制器宣传 PPT”", text: $state.recallTask)
                .textFieldStyle(.roundedBorder)
                .onSubmit { actions.recall() }
            Button(state.recallBusy ? "判断中…" : "召回") { actions.recall() }
                .disabled(state.recallBusy || state.recallTask.trimmingCharacters(in: .whitespaces).isEmpty)
            if !state.recallScores.isEmpty {
                Button("选中前 \(topIds.count) 条") { state.selection.formUnion(topIds) }.disabled(topIds.isEmpty)
                Button("清除召回") { actions.clearRecall() }
            }
            Text(state.recallStatus).font(.caption).foregroundStyle(.secondary).lineLimit(1)
        }
    }

    private func selectionBar(_ filtered: [InspirationItem]) -> some View {
        HStack {
            Text("已选 \(state.selection.count) 条").bold()
            Button("打包复制 ⌃⌥K") { actions.copyPack(Array(state.selection)) }
            Button("导出文件夹") { actions.exportPack(Array(state.selection)) }
            Menu("设项目") {
                Button("不归属") { setProject(nil) }
                ForEach(state.projects, id: \.self) { p in Button(p) { setProject(p) } }
            }.frame(width: 80)
            Button("让 Jev 整理") { actions.organize(Array(state.selection)) }
            Button("归档") { setArchived(true) }
            Spacer()
            Button("全选当前 \(filtered.count) 条") { state.selection.formUnion(filtered.map(\.id)) }
            Button("清空选择") { state.selection = [] }
        }
        .padding(6)
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.accentColor.opacity(0.1)))
    }

    @ViewBuilder private func content(_ filtered: [InspirationItem], top: Set<String>) -> some View {
        if state.library.isEmpty {
            Spacer()
            Text("还没有灵感。按 ⌃⌥C 开始圈选，移动光标圈住喜欢的内容，再按 ⌃⌥C。").foregroundStyle(.secondary).frame(maxWidth: .infinity)
            Spacer()
        } else if filtered.isEmpty {
            Spacer()
            Text("没有符合筛选的灵感").foregroundStyle(.secondary).frame(maxWidth: .infinity)
            Spacer()
        } else {
            ScrollView {
                LazyVGrid(columns: cols, spacing: 12) { ForEach(filtered) { item in card(item, isTop: top.contains(item.id)) } }.padding(2)
            }
        }
    }

    private func card(_ item: InspirationItem, isTop: Bool) -> some View {
        let url = state.store.imageURL(item)
        let selected = state.selection.contains(item.id)
        let score = state.recallScores[item.id]
        return VStack(alignment: .leading, spacing: 6) {
            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: 6).fill(Color.gray.opacity(0.12))
                if let url, let img = NSImage(contentsOf: url) {
                    Image(nsImage: img).resizable().scaledToFit().clipShape(RoundedRectangle(cornerRadius: 6))
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    Text("无截图").font(.caption).foregroundStyle(.secondary).frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                Button { toggle(item.id) } label: {
                    Image(systemName: selected ? "checkmark.circle.fill" : "circle").font(.title2)
                        .foregroundStyle(selected ? Color.accentColor : Color.secondary)
                        .background(Circle().fill(Color(nsColor: .windowBackgroundColor).opacity(0.85)))
                }
                .buttonStyle(.plain).padding(6).help("勾选，用来打包给 agent").accessibilityLabel(selected ? "取消勾选" : "勾选")
                if let s = score {
                    HStack {
                        Spacer()
                        Text(String(format: "%@ %.1f", RecallQuestions.levelName(s), s)).font(.caption2.bold())
                            .padding(.horizontal, 6).padding(.vertical, 3)
                            .background(Capsule().fill(s >= 1.5 ? Color.green.opacity(0.85) : Color.gray.opacity(0.6)))
                            .foregroundStyle(.white)
                    }.padding(6)
                }
            }
            .frame(height: 140)
            Text(item.intent.isEmpty ? "（未写意图）" : item.intent).font(.callout.bold()).lineLimit(2)
            HStack(spacing: 4) {
                if let c = item.category { chip(CategoryQuestion.displayName(c) + (item.categorySource == "mock" ? "·模拟" : ""), .accentColor) }
                if let p = item.project { chip(p, .purple) }
                ForEach(item.tagList.prefix(3), id: \.self) { t in chip("#" + t, .teal) }
                if item.pendingDuplicate != nil { chip("可能重复", .orange) }
                if item.isArchived { chip("已归档", .gray) }
            }
            .lineLimit(1)
            HStack {
                Text(LibraryQuery.sourceName(item) + " · " + item.createdAt.formatted(date: .abbreviated, time: .omitted))
                    .font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                Spacer()
                if item.uses > 0 { Text("用过 \(item.uses) 次").font(.caption2).foregroundStyle(.secondary) }
            }
            HStack {
                Button("复制") { actions.copyOne(item) }
                if item.url != nil { Button("回到原处") { actions.openSource(item) }.help("打开原网页，并尽量滚到圈过的那段文字") }
                Spacer()
                Button { editing = item } label: { Image(systemName: "pencil") }.help("编辑意图、类别、项目、标签").accessibilityLabel("编辑")
                Button(role: .destructive) { delete(item) } label: { Image(systemName: "trash") }.help("移到废纸篓").accessibilityLabel("删除")
            }
            .font(.caption)
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 8).fill(selected ? Color.accentColor.opacity(0.08) : Color.clear))
        .overlay(RoundedRectangle(cornerRadius: 8)
            .stroke(isTop ? Color.green : (selected ? Color.accentColor : Color.gray.opacity(0.25)), lineWidth: isTop || selected ? 2 : 1))
        .opacity(item.isArchived ? 0.55 : 1)
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { editing = item }
        .onDrag {
            state.store.markUsed([item.id])   // 拖出去算用过一次；不在这里刷新列表，免得打断拖动
            return provider(item)
        }
    }

    private func chip(_ text: String, _ color: Color) -> some View {
        Text(text).font(.caption2).padding(.horizontal, 6).padding(.vertical, 2)
            .background(Capsule().fill(color.opacity(0.18)))
    }

    private func toggle(_ id: String) {
        if state.selection.contains(id) { state.selection.remove(id) } else { state.selection.insert(id) }
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

    private func delete(_ item: InspirationItem) {
        try? state.store.delete(id: item.id)
        state.selection.remove(item.id)
        state.reloadLibrary()
    }

    private func setProject(_ p: String?) {
        for id in state.selection {
            guard var it = state.store.item(id: id) else { continue }
            it.project = p
            it.projectSource = "user"
            it.updatedAt = Date()
            try? state.store.update(it)
        }
        state.reloadLibrary()
    }

    private func setArchived(_ on: Bool) {
        for id in state.selection {
            guard var it = state.store.item(id: id) else { continue }
            it.archived = on
            it.updatedAt = Date()
            try? state.store.update(it)
        }
        state.selection = []
        state.reloadLibrary()
    }
}

// MARK: - 编辑一条灵感

struct ItemEditor: View {
    @ObservedObject var state: AppState
    let actions: LibraryActions
    let original: InspirationItem
    var onClose: () -> Void
    @State private var intent: String
    @State private var category: String?
    @State private var project: String?
    @State private var tagText: String
    @State private var newProject = ""

    init(state: AppState, actions: LibraryActions, original: InspirationItem, onClose: @escaping () -> Void) {
        self.state = state
        self.actions = actions
        self.original = original
        self.onClose = onClose
        _intent = State(initialValue: original.intent)
        _category = State(initialValue: original.category)
        _project = State(initialValue: original.project)
        _tagText = State(initialValue: original.tagList.joined(separator: " "))
    }

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            VStack(alignment: .leading, spacing: 8) {
                if let u = state.store.imageURL(original), let img = NSImage(contentsOf: u) {
                    Image(nsImage: img).resizable().scaledToFit().frame(maxWidth: 340, maxHeight: 280)
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                } else {
                    RoundedRectangle(cornerRadius: 6).fill(Color.gray.opacity(0.12)).frame(width: 340, height: 120)
                        .overlay(Text("无截图").foregroundStyle(.secondary))
                }
                info
            }
            .frame(width: 340)
            VStack(alignment: .leading, spacing: 10) {
                Text("编辑灵感").font(.headline)
                TextField("意图：为什么收它（写 #标签 会变成标签）", text: $intent, axis: .vertical)
                    .lineLimit(2...5).textFieldStyle(.roundedBorder)
                Picker("类别", selection: $category) {
                    Text("未分类").tag(String?.none)
                    ForEach(CategoryQuestion.options.map { $0.id }, id: \.self) { id in Text(CategoryQuestion.displayName(id)).tag(Optional(id)) }
                }
                HStack {
                    Picker("项目", selection: $project) {
                        Text("不归属").tag(String?.none)
                        ForEach(state.projects, id: \.self) { p in Text(p).tag(Optional(p)) }
                    }
                    TextField("新项目名", text: $newProject).textFieldStyle(.roundedBorder).frame(width: 120).onSubmit(addProject)
                    Button("添加", action: addProject).disabled(newProject.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                TextField("标签：空格或逗号分开", text: $tagText).textFieldStyle(.roundedBorder)
                if let a = original.autoTags, !a.isEmpty {
                    Text("其中自动加的：\(a.joined(separator: "、"))（不对就删掉）").font(.caption).foregroundStyle(.secondary)
                }
                if let d = original.pendingDuplicate { duplicateBox(d) }
                Spacer(minLength: 0)
                HStack {
                    Button("复制") { actions.copyOne(original) }
                    if original.url != nil { Button("回到原处") { actions.openSource(original) } }
                    Button("让 Jev 重新整理") { actions.organize([original.id]); onClose() }
                    Button(original.isArchived ? "取消归档" : "归档") { setArchived(!original.isArchived) }
                    Button("删除", role: .destructive) {
                        try? state.store.delete(id: original.id)
                        state.selection.remove(original.id)
                        state.reloadLibrary()
                        onClose()
                    }
                }
                .font(.callout)
                HStack {
                    Spacer()
                    Button("取消", action: onClose).keyboardShortcut(.cancelAction)
                    Button("保存", action: save).keyboardShortcut(.defaultAction)
                }
            }
            .frame(width: 440)
        }
        .padding(16)
        .frame(minHeight: 440)
    }

    private var info: some View {
        VStack(alignment: .leading, spacing: 3) {
            let src = [original.appName, original.windowTitle].compactMap { $0 }.joined(separator: " · ")
            if !src.isEmpty { Text("来源：" + src).lineLimit(2) }
            if let u = original.url { Text("链接：" + u).lineLimit(2).textSelection(.enabled) }
            if !original.texts.isEmpty { Text("圈内文字：" + original.texts.prefix(6).joined(separator: " / ")).lineLimit(4) }
            Text("保存于 " + original.createdAt.formatted(date: .abbreviated, time: .shortened))
            Text("用过 \(original.uses) 次" + (original.lastUsedAt.map { "，上次 " + $0.formatted(date: .abbreviated, time: .shortened) } ?? ""))
            let how = [original.categorySource.map { "类别来自 \($0)" }, original.projectSource.map { "项目来自 \($0)" },
                       original.organizedAt.map { "整理于 " + $0.formatted(date: .omitted, time: .shortened) }].compactMap { $0 }
            if !how.isEmpty { Text(how.joined(separator: " · ")) }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    private func duplicateBox(_ d: String) -> some View {
        let o = state.library.first { $0.id == d }
        return GroupBox(String(format: "可能和这条是同一个（%.0f%%）", (original.duplicateProbability ?? 0) * 100)) {
            VStack(alignment: .leading, spacing: 6) {
                Text(o.map { $0.intent.isEmpty ? "（未写意图）" : $0.intent } ?? "原条目已经不在了").bold()
                if let o { Text([o.appName, o.windowTitle].compactMap { $0 }.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary) }
                HStack {
                    Button("合并到那条") { actions.merge(original.id, d); onClose() }.disabled(o == nil)
                    Button("不是重复") {
                        guard var it = state.store.item(id: original.id) else { return }
                        it.duplicateDismissed = true
                        try? state.store.update(it)
                        state.reloadLibrary()
                        onClose()
                    }
                }
                Text("合并：意图和标签并进那条，这条移到废纸篓").font(.caption).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(4)
        }
    }

    private func addProject() {
        let n = newProject.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !n.isEmpty else { return }
        if !state.projects.contains(n) { try? state.store.saveProjects(state.projects + [n]); state.reloadLibrary() }
        project = n
        newProject = ""
    }

    private func setArchived(_ on: Bool) {
        guard var it = state.store.item(id: original.id) else { return }
        it.archived = on
        it.updatedAt = Date()
        try? state.store.update(it)
        state.reloadLibrary()
        onClose()
    }

    private func save() {
        guard var it = state.store.item(id: original.id) else { onClose(); return }
        let (clean, hashTags) = Hashtags.extract(intent)
        it.intent = clean
        if category != it.category { it.category = category; it.categorySource = "user" }
        if project != it.project { it.project = project; it.projectSource = "user" }
        var tags = Hashtags.parseList(tagText)
        for t in hashTags where !tags.contains(t) { tags.append(t) }
        it.tags = tags.isEmpty ? nil : tags
        let auto = (it.autoTags ?? []).filter { tags.contains($0) }
        it.autoTags = auto.isEmpty ? nil : auto
        it.updatedAt = Date()
        try? state.store.update(it)
        state.reloadLibrary()
        onClose()
    }
}

// MARK: - 项目列表

struct ProjectsEditor: View {
    struct Row: Identifiable {
        let id = UUID()
        var old: String?
        var name: String
    }

    @ObservedObject var state: AppState
    var onClose: () -> Void
    @State private var rows: [Row]
    @State private var removed: [String] = []
    @State private var newName = ""

    init(state: AppState, onClose: @escaping () -> Void) {
        self.state = state
        self.onClose = onClose
        _rows = State(initialValue: state.projects.map { Row(old: $0, name: $0) })
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("项目").font(.headline)
            Text("入库时 Jev 会判断这条灵感属于哪个项目；没有项目时不判断。改名会同步到已归属的条目，删掉的项目里的条目变成“未归属”。")
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            List {
                ForEach($rows) { $row in
                    HStack {
                        TextField("项目名", text: $row.name)
                        Spacer()
                        Text("\(state.library.filter { $0.project == row.old && row.old != nil }.count) 条").font(.caption).foregroundStyle(.secondary)
                        Button {
                            if let o = row.old { removed.append(o) }
                            rows.removeAll { $0.id == row.id }
                        } label: { Image(systemName: "minus.circle") }.buttonStyle(.plain).accessibilityLabel("删掉这个项目")
                    }
                }
            }
            .frame(minHeight: 160)
            HStack {
                TextField("新项目名，比如“AI 控制器宣传 PPT”", text: $newName).textFieldStyle(.roundedBorder).onSubmit(add)
                Button("添加", action: add).disabled(newName.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            HStack {
                Spacer()
                Button("取消", action: onClose).keyboardShortcut(.cancelAction)
                Button("保存", action: save).keyboardShortcut(.defaultAction)
            }
        }
        .padding(16)
        .frame(width: 480, height: 400)
    }

    private func add() {
        let n = newName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !n.isEmpty, !rows.contains(where: { $0.name == n }) else { return }
        rows.append(Row(old: nil, name: n))
        newName = ""
    }

    private func save() {
        try? state.store.saveProjects(rows.map(\.name))
        var rename: [String: String?] = [:]
        for r in rows { if let o = r.old, o != r.name { rename[o] = r.name } }
        for o in removed { rename[o] = .some(nil) }
        if !rename.isEmpty {
            for var it in state.store.all() {
                guard let p = it.project, let to = rename[p] else { continue }
                it.project = to
                it.updatedAt = Date()
                try? state.store.update(it)
            }
        }
        state.reloadLibrary()
        onClose()
    }
}

// MARK: - 目标模式的目标

struct GoalView: View {
    @State var goal: String
    var onSubmit: (String) -> Void
    var onCancel: () -> Void
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("这次在找什么？").font(.headline)
            Text("目标模式按这个目标给屏上的卡片标相关度：相关的加绿框，无关和推广的压暗。").font(.caption).foregroundStyle(.secondary)
            TextField("比如：奶油风客厅配色、好看的 PPT 排版", text: $goal)
                .textFieldStyle(.roundedBorder).font(.title3).focused($focused).onSubmit(submit)
            HStack {
                Spacer()
                Button("取消", action: onCancel).keyboardShortcut(.cancelAction)
                Button("开始", action: submit).keyboardShortcut(.defaultAction)
            }
        }
        .padding(16)
        .frame(width: 480)
        .onAppear { focused = true }
    }

    private func submit() {
        let g = goal.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !g.isEmpty else { NSSound.beep(); return }
        onSubmit(g)
    }
}
