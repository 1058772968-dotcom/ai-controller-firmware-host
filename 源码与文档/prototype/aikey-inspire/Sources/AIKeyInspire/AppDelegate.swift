import AppKit
import SwiftUI
import InspireCore

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    let state = AppState.shared
    var overlay: OverlayController!
    var predictor: ClickPredictor!
    var circle: CircleController!
    var statusItem: NSStatusItem!
    var timer: Timer?
    var permTimer: Timer?
    let circleLog = JSONLLog(name: "circles")
    let appLog = JSONLLog(name: "app")
    var flipper: ImageFlipper!
    var interactor: QuickInteractor!
    var targetMode: TargetMode!
    var popupCloser: PopupCloser!
    var windows: [String: NSWindow] = [:]

    func applicationDidFinishLaunching(_ note: Notification) {
        state.reloadKey()
        state.reloadLibrary()
        overlay = OverlayController()
        predictor = ClickPredictor(state: state, overlay: overlay)
        circle = CircleController(overlay: overlay)
        circle.onActiveChange = { [weak self] on in self?.predictor.paused = on }
        circle.onDraft = { [weak self] d in self?.showIntent(d) }
        circle.hideOwnWindows = { [weak self] in
            let shown = self?.windows.values.filter { $0.isVisible } ?? []
            shown.forEach { $0.orderOut(nil) }
            return { shown.forEach { $0.orderFront(nil) } }
        }

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = NSImage(systemSymbolName: "scope", accessibilityDescription: "AI KEY 灵感圈")
        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu

        flipper = ImageFlipper(overlay: overlay, state: state)
        interactor = QuickInteractor(overlay: overlay, state: state)
        interactor.confirm = { [weak self] text, go in self?.showConfirm(text, go) }
        targetMode = TargetMode(state: state, overlay: overlay)
        targetMode.askGoal = { [weak self] done in self?.showGoal(done) }
        popupCloser = PopupCloser(state: state, overlay: overlay)

        let hk = HotKeys.shared
        hk.register(.predict, keyCode: 0x23, modifiers: HotKeys.ctrlOpt) { [weak self] in self?.predictor.triggerNow() }       // P
        hk.register(.clickPredicted, keyCode: 0x24, modifiers: HotKeys.ctrlOpt) { [weak self] in self?.predictor.clickPredicted() } // Return
        hk.register(.circle, keyCode: 0x08, modifiers: HotKeys.ctrlOpt) { [weak self] in self?.circle.toggle() }              // C
        hk.register(.library, keyCode: 0x25, modifiers: HotKeys.ctrlOpt) { [weak self] in self?.showLibrary() }               // L
        hk.register(.debug, keyCode: 0x02, modifiers: HotKeys.ctrlOpt) { [weak self] in self?.showDebug() }                   // D
        // F1–F3 快捷功能（键盘版，先摸清链路；手柄按键接好后再映射到 V / S）
        var failed: [String] = []
        let reg: (HotKeys.ID, Int, String, @escaping () -> Void) -> Void = { id, code, name, h in
            if !hk.register(id, keyCode: code, modifiers: HotKeys.ctrlOpt, h) { failed.append(name) }
        }
        reg(.search, 0x01, "⌃⌥S") { [weak self] in self?.openQuickSearch() }
        reg(.flipNext, 0x7C, "⌃⌥→") { [weak self] in self?.flipper.begin(.next) }
        reg(.flipPrev, 0x7B, "⌃⌥←") { [weak self] in self?.flipper.begin(.prev) }
        hk.onRelease(.flipNext) { [weak self] in self?.flipper.end() }
        hk.onRelease(.flipPrev) { [weak self] in self?.flipper.end() }
        reg(.like, 0x12, "⌃⌥1") { [weak self] in self?.interactor.run(.like) }
        reg(.collect, 0x13, "⌃⌥2") { [weak self] in self?.interactor.run(.collect) }
        reg(.coin, 0x14, "⌃⌥3") { [weak self] in self?.interactor.run(.coin) }
        reg(.follow, 0x15, "⌃⌥4") { [weak self] in self?.interactor.run(.follow) }
        reg(.undo, 0x06, "⌃⌥Z") { [weak self] in self?.interactor.undo() }
        // 浏览：B2 目标模式、B3 下一条相关的、B7 关闭弹窗；灵感库：K4 打包
        reg(.targetMode, 0x05, "⌃⌥G") { [weak self] in self?.targetMode.toggle() }
        reg(.nextCard, 0x2D, "⌃⌥N") { [weak self] in self?.targetMode.next() }
        reg(.closePopup, 0x07, "⌃⌥X") { [weak self] in self?.popupCloser.run() }
        reg(.pack, 0x28, "⌃⌥K") { [weak self] in self?.packHotkey() }
        if !failed.isEmpty { appLog.append(["event": "hotkey_register_failed", "keys": failed]) }

        // 20 Hz 读指针：停留检测 + 圈选轨迹。用 common 模式，菜单展开时也在跑。
        let t = Timer(timeInterval: 0.05, repeats: true) { [weak self] _ in
            guard let self else { return }
            let p = ScreenGeometry.mouseAX()
            if self.circle.active { self.circle.tick(p) } else { self.predictor.tick(p, t: CFAbsoluteTimeGetCurrent()) }
        }
        RunLoop.main.add(t, forMode: .common)
        timer = t
        let pt = Timer(timeInterval: 1.0, repeats: true) { [weak self] _ in self?.state.refreshPermissions() }
        RunLoop.main.add(pt, forMode: .common)
        permTimer = pt

        // 启动记录：权限状态和 Jev 模式（不含 Key）
        appLog.append(["event": "app_start", "accessibility": state.axTrusted, "screen_recording": state.screenTrusted,
                       "jev": state.apiKey != nil, "key_source": state.keySource ?? "",
                       "version": Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "",
                       "args": Array(CommandLine.arguments.dropFirst())])

        if !state.axTrusted {
            AX.requestTrust()
            showSettings()
        }
        // open … --args --request-screen-capture：主动弹“屏幕录制”授权，并打开权限窗口
        if CommandLine.arguments.contains("--request-screen-capture") {
            if !state.screenTrusted { ScreenCapture.requestTrust() }
            showSettings()
        }
        // open … --args --jev-selftest：用人造数据把整理 / 召回 / 卡片 / 关闭弹窗四种请求各发一次，结果写进 selftest.jsonl
        if CommandLine.arguments.contains("--jev-selftest") {
            let log = JSONLLog(name: "selftest")
            if let k = state.apiKey {
                log.append(["event": "selftest_start", "key_source": state.keySource ?? ""])
                JevSelfTest.run(key: k, output: { line in log.append(["event": "selftest", "line": line]) },
                                done: { log.append(["event": "selftest_done"]) })
            } else {
                log.append(["event": "selftest_skipped", "reason": "没有 Key"])
            }
        }
        // 预热到 TypeSafe 的连接，第一次预判不用等握手
        if let k = state.apiKey {
            let t0 = CFAbsoluteTimeGetCurrent()
            JevClient(key: k).listModels { [weak self] r in
                let ms = Int((CFAbsoluteTimeGetCurrent() - t0) * 1000)
                DispatchQueue.main.async {
                    switch r {
                    case .success: self?.state.jevStatus = "启动时连接正常（\(ms) ms）"
                    case .failure(let e): self?.state.jevStatus = "启动时连接失败（\(ms) ms）：\(e.description)"
                    }
                }
            }
        }
    }

    /// 已在运行时再次打开 App：显示权限与设置
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showSettings()
        return true
    }

    // MARK: 菜单

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        let status = NSMenuItem(title: "辅助功能 \(state.axTrusted ? "✓" : "✗")   屏幕录制 \(state.screenTrusted ? "✓" : "✗")   \(state.apiKey == nil ? "模拟模式" : "Jev")", action: nil, keyEquivalent: "")
        status.isEnabled = false
        menu.addItem(status)
        menu.addItem(.separator())
        let toggle = item("停留自动预判", #selector(togglePrediction))
        toggle.state = state.predictionEnabled ? .on : .off
        menu.addItem(toggle)
        menu.addItem(item("立刻预判一次    ⌃⌥P", #selector(predictNow)))
        menu.addItem(item("点击预判目标    ⌃⌥↩", #selector(clickPredicted)))
        menu.addItem(.separator())
        menu.addItem(item(circle.active ? "完成圈选    ⌃⌥C" : "开始圈选    ⌃⌥C", #selector(toggleCircle)))
        menu.addItem(item("灵感库（\(state.library.count)）    ⌃⌥L", #selector(openLibrary)))
        menu.addItem(.separator())
        menu.addItem(item("快速搜索    ⌃⌥S", #selector(quickSearch)))
        let hint = NSMenuItem(title: "图片翻页 ⌃⌥← →（按住连续）· 点赞 ⌃⌥1 · 收藏 ⌃⌥2 · 投币 ⌃⌥3 · 关注 ⌃⌥4 · 撤销 ⌃⌥Z", action: nil, keyEquivalent: "")
        hint.isEnabled = false
        menu.addItem(hint)
        let target = item(state.targetModeOn ? "目标模式：\(state.userGoal.prefix(16))    ⌃⌥G" : "目标模式    ⌃⌥G", #selector(toggleTarget))
        target.state = state.targetModeOn ? .on : .off
        menu.addItem(target)
        menu.addItem(item("下一条相关的    ⌃⌥N", #selector(nextCard)))
        menu.addItem(item("关闭弹窗    ⌃⌥X", #selector(closePopup)))
        menu.addItem(item("打包所选灵感给 agent    ⌃⌥K", #selector(packSelected)))
        menu.addItem(.separator())
        menu.addItem(item("调试面板    ⌃⌥D", #selector(openDebug)))
        menu.addItem(item("权限与设置…", #selector(openSettings)))
        menu.addItem(item("打开日志文件夹", #selector(openLogs)))
        menu.addItem(.separator())
        menu.addItem(item("退出", #selector(quit)))
    }

    private func item(_ title: String, _ sel: Selector) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: sel, keyEquivalent: "")
        i.target = self
        return i
    }

    @objc func togglePrediction() { state.predictionEnabled.toggle(); if !state.predictionEnabled { overlay.clearPrediction() } }
    @objc func predictNow() { predictor.triggerNow() }
    @objc func clickPredicted() { predictor.clickPredicted() }
    @objc func toggleCircle() { circle.toggle() }
    @objc func openLibrary() { showLibrary() }
    @objc func quickSearch() { openQuickSearch() }
    @objc func toggleTarget() { targetMode.toggle() }
    @objc func nextCard() { targetMode.next() }
    @objc func closePopup() { popupCloser.run() }
    @objc func packSelected() { packHotkey() }
    @objc func openDebug() { showDebug() }
    @objc func openSettings() { showSettings() }
    @objc func openLogs() { NSWorkspace.shared.open(JSONLLog.directory) }
    @objc func quit() { NSApp.terminate(nil) }

    // MARK: 窗口

    func closeWindow(_ key: String) {
        windows[key]?.close()
        windows[key] = nil
    }

    /// 投币、关注前的确认框；确认后回到原来的应用再执行
    func showConfirm(_ text: String, _ go: @escaping () -> Void) {
        let prev = NSWorkspace.shared.frontmostApplication
        closeWindow("confirm")
        let view = ConfirmView(text: text, onConfirm: { [weak self] in
            self?.closeWindow("confirm")
            prev?.activate()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2, execute: go)
        }, onCancel: { [weak self] in
            self?.closeWindow("confirm")
            prev?.activate()
            actionLog.append(["event": "action_cancelled"])
            self?.overlay.toast("已取消", seconds: 1.0)
        })
        show("confirm", title: "确认", view, floating: true)
    }

    func show<V: View>(_ key: String, title: String, _ view: V, floating: Bool = false) {
        if let w = windows[key] {
            NSApp.activate(ignoringOtherApps: true)
            w.makeKeyAndOrderFront(nil)
            return
        }
        let w = NSWindow(contentViewController: NSHostingController(rootView: view))
        w.title = title
        w.styleMask = [.titled, .closable, .miniaturizable, .resizable]
        w.isReleasedWhenClosed = false
        if floating { w.level = .floating }
        w.center()
        windows[key] = w
        NSApp.activate(ignoringOtherApps: true)
        w.makeKeyAndOrderFront(nil)
    }

    func showSettings() { show("settings", title: "权限与设置", SettingsView(state: state)) }

    func showLibrary() {
        state.reloadLibrary()
        show("library", title: "灵感库", LibraryView(state: state, actions: libraryActions))
    }

    /// 目标模式没有目标时问一句“这次在找什么”
    func showGoal(_ done: @escaping (String) -> Void) {
        let prev = NSWorkspace.shared.frontmostApplication
        let isSelf = prev?.bundleIdentifier == Bundle.main.bundleIdentifier
        closeWindow("goal")
        let view = GoalView(goal: state.userGoal, onSubmit: { [weak self] g in
            self?.closeWindow("goal")
            if !isSelf { prev?.activate() }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { done(g) }
        }, onCancel: { [weak self] in
            self?.closeWindow("goal")
            if !isSelf { prev?.activate() }
        })
        show("goal", title: "目标模式", view, floating: true)
    }

    func showDebug() {
        show("debug", title: "点击预判 · 调试", DebugView(state: state,
                                                       onPredict: { [weak self] in self?.predictor.triggerNow() },
                                                       onClick: { [weak self] in self?.predictor.clickPredicted() },
                                                       onMark: { [weak self] ok in self?.predictor.mark(correct: ok) }),
             floating: true)
    }

    func showIntent(_ d: CircleController.Draft) {
        windows["intent"]?.close()
        windows["intent"] = nil
        let close: () -> Void = { [weak self] in
            self?.windows["intent"]?.close()
            self?.windows["intent"] = nil
            d.previousApp?.activate()
        }
        let view = IntentView(draft: d, projects: state.store.projects(), onSave: { [weak self] text, project in
            self?.saveInspiration(d, intent: text, project: project)
            close()
        }, onCancel: {
            self.circleLog.append(["event": "circle_cancelled", "app": d.context.appName ?? "", "url": d.context.url ?? ""])
            close()
        })
        show("intent", title: "存进灵感库", view, floating: true)
    }

    private func saveInspiration(_ d: CircleController.Draft, intent: String, project: ProjectChoice) {
        // 意图里的 #标签 拿出来当标签
        let (text, tags) = Hashtags.extract(intent.trimmingCharacters(in: .whitespacesAndNewlines))
        var item = InspirationItem(intent: text, context: d.context, texts: d.texts, rect: d.rect)
        item.tags = tags.isEmpty ? nil : tags
        switch project {
        case .auto: break
        case .none: item.projectSource = "user"
        case .named(let p): item.project = p; item.projectSource = "user"
        }
        do {
            item = try state.store.save(item, png: d.png)
        } catch {
            NSSound.beep()
            circleLog.append(["event": "save_failed", "error": "\(error)"])
            return
        }
        state.reloadLibrary()
        circleLog.append(["event": "saved", "id": item.id, "intent": text, "tags": tags, "project": item.project ?? "",
                          "app": d.context.appName ?? "",
                          "window_title": d.context.windowTitle ?? "", "url": d.context.url ?? "",
                          "has_image": d.png != nil, "capture_note": d.captureNote ?? "", "texts": d.texts,
                          "rect": [d.rect.minX, d.rect.minY, d.rect.width, d.rect.height]])
        organize(item)
    }
}
