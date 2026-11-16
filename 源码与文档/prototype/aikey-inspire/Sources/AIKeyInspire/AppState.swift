import AppKit
import Combine
import InspireCore

/// 界面共享状态（只在主线程改）
final class AppState: ObservableObject {
    static let shared = AppState()

    // 权限与 Jev
    @Published var axTrusted = AX.trusted
    @Published var screenTrusted = ScreenCapture.trusted
    @Published var keySource: String? = nil
    var apiKey: String? = nil

    // 开关与设置
    @Published var predictionEnabled = UserDefaults.standard.object(forKey: "predictionEnabled") as? Bool ?? true {
        didSet { UserDefaults.standard.set(predictionEnabled, forKey: "predictionEnabled") }
    }
    @Published var showAllCandidates = UserDefaults.standard.bool(forKey: "showAllCandidates") {
        didSet { UserDefaults.standard.set(showAllCandidates, forKey: "showAllCandidates") }
    }
    @Published var userGoal = UserDefaults.standard.string(forKey: "userGoal") ?? "" {
        didSet { UserDefaults.standard.set(userGoal, forKey: "userGoal") }
    }

    // 最近一次预判
    struct Row: Identifiable {
        let id: String
        let kind: String
        let label: String
        let distance: Double
        let direction: String
        let probability: Double?
    }
    @Published var rows: [Row] = []
    @Published var predicted: String?
    @Published var confidence: Double?
    @Published var aboutToClick: Double?
    @Published var source = "—"
    @Published var scanMs: Double?
    @Published var jevMs: Double?
    @Published var lastError: String?
    @Published var contextText = ""
    @Published var motionText = ""
    @Published var requestJSON = ""
    @Published var lastTime: Date?
    @Published var predictionCount = 0
    @Published var jevStatus = "未测试"

    // 灵感库
    @Published var library: [InspirationItem] = []
    let store = LibraryStore()

    var jevMode: String { apiKey == nil ? "模拟模式（没有 API Key）" : "Jev（Key 来自\(keySource ?? "?")）" }

    func reloadKey() {
        if let (k, src) = KeyStore.load() { apiKey = k; keySource = src } else { apiKey = nil; keySource = nil }
    }

    func reloadLibrary() { library = store.all() }

    func refreshPermissions() {
        let ax = AX.trusted, sc = ScreenCapture.trusted
        if ax != axTrusted { axTrusted = ax }
        if sc != screenTrusted { screenTrusted = sc }
    }
}
