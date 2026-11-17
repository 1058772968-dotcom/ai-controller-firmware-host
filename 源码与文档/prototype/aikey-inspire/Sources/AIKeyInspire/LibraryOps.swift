import AppKit
import InspireCore

/// 灵感库窗口里的按钮要做的事（由 AppDelegate 实现，视图只管显示）
struct LibraryActions {
    var copyPack: ([String]) -> Void
    var exportPack: ([String]) -> Void
    var recall: () -> Void
    var clearRecall: () -> Void
    var organize: ([String]) -> Void
    var merge: (String, String) -> Void
    var archiveStale: () -> Void
    var openSource: (InspirationItem) -> Void
    var copyOne: (InspirationItem) -> Void
    var markUsed: ([String]) -> Void
}

extension AppDelegate {
    var libraryActions: LibraryActions {
        LibraryActions(
            copyPack: { [weak self] ids in self?.copyPack(ids) },
            exportPack: { [weak self] ids in self?.exportPack(ids) },
            recall: { [weak self] in self?.recall() },
            clearRecall: { [weak self] in self?.state.recallScores = [:]; self?.state.recallStatus = "" },
            organize: { [weak self] ids in self?.organizeSequentially(ids) },
            merge: { [weak self] dup, orig in self?.mergeDuplicate(dup, into: orig) },
            archiveStale: { [weak self] in self?.archiveStale() },
            openSource: { it in if let u = SourceLink.url(for: it) { NSWorkspace.shared.open(u) } },
            copyOne: { [weak self] it in self?.copyPack([it.id], single: true) },
            markUsed: { [weak self] ids in self?.state.store.markUsed(ids); self?.state.reloadLibrary() }
        )
    }

    /// 按当前显示顺序取条目（召回时按相关度）
    func orderedItems(_ ids: [String]) -> [InspirationItem] {
        let set = Set(ids)
        let byId = Dictionary(uniqueKeysWithValues: state.library.map { ($0.id, $0) })
        let order = ids.isEmpty ? [] : state.library.map(\.id)
        let sorted = state.recallScores.isEmpty ? order : order.sorted { (state.recallScores[$0] ?? -1) > (state.recallScores[$1] ?? -1) }
        return sorted.filter { set.contains($0) }.compactMap { byId[$0] }
    }

    // MARK: K4 打包

    /// 复制到剪贴板：第一项是整段说明文字（带截图路径），后面是每张截图的文件
    func copyPack(_ ids: [String], single: Bool = false) {
        let items = orderedItems(ids)
        guard !items.isEmpty else { NSSound.beep(); return }
        let text = single ? items[0].promptText(imagePath: state.store.imageURL(items[0])?.path)
                          : InspirationPack.text(items, task: state.recallTask) { [weak self] in self?.state.store.imageURL($0)?.path }
        let pb = NSPasteboard.general
        pb.clearContents()
        var objs: [NSPasteboardWriting] = [text as NSString]
        if single, let u = state.store.imageURL(items[0]), let img = NSImage(contentsOf: u) { objs.append(img) }
        else { objs.append(contentsOf: items.compactMap { state.store.imageURL($0) as NSURL? }) }
        pb.writeObjects(objs)
        state.store.markUsed(items.map(\.id))
        state.reloadLibrary()
        circleLog.append(["event": single ? "copy_one" : "pack_copy", "ids": items.map(\.id), "task": state.recallTask])
        overlay.toast(single ? "已复制这条灵感" : "已复制 \(items.count) 条灵感：到 agent 里粘贴（文字里带截图路径）", seconds: 2)
    }

    /// 导出成文件夹并在访达里选中：整个文件夹可以拖进 agent
    func exportPack(_ ids: [String]) {
        let items = orderedItems(ids)
        guard !items.isEmpty else { NSSound.beep(); return }
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("AIKeyInspire/Packs", isDirectory: true)
        do {
            let out = try state.store.exportPack(items, task: state.recallTask, to: dir)
            NSWorkspace.shared.activateFileViewerSelecting([out])
            state.store.markUsed(items.map(\.id))
            state.reloadLibrary()
            circleLog.append(["event": "pack_export", "ids": items.map(\.id), "path": out.lastPathComponent])
        } catch {
            NSSound.beep()
            circleLog.append(["event": "pack_export_failed", "error": "\(error)"])
        }
    }

