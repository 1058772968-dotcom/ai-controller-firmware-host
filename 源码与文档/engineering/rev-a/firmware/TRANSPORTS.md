# REV A 传输与配置

USB 插入并枚举后优先；USB 挂起时禁止偷偷转向蓝牙。连接切换、蓝牙加密或订阅状态变化都会释放旧输入、轮换会话号，并要求仍按住的键先松开。EN 复位不会擦除配对或 Wi-Fi 设置。

USB 鼠标报告 ID 1 为 5 字节；控制报告 ID 2 的输入/输出各 32 字节；UAC2 为 16 kHz、16 bit、单声道。ID 3 是独立的 USB 配置输入/输出，各 32 字节。开发 VID/PID 为 `cafe:4031`，量产身份尚未分配。macOS 伴侣以共享方式打开 HID，普通鼠标由系统处理。

BLE 使用 HOGP（服务 1812），鼠标报告引用 ID 1；GATT 值不带报告 ID。自定义控制服务为 `98f32a0e-79bc-4d5b-9f84-dcce6f807291`，特征为 `98f32a0e-79bc-4d5b-9f84-dcce6f807292`。控制特征需加密、订阅通知及 ATT MTU 至少 35。设备名 `AIKEY-xxxxxx`。保存一个绑定；首次使用通过系统配对。采用 LE Secure Connections / JustWorks，无显示器或键盘认证，因此不具备人工核对码的 MITM 认证。显式重新配对通过 USB 配置命令执行。

控制协议沿用 `core/protocol.c`：32 字节、版本 1、小端、CRC16-CCITT。主机每 200 ms 续租；固件租约 750 ms。命令 ACK 的会话和命令序号必须精确匹配，写入成功或收到普通状态都不等于执行成功。浏览器失活后，伴侣在 550 ms 撤回增强控制。

## USB 配置

配置报告布局：版本 1、操作码、2 字节偏移、4 字节当前固件会话、4 字节事务号、16 字节数据、2 字节保留零、2 字节 CRC16。操作码 1/2/3/4/5/6 分别为开始、分包、提交、放弃、状态、清除 BLE 绑定。回复操作码最高位为 1，字节 2 为结果、字节 3 为已保存标记，12–13 为收到长度、14–15 为目标长度。

配置仅允许 USB 当前连接，且所有实体键松开、没有伴侣会话或录音/圈画。160 字节配置需完整有序上传，校验后才 NVS 提交；重复提交、缺包、会话变化、存储失败都不返回保存成功。配置回复不返回密码或密钥。Wi-Fi 设置在下次 EN 复位后生效，不在活动录音中切换网络。

配置块：0 版本，1 SSID 字节数，2 密码字节数，3 保留；4–35 SSID，36–99 WPA2/过渡模式口令，100–115 电脑 IPv4 字符串，116–117 端口，118–149 随机 32 字节 TLS 密钥，150–159 保留零。电脑配置文件仅保存连接密钥与端点，不保存 Wi-Fi 口令。开发固件的 NVS 未启用量产 Flash 加密；本阶段未执行 eFuse 或安全启动烧写。

## Wi-Fi 语音

设备以 STA 加入配置的局域网，通过 TLS 1.2 PSK 与电脑建立加密连接。电脑仅接受 `PSK-AES128-GCM-SHA256`；身份为设备 USB 序列号，密钥由 USB 配置工具随机生成。使用现有 ESP-IDF 5.2.3 的 ESP-TLS，不修改 SDK。电脑接收端需要支持 PSK 的 Python 3.13 以上；本机已验证 Python 3.14.7 / OpenSSL 3.6.4。

TLS 内的帧头为 20 字节：`AKAU`、版本 1、类型、2 字节载荷长度、4 字节控制会话、4 字节录音流号、4 字节序号，全部小端。HELLO/BEGIN/DATA/END/PING/ACK 类型为 1–6；DATA 最多 160 个 PCM16 样本。每帧等待精确匹配的 ACK；断线、序号异常、排队溢出或会话变化使录音失效。

设备只在实体 V 保持、主机授权且麦克风稳定后发送 PCM。主机先按控制会话开放接收，再发送录音授权；结束帧前不会把音频当作完整录音。取消、断线和过期音频会被丢弃。单次录音最多 60 秒，完整音频仍须先转写预览、确认发送，再独立确认应用文件。

## 验证范围

`reports/firmware-wifi-build.log` 是实际 Xtensa 构建；`reports/wifi-elf-check.json` 检查最终链接的 Wi-Fi/TLS/设置路径。`reports/firmware-native-tests.json` 执行真实可移植 C 核心。`reports/wifi-audio-validation.json` 和 `reports/wifi-browser-validation.json` 使用真实回环 TLS、同一 C 音频编码器、合成录音及真实本地模型/文件操作。它们不证明实体 BLE、Wi-Fi、PDM 麦克风、射频或电池性能。

API 依据：[ESP-IDF 5.2 系列 ESP-TLS](https://docs.espressif.com/projects/esp-idf/en/v5.2.2/esp32s3/api-reference/protocols/esp_tls.html)、[Python SSL](https://docs.python.org/3.14/library/ssl.html)、[Bleak](https://bleak.readthedocs.io/en/latest/api/client.html)、[HIDAPI 0.15 macOS 源码](https://github.com/libusb/hidapi/blob/hidapi-0.15.0/mac/hid.c)。实际编译接口以本机锁定的 5.2.3 头文件为准。
