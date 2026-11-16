#!/usr/bin/env python3
"""由 spec/board.json 生成板级头文件。引脚只在 board.json 里改，生成文件不要手改。

输出：
  firmware/components/bsp_e24/include/bsp_pins.h     BSP 引脚与 I2C 地址
  firmware/components/aikey_core/include/board_config.h  控制核心时序（沿用 REV A 宏名）

--check：只比对，不写文件；生成结果与磁盘不一致时返回 1（用于构建前检查）。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "spec/board.json"
OUT_PINS = ROOT / "firmware/components/bsp_e24/include/bsp_pins.h"
OUT_CORE = ROOT / "firmware/components/aikey_core/include/board_config.h"

# ESP32-S3 可用 GPIO 0–21、26–48；26–32 接模组内部 Flash，N8R8 的 33–37 接 Octal PSRAM
VALID = set(range(0, 22)) | set(range(26, 49))
MODULE_INTERNAL = set(range(26, 38))
STRAPPING = {0, 3, 45, 46}


def validate(b):
    pins = b["pins"]
    errors = []
    seen = {}
    for name, p in pins.items():
        g = p["gpio"]
        if g not in VALID:
            errors.append(f"{name}: GPIO{g} 不存在")
        if g in MODULE_INTERNAL:
            errors.append(f"{name}: GPIO{g} 被模组内部 Flash/PSRAM 占用")
        if g in b["reserved_gpio"] and p["dir"] != "strap":
            errors.append(f"{name}: GPIO{g} 在保留列表中")
        if g in STRAPPING and p["dir"] != "strap":
            errors.append(f"{name}: GPIO{g} 是启动脚，必须标为 strap")
        if g in seen:
            errors.append(f"{name}: GPIO{g} 与 {seen[g]} 冲突")
        seen[g] = name
        if p["dir"] not in {"in", "out", "od", "usb", "strap"}:
            errors.append(f"{name}: 未知方向 {p['dir']}")
    if pins.get("USB_DM", {}).get("gpio") != 19 or pins.get("USB_DP", {}).get("gpio") != 20:
        errors.append("USB D-/D+ 必须是 GPIO19/20")
    return errors


def render(b):
    pins = b["pins"]
    h = [
        "/* 由 tools/gen_board.py 从 spec/board.json 生成，不要手改。 */",
        "#pragma once",
        f'#define BSP_BOARD_REVISION "{b["revision"]}"',
        f"#define BSP_FLASH_BYTES {b['flash_bytes']}u",
        f"#define BSP_PSRAM_BYTES {b['psram_bytes']}u",
        "",
    ]
    for name, p in pins.items():
        note = f"/* net {p['net']}, {p['dir']}{', active low' if p.get('active_low') else ''} */"
        h.append(f"#define BSP_PIN_{name} {p['gpio']} {note}")
    h.append("")
    outs = [(n, p) for n, p in pins.items() if p["dir"] == "out"]
    h.append("/* 上电安全态：这些输出在 bsp_early_init() 里第一时间驱动到给定电平 */")
    h.append("#define BSP_BOOT_OUTPUTS { " + ", ".join(f"{{BSP_PIN_{n}, {p.get('boot_level', 0)}}}" for n, p in outs) + " }")
    keys = ["KEY_LEFT", "KEY_RIGHT", "KEY_VOICE", "KEY_DRAW"]
    h.append("/* 按键顺序与控制核心位图一致：bit0 L, bit1 R, bit2 V, bit3 S(DRAW) */")
    h.append("#define BSP_KEY_PINS { " + ", ".join(f"BSP_PIN_{k}" for k in keys) + " }")
    h.append("")
    i2c = b["i2c"]
    h.append(f"#define BSP_I2C_FREQ_HZ {i2c['frequency_hz']}u")
    h.append(f"#define BSP_I2C_TIMEOUT_MS {i2c['timeout_ms']}")
    h.append(f"#define BSP_I2C_RETRIES {i2c['retries']}")
    for dev, addr in i2c["addr7"].items():
        h.append(f"#define BSP_I2C_ADDR_{dev} 0x{addr:02X} /* 7 位地址 */")
    a = b["audio"]
    h.append(f"#define BSP_I2S_SAMPLE_HZ {a['i2s_sample_hz']}u")
    h.append(f"#define BSP_I2S_SLOT_BITS {a['slot_bits']}u")
    h.append(f"#define BSP_PCM_OUTPUT_HZ {a['pcm_output_hz']}u")
    h.append("")

    c = [
        "/* 由 tools/gen_board.py 从 spec/board.json 生成，不要手改。 */",
        "#ifndef AIKEY_BOARD_CONFIG_H",
        "#define AIKEY_BOARD_CONFIG_H",
        f'#define AK_BOARD_REVISION "{b["revision"]}"',
    ]
    c += [f"#define AK_{k.upper()}_MS {v}u" for k, v in b["timing_ms"].items()]
    c += [f"#define AK_MIC_SETTLE_MS {a['settle_ms']}u", "#endif", ""]
    return "\n".join(h), "\n".join(c)


def main():
    check = "--check" in sys.argv
    b = json.loads(BOARD.read_text())
    errors = validate(b)
    if errors:
        print("board.json 校验失败：\n  " + "\n  ".join(errors))
        return 1
    pins_h, core_h = render(b)
    stale = [p for p, t in ((OUT_PINS, pins_h), (OUT_CORE, core_h)) if not p.exists() or p.read_text() != t]
    if check:
        if stale:
            print("生成文件已过期，请运行 tools/gen_board.py：" + ", ".join(str(p.relative_to(ROOT)) for p in stale))
            return 1
        print(f"OK {len(b['pins'])} 个引脚，生成文件与 board.json 一致")
        return 0
    OUT_PINS.write_text(pins_h)
    OUT_CORE.write_text(core_h)
    print(f"已生成 {OUT_PINS.relative_to(ROOT)}、{OUT_CORE.relative_to(ROOT)}（{len(b['pins'])} 个引脚）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
