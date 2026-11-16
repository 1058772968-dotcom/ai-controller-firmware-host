import Carbon.HIToolbox
import Foundation

/// 全局快捷键（Carbon RegisterEventHotKey：不需要额外权限）
final class HotKeys {
    static let shared = HotKeys()
    static let ctrlOpt = UInt32(controlKey | optionKey)

    enum ID: UInt32 {
        case predict = 1, circle, library, clickPredicted, debug, escape
    }

    private var handlers: [UInt32: () -> Void] = [:]
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
    }

    fileprivate func fire(_ id: UInt32) { handlers[id]?() }

    private func install() {
        guard !installed else { return }
        installed = true
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, event, _ -> OSStatus in
            var hk = EventHotKeyID()
            GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                              nil, MemoryLayout<EventHotKeyID>.size, nil, &hk)
            let id = hk.id
            DispatchQueue.main.async { HotKeys.shared.fire(id) }
            return noErr
        }, 1, &spec, nil, nil)
    }
}
