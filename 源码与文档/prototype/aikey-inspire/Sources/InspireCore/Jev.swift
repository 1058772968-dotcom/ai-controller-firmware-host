import Foundation
import Security

public enum JevError: Error, CustomStringConvertible {
    case noKey
    case http(Int, String)
    case transport(String)
    case decode(String)

    public var description: String {
        switch self {
        case .noKey: return "没有 TypeSafe API Key"
        case .http(let code, let body):
            let hint: String
            switch code {
            case 401: hint = "Key 无效或缺失"
            case 422: hint = "请求格式不对"
            case 429: hint = "超出频率限制"
            case 529: hint = "TypeSafe 暂时过载"
            default: hint = "HTTP 错误"
            }
            return "\(hint)（\(code)）\(body.prefix(300))"
        case .transport(let s): return "网络错误：\(s)"
        case .decode(let s): return "解析错误：\(s)"
        }
    }
}

/// TypeSafe System One 的最小 HTTP 客户端（官方没有 Swift SDK）。Key 只放在 Authorization 头里，不写日志。
public final class JevClient {
    public static let base = URL(string: "https://api.typesafe.ai")!
    private let key: String
    private let session: URLSession

    /// 所有客户端共用一个会话：连接保持复用，免得每次请求都重新握手（实测新建会话每次多 1 秒以上）
    private static let sharedSession: URLSession = {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.timeoutIntervalForRequest = 6
        cfg.httpMaximumConnectionsPerHost = 2
        return URLSession(configuration: cfg)
    }()

    public init(key: String) {
        self.key = key
        session = JevClient.sharedSession
    }

    public func systemOne(_ body: [String: Any], completion: @escaping (Result<Data, JevError>) -> Void) {
        var req = URLRequest(url: JevClient.base.appendingPathComponent("v1/systemone"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        do {
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        } catch {
            completion(.failure(.decode("请求体无法编码：\(error)")))
            return
        }
        send(req, completion: completion)
    }

    /// GET /v1/models：用来检查 Key 是否可用
    public func listModels(completion: @escaping (Result<Data, JevError>) -> Void) {
        var req = URLRequest(url: JevClient.base.appendingPathComponent("v1/models"))
        req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        send(req, completion: completion)
    }

    private func send(_ req: URLRequest, completion: @escaping (Result<Data, JevError>) -> Void) {
        session.dataTask(with: req) { data, resp, err in
            if let err { completion(.failure(.transport(err.localizedDescription))); return }
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            let body = data ?? Data()
            guard (200..<300).contains(code) else {
                completion(.failure(.http(code, String(data: body, encoding: .utf8) ?? "")))
                return
            }
            completion(.success(body))
        }.resume()
    }
}

/// API Key 存在系统钥匙串；环境变量 TYPESAFE_API_KEY 优先（从终端启动、命令行探针用）。
public enum KeyStore {
    public static let service = "com.aikey.inspire.typesafe"
    public static let account = "default"

    public static func load() -> (key: String, source: String)? {
        if let e = ProcessInfo.processInfo.environment["TYPESAFE_API_KEY"], !e.isEmpty {
            return (e, "环境变量")
        }
        let q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var out: CFTypeRef?
        if SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess,
           let d = out as? Data, let s = String(data: d, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines), !s.isEmpty {
            return (s, "钥匙串")
        }
        return nil
    }

    @discardableResult
    public static func save(_ key: String) -> Bool {
        let k = key.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !k.isEmpty, let data = k.data(using: .utf8) else { return false }
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        let st = SecItemUpdate(base as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if st == errSecSuccess { return true }
        var add = base
        add[kSecValueData as String] = data
        add[kSecAttrLabel as String] = "AI KEY 灵感圈 · TypeSafe API Key"
        return SecItemAdd(add as CFDictionary, nil) == errSecSuccess
    }

    public static func delete() {
        let q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(q as CFDictionary)
    }
}
