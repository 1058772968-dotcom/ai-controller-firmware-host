# E24 固件工程

ESP32-S3-WROOM-1-N8R8，ESP-IDF **v5.2.3**（本机 `/Users/linxiansheng/esp-idf`，不切换版本）。
框架规划：[固件框架规划](../../docs/engineering/项目档案/20261106-固件框架规划/固件框架规划.md)。REV A 工程保留在 `../rev-a/` 不动。

当前阶段：**M0 完成；联调档（USB 复合设备 + BMI270 陀螺仪指向）已写好并通过电脑端测试，未上板。**
接口约定见 [固件-上位机联调预案](../../docs/engineering/项目档案/20261106-固件框架规划/固件-上位机联调预案.md)，上板流程见 [链路联调文档](../../docs/engineering/项目档案/20261106-链路联调预演/链路联调文档.md)。

## 构建档位

| 档位 | 命令前缀 | 内容 | 日志 |
|---|---|---|---|
| `bringup` 点亮 | `E24_PROFILE=bringup tools/idf.sh …` | 只用 GPIO：容量、复位原因、按键、VBUS、功放保持关 | USB-Serial-JTAG |
| `link` 联调（默认） | `tools/idf.sh …` | TinyUSB：HID 鼠标/控制(v1)/配置 + CDC；BMI270 指向；控制核心 | CDC 口（新的 usbmodem） |
| `micpoc` 麦克风 POC | `E24_PROFILE=micpoc tools/idf.sh …` | 联调档 + 主机开流即放行麦克风（设备名 `AI KEY Mic POC`）。**放宽规格 AUD 02，只烧台架板，不用于交付** | CDC 口 |

各档位的 sdkconfig 和构建目录分开：`firmware/sdkconfig.<档位>`、`~/.cache/ai-key-e24/build-<档位>`。

## 目录

| 路径 | 说明 |
|---|---|
| `spec/board.json` | 引脚唯一来源（来自 2026-11-06 EDA 网表） |
| `tools/gen_board.py` | 生成 `bsp_pins.h`、`board_config.h`；`--check` 只比对 |
| `tools/check_board_vs_netlist.py` | board.json 与 EDA 网表比对；可传新导出的网表 |
| `tools/check_partitions.py` | 分区表检查 |
| `tools/run_host_tests.py` | 电脑端全部检查 + 协议/控制核心单元测试 + 全链路模拟 |
| `tests/link_sim/` | [全链路模拟器](tests/link_sim/README.md)：真实固件 C 代码接真实上位机 JS |
| `tools/e24ctl.py` | 调参小工具：读写指向参数、校准、轴向向导、单键调手感、遥测与静置漂移检查 |
| `tools/idf.sh` | 构建/烧录包装：锁定 v5.2.3，构建目录放 `~/.cache/ai-key-e24/build`（不进 iCloud） |
| `firmware/components/bsp_e24/` | L1 BSP：安全初始态、按键/VBUS 读取、容量校验 |
| `firmware/components/aikey_core/` | 控制核心与协议（REV A 原样）+ 陀螺仪指向 `pointer.c` + 配置通道 `devcfg.c`（纯 C） |
| `firmware/components/bmi270_sensorapi/` | Bosch SensorAPI（BSD-3），来源与补丁见 `SOURCE.md` |
| `firmware/components/imu_bmi270/` | BMI270 驱动：i2c_master + 数据就绪中断 |
| `firmware/main/bringup.c` | 点亮档 |
| `firmware/main/link_app.c`、`usb_link.c` | 联调档主循环与 USB 复合设备 |
| `reports/` | 构建日志、电脑端测试结果 |

## 常用命令

```bash
python3 -I tools/run_host_tests.py
```

```bash
tools/idf.sh build
```

```bash
tools/idf.sh -p /dev/cu.usbmodemXXXX flash
```

联调档烧完后 JTAG 口会消失，`monitor` 用不了，改用 `screen` 打开新的 CDC 口。在 worktree 里构建要联网拉 `managed_components`，上板前在主工作目录构建。

## 调参小工具（联调档）

不需要上位机网页，也不抢系统鼠标，光标可以边调边动。依赖 Homebrew 的 hidapi 和 pyserial，本机都已具备。不要加 `-I`，否则找不到用户目录里的 pyserial。

```bash
python3 tools/e24ctl.py info
```

```bash
python3 tools/e24ctl.py wizard
```

```bash
python3 tools/e24ctl.py tune
```

```bash
python3 tools/e24ctl.py still -s 10
```

```bash
python3 tools/e24ctl.py watch --csv /tmp/e24.csv
```