    /// ⌃⌥K：有勾选就打包复制；没有就打开灵感库，提示先选
    func packHotkey() {
        if !state.selection.isEmpty { copyPack(Array(state.selection)); return }
        showLibrary()
        overlay.toast("先在灵感库里勾选几条（或按任务召回后点“选中前 5”），再按 ⌃⌥K", seconds: 2.5)
    }

    // MARK: K3 按任务召回

    func recall() {
        let task = state.recallTask.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !task.isEmpty, !state.recallBusy else { NSSound.beep(); return }
        // 时间、来源、类别这些筛选在代码里先做，剩下的最近 48 条交给 Jev
        var q = state.query
        q.text = ""
        let pool = Array(q.apply(state.library).prefix(RecallQuestions.maxItems))
        guard !pool.isEmpty else { state.recallStatus = "当前筛选下没有条目"; return }
        let t0 = CFAbsoluteTimeGetCurrent()
        guard let key = state.apiKey else {
            state.recallScores = RecallQuestions.mock(task: task, items: pool)
            state.recallStatus = "模拟（没有 Key，只看字面重合）· \(pool.count) 条"
            circleLog.append(["event": "recall", "source": "mock", "task": task, "items": pool.count])
            return
        }
        state.recallBusy = true
        state.recallStatus = "Jev 判断中…"
        let batches = RecallQuestions.batches(pool)
        let group = DispatchGroup()
        let lock = NSLock()
        var scores: [String: Double] = [:]
        var errors: [String] = []
        var tokens = 0
        for b in batches {
            group.enter()
            JevClient(key: key).systemOne(RecallQuestions.requestBody(task: task, items: b)) { r in
                lock.lock()
                switch r {
                case .success(let d):
                    if let s = try? RecallQuestions.parse(d, items: b) { scores.merge(s) { $1 } } else { errors.append("解析失败") }
                    if let u = ((try? JSONSerialization.jsonObject(with: d)) as? [String: Any])?["usage"] as? [String: Any],
                       let n = (u["input_tokens"] as? NSNumber)?.intValue { tokens += n }
                case .failure(let e): errors.append(e.description)
                }
                lock.unlock()
                group.leave()
            }
        }
        group.notify(queue: .main) { [weak self] in
            guard let self else { return }
            let ms = (CFAbsoluteTimeGetCurrent() - t0) * 1000
            self.state.recallBusy = false
            let missing = pool.filter { scores[$0.id] == nil }
            if !missing.isEmpty { scores.merge(RecallQuestions.mock(task: task, items: missing)) { a, _ in a } }
            self.state.recallScores = scores
            let top = pool.filter { (scores[$0.id] ?? 0) >= 1.5 }.count
            self.state.recallStatus = String(format: "Jev · %d 条 %d 批 · %.1f s · 相关 %d 条", pool.count, batches.count, ms / 1000, top)
                + (errors.isEmpty ? "" : " · \(errors.count) 批失败，用模拟补上")
            self.circleLog.append(["event": "recall", "source": "jev", "task": task, "items": pool.count, "batches": batches.count,
                                   "ms": Int(ms), "input_tokens": tokens, "errors": errors, "relevant": top])
        }
    }

    // MARK: K2 整理

