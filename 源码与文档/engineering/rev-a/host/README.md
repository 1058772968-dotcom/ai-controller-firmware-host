# AI KEY 本地工作台

这是 REV A 的可运行电脑端。当前在本机读取 UTF-8 文本、调用本地 whisper / Qwen 模型、显示修改前后对比，并通过独立确认写入文件、读回校验和撤销。默认工作区是 `host/workspace`，附带一份验收文本。

双击 `启动电脑端工作台.command`，再打开 <http://127.0.0.1:8893>。它显式使用固件模拟：C 控制核心和 32 字节协议来自同一份固件源代码，按键输入由电脑提供，没有冒充已连接 USB、BLE 或麦克风硬件。F1/F2 模拟 L/R，F3 模拟语音扳机 V，F4 模拟侧键 S。

侧键短按打开六项菜单，长按圈画。语音扳机按下锁定文件快照，保持后申请电脑麦克风，松开即关闭采集并进入本地识别。首次使用需要浏览器麦克风权限；权限对话框弹出期间松开扳机会取消这次采集，请授权后重新按住。也可导入 16 kHz、16 bit、单声道 PCM WAV，或锁定后直接输入要求。录音上限 60 秒。

“确认发送”仅生成提案，“确认应用到文件”才写入。成功回执包含目标文件、事务 ID 和读回 SHA-256。目标在锁定后或对比后被其他程序更改时会拒绝覆盖；撤销也会拒绝覆盖后来出现的新改动。取消、隐藏和录音期间失焦会关闭采集，迟到的识别或模型结果失效。窗口刷新从当前固件状态建立会话，历史按键不重放。

标注保存文本区域、四角调整后的坐标和关系箭头；锁定时将对应行号映射回文件快照。临时指示 850 毫秒后消失，不发送给模型。当前是本工作区文本上下文，不是全系统截图、其他应用的可访问性信息或已接通的编辑器插件。

## 本机运行环境

模型和原生运行时位于 `~/.cache/ai-key-rev-a/local-ai`，不复制进工程。语音使用 whisper.cpp v1.9.4 / small multilingual；文本使用 llama.cpp v0.5.0 / Qwen2.5-1.5B-Instruct Q4_K_M。模型下载需通过发布者提供的大小和 SHA-256 校验。推理服务只监听回环地址，并使用每次启动生成的访问令牌。

在工程根目录可重建环境和运行验收：

```sh
python3 tools/setup_local_ai.py
python3 tools/validate_host_integration.py
node tools/validate_host_browser.cjs
```

浏览器验收依赖 Playwright；脚本允许用 `PLAYWRIGHT_MODULE` 指定现有模块路径。测试创建独立临时工作区，实际运行本地模型、写入和撤销文件；报告保存在 `reports/host-browser-validation.json`。语音测试录音由 macOS Tingting 合成，其结果不能代表实际麦克风或嘈杂环境识别率。

如需换工作区，可直接启动：

```sh
python3 host/server.py --simulation --workspace /absolute/path/to/text-workspace --port 8893
```

事务日志默认位于 `~/.cache/ai-key-rev-a/host-journal`，包含为恢复而保留的修改前后文本。应用重启不会自动重放未完成事务，也不会自动恢复旧的应用授权。使用其他工作区时可用 `--journal` 指定对应日志目录。

## 当前边界

USB HID、BLE GATT 伴侣接口及 Wi-Fi TLS 语音已实现，并通过电脑端协议与回环验收。当前没有样机，实际 USB 枚举、蓝牙配对、无线传输与硬件麦克风尚未实测；全系统和跨应用目标适配也未完成。模型规模较小，提案质量必须由用户检查；模型输出不能执行命令或自行写文件。文件写入使用快照冲突检查与原子替换，对不配合锁定的第三方编辑器不能提供跨进程强事务保证。


## 连接实物的入口

以下入口已实现，当前没有设备，不能把这些命令示例视为实物连接证据。主界面在实物模式隐藏模拟键，F1–F4 不会向硬件注入按键。

```sh
/opt/homebrew/bin/python3.14 tools/setup_host_transports.py
~/.cache/ai-key-rev-a/host-python314/bin/python host/list_devices.py --usb
~/.cache/ai-key-rev-a/host-python314/bin/python host/server.py --usb
```

USB 模式只选择 AI KEY 的 UAC 麦克风。浏览器未能识别唯一 AI KEY 麦克风时会撤回录音，不改用电脑默认麦克风。先在浏览器的麦克风设置中授权并选择 AI KEY，再重新按住 V。

BLE 首次配对由系统处理；绑定保存在设备 NVS。macOS 的扫描结果 `address` 是 CoreBluetooth 标识，不是硬件 MAC。发现设备后，用扫描结果启动：

```sh
~/.cache/ai-key-rev-a/host-python314/bin/python host/list_devices.py --ble
~/.cache/ai-key-rev-a/host-python314/bin/python host/server.py --ble-address '<扫描得到的 address>'
```

无线语音需先停止伴侣程序、松开全部实体键，通过 USB 配网。替换下列 SSID 和电脑局域网 IPv4；密码会在终端隐藏输入，不写入电脑连接配置。端口默认 8894。

```sh
~/.cache/ai-key-rev-a/host-python314/bin/python host/configure_device.py --ssid '<SSID>' --host '<电脑局域网 IPv4>'
```

只有设备回复保存成功才算配置提交。按 EN 复位使设置生效，再用工具输出的私有连接文件启动：

```sh
~/.cache/ai-key-rev-a/host-python314/bin/python host/server.py --ble-address '<address>' --wifi-config '<连接配置 JSON 的绝对路径>'
```

控制网页仍只监听 127.0.0.1；音频服务监听配置中的局域网地址，使用设备专属 TLS 密钥。无线模式从 TLS 接收 PCM，不申请浏览器麦克风。更换绑定电脑时，通过 USB 执行 `host/configure_device.py --forget-bond`；不会清除 Wi-Fi 设置。EN 复位不会清除绑定。

新增验收入口为 `tools/validate_host_physical_browser.cjs`、`tools/validate_wifi_audio.py`（用 Python 3.14）和 `tools/validate_wifi_browser.cjs`。前者使用连接适配器替身；后两者执行真实 TLS、C 编码器和合成音频。网络端到端测试真实调用本地 whisper/Qwen、写入并读回临时文件，再撤销；不替代样机测试。
