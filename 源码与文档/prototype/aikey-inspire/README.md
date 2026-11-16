# AI KEY 灵感圈（光标交互 MVP）

对应需求：拿控制器当鼠标，躺在床上逛小红书、用 Google 搜东西；看到喜欢的，**圈起来、说明意图、存进灵感库**，再把灵感**丢进 agent**。另加一层 **Jev 点击预判**：陀螺仪指针不如鼠标准，光标停下时，Jev 判断你想点哪个按钮，并把它高亮出来。

原生 macOS 菜单栏 App（Swift），不占 Dock。控制器本身就是 HID 鼠标，“当鼠标用”不需要这个 App。

## 现在能做什么

| 功能 | 怎么用 | 说明 |
|---|---|---|
| 点击预判 | 移动光标后停住约 0.55 秒自动触发；`⌃⌥P` 立刻预判 | 用辅助功能读光标周围 150 px 内能点的元素（最多 20 个），交给 Jev 选一个，绿色框 = 置信度 ≥ 0.5，橙色 = 拿不准 |
| 点预判目标 | `⌃⌥↩` | 先对目标执行辅助功能的“按下”，不支持再在中心模拟一次点击 |
| 圈选 | `⌃⌥C` 开始 → 移动光标画圈 → `⌃⌥C` 完成，`Esc` 取消 | 截下圈住的范围，记录软件、窗口标题、网址、圈内文字 |
| 说明意图 | 圈完弹出输入框，回车保存 | 保存后 Jev 给灵感分类（配色、排版、产品造型、交互、文案、摄影构图、素材、其他） |
| 灵感库 | `⌃⌥L` | 卡片可以直接拖进 agent 对话框（图片 + 说明文字），或点“复制”后粘贴 |
| 调试面板 | `⌃⌥D` | 每次预判的候选、概率、置信度、耗时、请求 JSON；可写“当前目标”、标记猜对或猜错 |

还没做：控制器 S 键圈选、按住 V 用语音说意图（板上按键还没接好，见 E24 部署调试归档）；截图 + Box 兜底（读不到辅助功能信息的软件）；吸附点击。

## 编译和安装

```bash
./build.sh run
```

生成 `~/Applications/AI KEY 灵感圈.app`，用本机 Apple Development 证书签名（证书名不会打印出来）。签名身份固定，重新编译后已授的权限还在。中间文件放在 `~/.cache/ai-key-inspire/`，不进 iCloud。

```bash
./build.sh test
```

## 权限

| 权限 | 用途 | 没有时 |
|---|---|---|
| 辅助功能 | 读光标附近的元素、圈内文字、执行“点它” | 预判找不到候选 |
| 屏幕录制 | 圈选截图 | 灵感只存文字和来源；授权后要重开 App |

首次启动会弹系统授权框。也可以在菜单 → 权限与设置里查看状态、打开系统设置。

## Jev（TypeSafe）

- API Key 存在本机钥匙串（服务名 `com.aikey.inspire.typesafe`），App 的“权限与设置”里可以保存、测试、删除；也接受环境变量 `TYPESAFE_API_KEY`，环境变量优先。Key 不写日志，不进仓库。
- 没有 Key 时自动用**模拟模式**：只按距离和运动方向打分，用来调界面，不代表 Jev 的判断。
- 每次预判一个请求，两个问题并行：
  - `target`（Choice）：候选 `c1…cN` 加 `none`；
  - `about_to_click`（Noul）：是否正在瞄准某个要点的东西。
- 状态里有：软件名、窗口标题、网址、指针位置和停下前 0.5 秒的移动、候选（类型、文字、距离、方向、尺寸），以及可选的“当前目标”。**这些会发给 TypeSafe，截图不发。**
- 两次自动请求至少间隔 0.8 秒；同一位置、同一批候选不重复请求；指着灵感圈自己的窗口不预判。

## 调试

- 日志：`~/Library/Logs/AIKeyInspire/predictions.jsonl`（每次预判一行：候选、概率、耗时、来源、是否过期）、`circles.jsonl`（圈选、保存、分类）。
- 灵感库：`~/Library/Application Support/AIKeyInspire/Library/<id>/`（`item.json` + `shot.png`）。删除会移到废纸篓。
- 命令行探针（不用装 App；运行它的终端要有辅助功能权限）：

```bash
~/.cache/ai-key-inspire/build/release/inspire-probe scan
```

```bash
~/.cache/ai-key-inspire/build/release/inspire-probe watch 20
```

```bash
TYPESAFE_API_KEY="$(security find-generic-password -s com.aikey.inspire.typesafe -a default -w)" ~/.cache/ai-key-inspire/build/release/inspire-probe demo
```

`scan` 枚举光标附近的候选并打印请求体；`watch` 跟随光标，每次停留扫描一次；`demo` 把 4 个人造场景发给 Jev（不含真实屏幕内容）；`capture x y w h out.png` 截图；`texts x y w h` 读区域内文字。

## 代码结构

| 路径 | 内容 |
|---|---|
| `Sources/InspireCore/AXSupport.swift` | 辅助功能读取封装、坐标换算 |
| `Sources/InspireCore/Candidates.swift` | 环形采样命中测试、可点击元素判定、上下文（软件/窗口/网址）、圈内文字 |
| `Sources/InspireCore/ClickPrediction.swift` | Jev 请求体、回复解析、模拟预判、停留检测 |
| `Sources/InspireCore/Jev.swift` | TypeSafe HTTP 客户端（共用连接）、钥匙串 |
| `Sources/InspireCore/Library.swift` | 灵感条目、灵感库、分类问题、JSONL 日志 |
| `Sources/InspireCore/Capture.swift` | 截图（ScreenCaptureKit，失败退回 `screencapture`） |
| `Sources/AIKeyInspire/` | 菜单栏、浮层、快捷键、预判调度、圈选、SwiftUI 窗口 |
| `Sources/inspire-probe/` | 命令行探针 |
| `Tests/InspireCoreTests/` | 请求格式、回复解析、模拟预判、停留检测、灵感库 |
