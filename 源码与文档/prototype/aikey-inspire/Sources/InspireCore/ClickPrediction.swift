import Foundation
import CoreGraphics

/// 指针停下前的运动
public struct PointerMotion: Codable, Equatable {
    public var x: Double
    public var y: Double
    public var dx: Double
    public var dy: Double
    public var speed: Double
    public var text: String
    public init(x: Double, y: Double, dx: Double, dy: Double, speed: Double, text: String) {
        self.x = x; self.y = y; self.dx = dx; self.dy = dy; self.speed = speed; self.text = text
    }
}

/// 一次预判的全部输入
public struct ClickSnapshot {
    public var context: ScreenContext
    public var pointer: PointerMotion
    public var candidates: [CandidateInfo]
    public var userGoal: String?
    public init(context: ScreenContext, pointer: PointerMotion, candidates: [CandidateInfo], userGoal: String?) {
        self.context = context; self.pointer = pointer; self.candidates = candidates; self.userGoal = userGoal
    }
}

/// 解析后的回答
public struct ClickAnswer: Codable, Equatable {
    public var choice: String
    public var confidence: Double?
    public var probabilities: [String: Double]
    public var aboutToClick: Double?
    public var model: String?
    public var inputTokens: Int?
    public init(choice: String, confidence: Double?, probabilities: [String: Double], aboutToClick: Double?,
                model: String? = nil, inputTokens: Int? = nil) {
        self.choice = choice; self.confidence = confidence; self.probabilities = probabilities
        self.aboutToClick = aboutToClick; self.model = model; self.inputTokens = inputTokens
    }
}

public enum ClickQuestions {
    public static let noneId = "none"
    public static let model = "jev-latest"

    public static let targetInstructions = """
    Which element in `candidates` is the user most likely about to click? \
    Weigh how close it is to the pointer (`candidates[].distance_px`, where 0 means the pointer is on it), \
    whether it lies in the direction the pointer was moving (`pointer.recent_motion` and `candidates[].direction_from_pointer`), \
    and, when present, how well its label fits `user_goal` and the page described by `window_title`. \
    Choose none if the user seems to be resting the pointer or reading rather than aiming at one of them.
    """

    public static let aboutToClickInstructions = """
    Given `pointer.recent_motion` and the elements in `candidates`, is the user aiming at something to click \
    right now, rather than resting the pointer or reading?
    """

    /// 发给 POST /v1/systemone 的请求体（问题 id 只给代码用，模型看不到）
    public static func requestBody(_ s: ClickSnapshot, model: String = model) -> [String: Any] {
        var state: [String: Any] = [
            "device": "The user points with a handheld gyroscope air mouse, which is less precise than a desk mouse. The pointer has just stopped moving.",
            "app": s.context.appName ?? "unknown",
            "pointer": [
                "x": Int(s.pointer.x.rounded()),
                "y": Int(s.pointer.y.rounded()),
                "recent_motion": s.pointer.text,
                "speed_px_per_s": Int(s.pointer.speed.rounded()),
            ] as [String: Any],
            "candidates": s.candidates.map { c -> [String: Any] in
                [
                    "id": c.id,
                    "kind": c.kind,
                    "label": c.label,
                    "distance_px": Int(c.distance.rounded()),
                    "direction_from_pointer": c.direction,
                    "size_px": "\(Int(c.w.rounded()))x\(Int(c.h.rounded()))",
                ]
            },
        ]
        if let t = s.context.windowTitle { state["window_title"] = t }
        if let u = s.context.url { state["page_url"] = u }
        if let g = s.userGoal?.trimmingCharacters(in: .whitespacesAndNewlines), !g.isEmpty { state["user_goal"] = g }

        var criteria: [String: String] = [:]
        for c in s.candidates { criteria[c.id] = "\(c.kind) “\(c.label)”" }
        criteria[noneId] = "None of the listed elements; the user is not about to click any of them"

        return [
            "model": model,
            "state": state,
            "questions": [
                "target": ["type": "choice", "instructions": targetInstructions, "criteria": criteria] as [String: Any],
                "about_to_click": ["type": "noul", "instructions": aboutToClickInstructions] as [String: Any],
            ] as [String: Any],
        ]
    }

    public enum ParseError: Error, CustomStringConvertible {
        case malformed(String)
        public var description: String { if case .malformed(let s) = self { return s }; return "" }
    }

