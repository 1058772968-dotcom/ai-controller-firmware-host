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
    private var windows: [String: NSWindow] = [:]

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

        let hk = HotKeys.shared
        hk.register(.predict, keyCode: 0x23, modifiers: HotKeys.ctrlOpt) { [weak self] in self?.predictor.triggerNow() }       // P
        hk.register(.clickPredicted, keyCode: 0x24, modifiers: HotKeys.ctrlOpt) { [weak self] in self?.predictor.clickPredicted() } // Return
        hk.register(.circle, keyCode: 0x08, modifiers: HotKeys.ctrlOpt) { [weak self] in self?.circle.toggle() }              // C
        hk.register(.library, keyCode: 0x25, modifiers: HotKeys.ctrlOpt) { [weak self] in self?.showLibrary() }               // L
        hk.register(.debug, keyCode: 0x02, modifiers: HotKeys.ctrlOpt) { [weak self] in self?.showDebug() }                   // D

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
    @objc func openDebug() { showDebug() }
    @objc func openSettings() { showSettings() }
    @objc func openLogs() { NSWorkspace.shared.open(JSONLLog.directory) }
    @objc func quit() { NSApp.terminate(nil) }

    // MARK: 窗口

    private func show<V: View>(_ key: String, title: String, _ view: V, floating: Bool = false) {
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
        show("library", title: "灵感库", LibraryView(state: state))
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
        let view = IntentView(draft: d, onSave: { [weak self] text in
            self?.saveInspiration(d, intent: text)
            close()
        }, onCancel: {
            self.circleLog.append(["event": "circle_cancelled", "app": d.context.appName ?? "", "url": d.context.url ?? ""])
            close()
        })
        show("intent", title: "存进灵感库", view, floating: true)
    }

    private func saveInspiration(_ d: CircleController.Draft, intent: String) {
        let text = intent.trimmingCharacters(in: .whitespacesAndNewlines)
        var item = InspirationItem(intent: text, context: d.context, texts: d.texts, rect: d.rect)
        do {
            item = try state.store.save(item, png: d.png)
        } catch {
            NSSound.beep()
            circleLog.append(["event": "save_failed", "error": "\(error)"])
            return
        }
        state.reloadLibrary()
        circleLog.append(["event": "saved", "id": item.id, "intent": text, "app": d.context.appName ?? "",
                          "window_title": d.context.windowTitle ?? "", "url": d.context.url ?? "",
                          "has_image": d.png != nil, "capture_note": d.captureNote ?? "", "texts": d.texts,
                          "rect": [d.rect.minX, d.rect.minY, d.rect.width, d.rect.height]])
        classify(item)
    }

    /// 用 Jev 给灵感分类（没有 Key 时用关键词模拟）
    private func classify(_ item: InspirationItem) {
        let ctx = ScreenContext(appName: item.appName, bundleId: item.bundleId, windowTitle: item.windowTitle, url: item.url)
        guard let key = state.apiKey else {
            var it = item
            it.category = CategoryQuestion.mock(intent: item.intent)
            it.categorySource = "mock"
            try? state.store.update(it)
            state.reloadLibrary()
            return
        }
        let t0 = CFAbsoluteTimeGetCurrent()
        let body = CategoryQuestion.requestBody(intent: item.intent, context: ctx, texts: item.texts)
        JevClient(key: key).systemOne(body) { [weak self] r in
            let ms = (CFAbsoluteTimeGetCurrent() - t0) * 1000
            DispatchQueue.main.async {
                guard let self else { return }
                var it = item
                switch r {
                case .success(let d):
                    if let (c, p) = try? CategoryQuestion.parse(d) {
                        it.category = c; it.categorySource = "jev"; it.categoryProbabilities = p
                    }
                    self.circleLog.append(["event": "category", "id": item.id, "jev_ms": ms, "category": it.category ?? "",
                                           "probabilities": it.categoryProbabilities ?? [:]])
                case .failure(let e):
                    it.category = CategoryQuestion.mock(intent: item.intent); it.categorySource = "mock"
                    self.circleLog.append(["event": "category_failed", "id": item.id, "jev_ms": ms, "error": e.description])
                }
                try? self.state.store.update(it)
                self.state.reloadLibrary()
            }
        }
    }
}
