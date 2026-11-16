// swift-tools-version:5.10
// AI KEY 灵感圈：光标交互 MVP（Jev 点击预判 + 圈选灵感 + 灵感库）
import PackageDescription

let package = Package(
    name: "AIKeyInspire",
    platforms: [.macOS(.v14)],
    targets: [
        // 纯逻辑与系统接口封装：辅助功能候选枚举、Jev 请求/解析、模拟预判、停留检测、灵感库、日志
        .target(name: "InspireCore", path: "Sources/InspireCore"),
        // 菜单栏 App
        .executableTarget(name: "AIKeyInspire", dependencies: ["InspireCore"], path: "Sources/AIKeyInspire"),
        // 命令行探针：不装 App 也能在终端里验证候选枚举、请求体和截图
        .executableTarget(name: "inspire-probe", dependencies: ["InspireCore"], path: "Sources/inspire-probe"),
        .testTarget(name: "InspireCoreTests", dependencies: ["InspireCore"], path: "Tests/InspireCoreTests"),
    ]
)