其他命令：`list`、`get`、`set sens=32 deadzone=0.5`、`save`、`defaults`、`cal`、`tel on|off`、`dfu`。

- `set` 和 `tune` 的改动立即生效但不落盘，`save` 才写入设备。
- `defaults` 和 `tune` 的 `r` 只恢复手感参数，保留轴映射；连轴向一起恢复用 `defaults --axes`。
- 打不开设备时，到“系统设置 → 隐私与安全性 → 输入监控”给终端打勾，再重开终端。
- 串口不要手动设成 1200 bps：固件会把它当作重启进下载模式的信号。

改了原理图后：在 EDA 重新导出网表，运行 `python3 -I tools/check_board_vs_netlist.py <新网表.json>`；不一致先改 `spec/board.json`，再运行 `python3 -I tools/gen_board.py`。

## 音频（联调档）

| 项目 | 实现 |
|---|---|
| I²S | 一个控制器全双工，32 kHz，32 bit 立体声，BCLK 2.048 MHz；没有录音、自检、播放时停时钟、关功放 |
| 麦克风 | ICS-43434 左槽，24 bit，63 阶 FIR 抽取到 16 kHz，+12 dB 起点增益，走 UAC2（`Held-key microphone`） |
| 隐私闸门 | 按住 V、HOST 归属、主机发 RECORD=1、麦克风稳定 50 ms，四项同时成立才放行；否则主机收到的是零。麦克风 VDD 直连 3V3，这是软件隐私，不是物理断电 |
| 扬声器 | 只做设备提示音，不是 USB 声卡。规格 AUD 03 要求参数冻结前禁用有声播放，所以默认不响：每次要带 `SPK!` 口令，音量上限 -30 dB，5 ms 渐变，录音时抢占 |

```bash
python3 tools/e24ctl.py audio
```
```bash
python3 tools/e24ctl.py mic
```
```bash
python3 tools/e24ctl.py record -s 15
```
```bash
python3 tools/e24ctl.py tone --hz 1000 --ms 200 --atten 40
```

- `mic` 跑约 1 秒，只回电平统计，不传波形。左槽约 99%、右槽 0% 才对。
- `record` 只是接管指针并在按住 V 时请求录音，音频要用系统录音软件从 `Held-key microphone` 采。
- `tone` 会真的出声，接扬声器前先确认负载。

联调档更新固件不用按键：`e24ctl.py dfu` 约 1 秒切到 JTAG 口，再用 esptool 写。`--after hard_reset` 这一步实测可能不生效（esptool 之后提示 `Stub is already running`），端口停在 JTAG 时再执行一次复位或拔插 USB。

## M1 上板点亮清单（R7 首板）

点亮程序只用 GPIO：不访问 I²C（避免触发 BQ25180 看门狗）、不开 I²S、不开 USB 设备栈和无线。

1. **断电量线**：U1 第 8 脚（GPIO15）→ U10 RESET / R19；第 9 脚（GPIO16）→ R20 → U4 SD_MODE。确认首板和原理图一致。
2. **只接 USB、不接电池**。电池参数没批准前，BQ25180 保持上电默认值。
3. 烧录：`tools/idf.sh -p <端口> flash monitor`。空片上电不会停在 ROM 下载：ROM 找不到程序，串口满屏 `invalid header: 0xffffffff`，约每 2.75 秒看门狗复位（`rst:0x7`）并重新枚举一次，这是正常现象，esptool 能直接连上烧录。如果端口没出现，按住 SW6（BOOT）点一下 SW7（复位）。
4. 期望日志：
   - `Flash 8192 KB，PSRAM 8192 KB -> PASS`
   - `运行分区 ota_0 @0x20000`
   - `VBUS 存在`（只接 USB 时一直为存在；拔插测试要等接上电池）
5. 逐个按 L / R / V / S：每次按下、松开各出现一条 `EDGE` 事件，键位依次为 0x1 / 0x2 / 0x4 / 0x8。R7 板上没有按键，要先在 J5–J8 接临时开关，或用镊子把第 1 脚短接到第 2 脚 GND。
6. 按住任意键再复位：出现“启动时有键按住”，松开之前不产生动作。
7. 万用表量：GPIO16（AMP_EN）、GPIO4/5/7 为 0 V，扬声器无声。

把实测结果记到任务归档；没测的项目不要写成通过。

## 下一步（M2）

I²C 总线管理 + 三个器件识别（BMI270 0x68 / BQ25180 0x6A / DRV2605L 0x5A）+ 故障注入。BQ25180 只读，并默认禁止充电。