    /// 入库时（或手动“重新整理”）：一次请求判断类别、项目、标签、是否重复
    func organize(_ item: InspirationItem, done: (() -> Void)? = nil) {
        let library = state.store.all()
        let projects = state.store.projects()
        let vocab = OrganizeQuestions.vocabulary(library, excluding: item)
        let pairs = Similarity.candidates(for: item, in: library.filter { !$0.isArchived })
        let similar = pairs.map(\.item)
        let finish: (OrganizeResult, [String: Any]) -> Void = { [weak self] r, extra in
            guard let self else { return }
            guard let cur = self.state.store.item(id: item.id) else { done?(); return }   // 期间被删了
            let it = OrganizeQuestions.apply(r, to: cur)
            try? self.state.store.update(it)
            self.state.reloadLibrary()
            var log: [String: Any] = ["event": "organized", "id": item.id, "source": r.source, "category": r.category,
                                      "project": r.project ?? "", "tags": r.tags, "tag_probabilities": r.tagProbabilities,
                                      "duplicate_of": r.duplicateOf ?? "", "duplicate_p": r.duplicateProbability ?? NSNull(),
                                      "vocabulary": vocab, "similar": pairs.map { ["id": $0.item.id, "score": ($0.score * 100).rounded() / 100] }]
            log.merge(extra) { $1 }
            self.circleLog.append(log)
            if let d = it.pendingDuplicate, let o = self.state.library.first(where: { $0.id == d }) {
                self.overlay.toast("可能和“\(o.intent.prefix(16))”是同一条：到灵感库里合并或忽略", seconds: 2.5)
            }
            done?()
        }
        guard let key = state.apiKey else {
            finish(OrganizeQuestions.mock(item: item, projects: projects, vocabulary: vocab, similar: pairs), [:])
            return
        }
        let t0 = CFAbsoluteTimeGetCurrent()
        let body = OrganizeQuestions.requestBody(item: item, projects: projects, vocabulary: vocab, similar: similar,
                                                 askProject: item.projectSource != "user")
        JevClient(key: key).systemOne(body) { r in
            let ms = (CFAbsoluteTimeGetCurrent() - t0) * 1000
            DispatchQueue.main.async {
                switch r {
                case .success(let d):
                    if let res = try? OrganizeQuestions.parse(d, projects: projects, vocabulary: vocab, similar: similar) {
                        finish(res, ["jev_ms": Int(ms)])
                    } else {
                        finish(OrganizeQuestions.mock(item: item, projects: projects, vocabulary: vocab, similar: pairs),
                               ["jev_ms": Int(ms), "error": "解析失败"])
                    }
                case .failure(let e):
                    finish(OrganizeQuestions.mock(item: item, projects: projects, vocabulary: vocab, similar: pairs),
                           ["jev_ms": Int(ms), "error": e.description])
                }
            }
        }
    }

    /// 一条一条整理（免得一下发出几十个请求）
    func organizeSequentially(_ ids: [String]) {
        var rest = ids
        guard !rest.isEmpty else { return }
        let id = rest.removeFirst()
        guard let it = state.store.item(id: id) else { organizeSequentially(rest); return }
        state.recallStatus = "整理中：还剩 \(rest.count + 1) 条"
        organize(it) { [weak self] in
            if rest.isEmpty { self?.state.recallStatus = "整理完成" }
            self?.organizeSequentially(rest)
        }
    }

    func mergeDuplicate(_ dup: String, into orig: String) {
        do {
            try state.store.merge(duplicate: dup, into: orig)
            state.selection.remove(dup)
            circleLog.append(["event": "merged", "duplicate": dup, "into": orig])
        } catch {
            NSSound.beep()
            circleLog.append(["event": "merge_failed", "error": "\(error)"])
        }
        state.reloadLibrary()
    }

    // MARK: K5 回流

    /// 30 天里没用过、也不是 30 天内新收的：归档（不删，筛选里打开“显示归档”还能看到）
    static func staleItems(_ library: [InspirationItem], now: Date = Date()) -> [InspirationItem] {
        library.filter { !$0.isArchived && now.timeIntervalSince($0.lastUsedAt ?? $0.createdAt) > 30 * 86400 }
    }

    func archiveStale() {
        let stale = Self.staleItems(state.library)
        for var it in stale { it.archived = true; it.updatedAt = Date(); try? state.store.update(it) }
        circleLog.append(["event": "archive_stale", "count": stale.count])
        state.reloadLibrary()
        overlay.toast("归档了 \(stale.count) 条 30 天没用过的灵感", seconds: 1.8)
    }
}
