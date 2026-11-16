#!/usr/bin/env python3
"""生成 32 kHz -> 16 kHz 抽取用的 FIR 系数：63 阶 Blackman 窗 sinc，截止 7 kHz。
用法：tools/gen_audio_fir.py 写文件；--check 只比对，不一致时退出码 1。"""
import math
import sys
from pathlib import Path

TAPS, FS, FC = 63, 32000.0, 7000.0
OUT = Path(__file__).resolve().parents[1] / "firmware/components/aikey_core/include/audio_fir.h"


def coefficients():
    h = []
    for i in range(TAPS):
        x = i - (TAPS - 1) / 2
        fc = FC / FS
        v = 2 * fc if x == 0 else math.sin(2 * math.pi * fc * x) / (math.pi * x)
        n = i / (TAPS - 1)
        h.append(v * (0.42 - 0.5 * math.cos(2 * math.pi * n) + 0.08 * math.cos(4 * math.pi * n)))
    s = sum(h)
    return [x / s for x in h]


def render():
    body = ",\n".join(f"    {x:.9e}f" for x in coefficients())
    return ("/* 由 tools/gen_audio_fir.py 生成，不要手改。32 kHz -> 16 kHz 抗混叠，63 阶 Blackman，截止 7 kHz。 */\n"
            "#ifndef AIKEY_AUDIO_FIR_H\n#define AIKEY_AUDIO_FIR_H\n"
            f"#define AK_FIR_TAPS {TAPS}\n"
            "static const float ak_fir_coeffs[AK_FIR_TAPS] = {\n" + body + "\n};\n#endif\n")


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        sys.exit(0 if OUT.exists() and OUT.read_text() == text else 1)
    OUT.write_text(text)
