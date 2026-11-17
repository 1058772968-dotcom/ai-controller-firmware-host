import Carbon.HIToolbox
import Foundation

/// 全局快捷键（Carbon RegisterEventHotKey：不需要额外权限）
final class HotKeys {
    static let shared = HotKeys()
    static let ctrlOpt = UInt32(controlKey | optionKey)

    enum ID: UInt32 {
        case predict = 1, circle, library, clickPredicted, debug, escape
        case search, flipNext, flipPrev, like, collect, coin, follow, undo
        case targetMode, nextCard, closePopup, pack
    }

    private var handlers: [UInt32: () -> Void] = [:]
    private var releaseHandlers: [UInt32: () -> Void] = [:]
    private var refs: [UInt32: EventHotKeyRef] = [:]
    private var installed = false

    @discardableResult
    func register(_ id: ID, keyCode: Int, modifiers: UInt32, _ handler: @escaping () -> Void) -> Bool {
        install()
        unregister(id)
        var ref: EventHotKeyRef?
        let hk = EventHotKeyID(signature: OSType(0x4149_4B49), id: id.rawValue)  // 'AIKI'
        let st = RegisterEventHotKey(UInt32(keyCode), modifiers, hk, GetApplicationEventTarget(), 0, &ref)
        guard st == noErr, let ref else { return false }
        refs[id.rawValue] = ref
        handlers[id.rawValue] = handler
        return true
    }

    func unregister(_ id: ID) {
        if let r = refs[id.rawValue] { UnregisterEventHotKey(r) }
        refs[id.rawValue] = nil
        handlers[id.rawValue] = nil
        releaseHandlers[id.rawValue] = nil
    }

    /// 松开快捷键时调用（按住连续翻页用）
    func onRelease(_ id: ID, _ handler: @escaping () -> Void) { releaseHandlers[id.rawValue] = handler }

    fileprivate func fire(_ id: UInt32) { handlers[id]?() }
    fileprivate func fireRelease(_ id: UInt32) { releaseHandlers[id]?() }

    private func install() {
        guard !installed else { return }
        installed = true
        var specs = [EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
                     EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased))]
        InstallEventHandler(GetApplicationEventTarget(), { _, event, _ -> OSStatus in
            var hk = EventHotKeyID()
            GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                              nil, MemoryLayout<EventHotKeyID>.size, nil, &hk)
            let id = hk.id
            let released = GetEventKind(event) == UInt32(kEventHotKeyReleased)
            DispatchQueue.main.async { released ? HotKeys.shared.fireRelease(id) : HotKeys.shared.fire(id) }
            return noErr
        }, 2, &specs, nil, nil)
    }
}
