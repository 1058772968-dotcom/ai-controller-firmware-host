import ApplicationServices
import AppKit

/// 辅助功能接口的小封装。坐标一律是全局坐标、左上角为原点、单位是点（与 AX 和 CGEvent 一致）。
public enum AX {
    public static func copy(_ el: AXUIElement, _ attr: String) -> CFTypeRef? {
        var v: CFTypeRef?
        return AXUIElementCopyAttributeValue(el, attr as CFString, &v) == .success ? v : nil
    }

    public static func string(_ el: AXUIElement, _ attr: String) -> String? {
        guard let s = copy(el, attr) as? String else { return nil }
        let t = clean(s)
        return t.isEmpty ? nil : t
    }

    /// 去掉不可见的格式字符（Unicode Cf：零宽空格、零宽连接符、BOM 等）再去首尾空白。
    /// 飞书等网页的标题里会夹带这类字符，原样存下来或发给 Jev 都是噪声。
    public static func clean(_ s: String) -> String {
        var u = String.UnicodeScalarView()
        u.append(contentsOf: s.unicodeScalars.filter { $0.properties.generalCategory != .format })
        return String(u).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    public static func element(_ el: AXUIElement, _ attr: String) -> AXUIElement? {
        guard let v = copy(el, attr), CFGetTypeID(v) == AXUIElementGetTypeID() else { return nil }
        return (v as! AXUIElement)
    }

    public static func children(_ el: AXUIElement) -> [AXUIElement] {
        (copy(el, "AXChildren") as? [AXUIElement]) ?? []
    }

    public static func role(_ el: AXUIElement) -> String { string(el, "AXRole") ?? "" }

    public static func frame(_ el: AXUIElement) -> CGRect? {
        guard let p = copy(el, "AXPosition"), let s = copy(el, "AXSize"),
              CFGetTypeID(p) == AXValueGetTypeID(), CFGetTypeID(s) == AXValueGetTypeID() else { return nil }
        var pt = CGPoint.zero, sz = CGSize.zero
        guard AXValueGetValue(p as! AXValue, .cgPoint, &pt), AXValueGetValue(s as! AXValue, .cgSize, &sz) else { return nil }
        return CGRect(origin: pt, size: sz)
    }

    public static func actions(_ el: AXUIElement) -> [String] {
        var names: CFArray?
        guard AXUIElementCopyActionNames(el, &names) == .success else { return [] }
        return (names as? [String]) ?? []
    }

    public static func pid(_ el: AXUIElement) -> pid_t? {
        var p: pid_t = 0
        return AXUIElementGetPid(el, &p) == .success ? p : nil
    }

    public static func url(_ el: AXUIElement) -> String? {
        if let u = copy(el, "AXURL") as? URL { return u.absoluteString }
        return string(el, "AXURL")
    }

    /// 屏幕坐标（左上原点）下，指针所在位置最上层的元素
    public static func hit(_ system: AXUIElement, _ p: CGPoint) -> AXUIElement? {
        var el: AXUIElement?
        return AXUIElementCopyElementAtPosition(system, Float(p.x), Float(p.y), &el) == .success ? el : nil
    }

    public static var trusted: Bool { AXIsProcessTrusted() }

    /// 弹系统授权框（只会在未授权时弹）
    @discardableResult
    public static func requestTrust() -> Bool {
        let opts = ["AXTrustedCheckOptionPrompt": true] as CFDictionary
        return AXIsProcessTrustedWithOptions(opts)
    }
}

/// 让 AXUIElement 能放进 Set / 字典
struct AXKey: Hashable {
    let el: AXUIElement
    static func == (a: AXKey, b: AXKey) -> Bool { CFEqual(a.el, b.el) }
    func hash(into h: inout Hasher) { h.combine(CFHash(el)) }
}

/// 屏幕坐标换算：AX（左上原点）↔ Cocoa（左下原点，以主屏为基准）
public enum ScreenGeometry {
    public static var primaryHeight: CGFloat { NSScreen.screens.first?.frame.height ?? 0 }

    public static func axToCocoa(_ p: CGPoint) -> CGPoint { CGPoint(x: p.x, y: primaryHeight - p.y) }
    public static func cocoaToAX(_ p: CGPoint) -> CGPoint { CGPoint(x: p.x, y: primaryHeight - p.y) }
    public static func axToCocoa(_ r: CGRect) -> CGRect {
        CGRect(x: r.minX, y: primaryHeight - r.maxY, width: r.width, height: r.height)
    }
    /// 当前指针位置（AX 坐标）
    public static func mouseAX() -> CGPoint { cocoaToAX(NSEvent.mouseLocation) }
}