    /// 解析 System One 回复；答案按问题 id 取
    public static func parse(_ data: Data) throws -> ClickAnswer {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let answers = root["answers"] as? [String: Any],
              let target = answers["target"] as? [String: Any],
              let choice = target["choice"] as? String else {
            throw ParseError.malformed("回复里没有 answers.target.choice")
        }
        var probs: [String: Double] = [:]
        for (k, v) in (target["probabilities"] as? [String: Any]) ?? [:] {
            if let d = (v as? NSNumber)?.doubleValue { probs[k] = d }
        }
        let noul = ((answers["about_to_click"] as? [String: Any])?["noul"] as? NSNumber)?.doubleValue
        let usage = root["usage"] as? [String: Any]
        return ClickAnswer(choice: choice, confidence: (target["confidence"] as? NSNumber)?.doubleValue,
                           probabilities: probs, aboutToClick: noul, model: root["model"] as? String,
                           inputTokens: (usage?["input_tokens"] as? NSNumber)?.intValue)
    }

    /// 没有 API Key 时的本地替身：只按距离和运动方向打分。用来调界面和日志，不代表 Jev 的判断。
    public static func mock(_ s: ClickSnapshot) -> ClickAnswer {
        let moveDir = Geometry.direction(dx: s.pointer.dx, dy: s.pointer.dy)
        var w: [String: Double] = [:]
        for c in s.candidates {
            var v = exp(-c.distance / 45)
            if c.direction == "under_pointer" { v *= 2.0 }
            if c.direction == moveDir { v *= 1.4 }
            w[c.id] = v
        }
        w[noneId] = s.pointer.speed < 40 ? 0.35 : 0.12
        let sum = w.values.reduce(0, +)
        var p: [String: Double] = [:]
        for (k, v) in w { p[k] = sum > 0 ? v / sum : 0 }
        let best = p.max { $0.value < $1.value }?.key ?? noneId
        // 置信度：1 - 归一化熵
        let n = Double(max(p.count, 2))
        let h = -p.values.filter { $0 > 0 }.reduce(0) { $0 + $1 * log($1) }
        let conf = max(0, min(1, 1 - h / log(n)))
        return ClickAnswer(choice: best, confidence: (conf * 100).rounded() / 100, probabilities: p,
                           aboutToClick: s.candidates.isEmpty ? 0 : (s.pointer.speed > 40 ? 0.7 : 0.4), model: "mock")
    }

    /// 两次扫描的候选是否实质相同（用于跳过重复请求）
    public static func signature(_ cs: [CandidateInfo]) -> String {
        cs.map { "\($0.role)|\($0.label)|\(Int($0.x))|\(Int($0.y))" }.joined(separator: ";")
    }
}

/// 停留检测：先移动超过 armDistance，再在 stillRadius 内停 dwellSeconds，触发一次。
/// 一直不动不会重复触发；必须重新移动才会再次“上膛”。
public struct DwellDetector {
    public var dwellSeconds: Double
    public var stillRadius: Double
    public var armDistance: Double
    private var anchor: CGPoint?
    private var anchorTime: Double = 0
    private var movedSinceFire: Double = 0
    private var last: CGPoint?
    public private(set) var trail: [(t: Double, p: CGPoint)] = []

    public init(dwellSeconds: Double = 0.55, stillRadius: Double = 6, armDistance: Double = 24) {
        self.dwellSeconds = dwellSeconds; self.stillRadius = stillRadius; self.armDistance = armDistance
    }

    public mutating func feed(_ p: CGPoint, at t: Double) -> Bool {
        last = p
        trail.append((t, p))
        trail.removeAll { t - $0.t > 2.0 }
        if let a = anchor, Double(hypot(p.x - a.x, p.y - a.y)) <= stillRadius {
            if movedSinceFire >= armDistance && t - anchorTime >= dwellSeconds {
                movedSinceFire = 0
                return true
            }
            return false
        }
        // 只在离开静止圈时累计位移：陀螺仪静止时的小抖动不会让它重新上膛
        if let a = anchor { movedSinceFire += Double(hypot(p.x - a.x, p.y - a.y)) }
        anchor = p
        anchorTime = t
        return false
    }

    /// 停下之前 window 秒内的位移
    public func motion(window: Double = 0.5) -> PointerMotion {
        guard let end = anchor ?? last else { return PointerMotion(x: 0, y: 0, dx: 0, dy: 0, speed: 0, text: "no recent movement") }
        let start = trail.first { anchorTime - $0.t <= window }?.p ?? end
        let dx = Double(end.x - start.x), dy = Double(end.y - start.y)
        let dist = (dx * dx + dy * dy).squareRoot()
        let speed = dist / window
        let text: String
        if dist < 8 {
            text = "barely moved in the last \(window) s before stopping"
        } else {
            text = "moved \(Geometry.direction(dx: dx, dy: dy)) about \(Int(dist.rounded())) px in the last \(window) s, then stopped"
        }
        return PointerMotion(x: Double(end.x), y: Double(end.y), dx: dx, dy: dy, speed: speed, text: text)
    }
}
