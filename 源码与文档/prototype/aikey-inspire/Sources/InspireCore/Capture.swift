import AppKit
import ScreenCaptureKit

/// 截取屏幕的一块（AX 坐标：全局、左上原点、单位点）。需要“屏幕录制”权限。
public enum ScreenCapture {
    public static var trusted: Bool { CGPreflightScreenCaptureAccess() }

    @discardableResult
    public static func requestTrust() -> Bool { CGRequestScreenCaptureAccess() }

    /// 先用 ScreenCaptureKit；不可用或失败时退回系统自带的 screencapture 命令
    public static func png(rectAX: CGRect, completion: @escaping (Data?, String, String?) -> Void) {
        let r = rectAX.integral
        if #available(macOS 15.2, *) {
            Task {
                do {
                    let img = try await SCScreenshotManager.captureImage(in: r)
                    completion(pngData(img), "ScreenCaptureKit", nil)
                } catch {
                    cli(r) { d, err in completion(d, "screencapture", d == nil ? "SCK：\(error.localizedDescription)；\(err ?? "")" : nil) }
                }
            }
        } else {
            cli(r) { d, err in completion(d, "screencapture", err) }
        }
    }

    static func pngData(_ img: CGImage) -> Data? {
        NSBitmapImageRep(cgImage: img).representation(using: .png, properties: [:])
    }

    static func cli(_ r: CGRect, completion: @escaping (Data?, String?) -> Void) {
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("aikey-inspire-\(UUID().uuidString).png")
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        p.arguments = ["-x", "-R", "\(Int(r.minX)),\(Int(r.minY)),\(Int(r.width)),\(Int(r.height))", tmp.path]
        p.terminationHandler = { proc in
            let d = try? Data(contentsOf: tmp)
            try? FileManager.default.removeItem(at: tmp)
            completion(d, d == nil ? "screencapture 退出码 \(proc.terminationStatus)" : nil)
        }
        do { try p.run() } catch { completion(nil, "screencapture 启动失败：\(error.localizedDescription)") }
    }
}
