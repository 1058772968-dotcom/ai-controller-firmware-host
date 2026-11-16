#!/usr/bin/env python3
"""电脑端检查：引脚生成、网表比对（含反例）、分区表、协议与控制核心单元测试（ASan/UBSan）。
只证明纯逻辑和配置一致，不代表芯片或实物通过。"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "firmware/components/aikey_core"
results = []


def step(name, cmd, expect_fail=False):
    r = subprocess.run(cmd, text=True, capture_output=True)
    ok = (r.returncode != 0) if expect_fail else (r.returncode == 0)
    results.append({"name": name, "status": "PASS" if ok else "FAIL", "exit": r.returncode,
                    "log": (r.stdout + r.stderr)[-2000:]})
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(r.stdout + r.stderr)


py = [sys.executable, "-I"]
step("board.json 生成文件一致", py + [str(ROOT / "tools/gen_board.py"), "--check"])
step("board.json 与 EDA 网表一致", py + [str(ROOT / "tools/check_board_vs_netlist.py")])
step("分区表", py + [str(ROOT / "tools/check_partitions.py")])
step("音频 FIR 系数一致", py + [str(ROOT / "tools/gen_audio_fir.py"), "--check"])

# 反例：把网表里 AMP_EN 改名，比对脚本必须报错
board = json.loads((ROOT / "spec/board.json").read_text())
src = ROOT.parents[1] / board["source"]["netlist"]
raw = json.loads(src.read_text())
with tempfile.TemporaryDirectory(prefix="e24-host-") as tmp:
    bad = Path(tmp) / "bad.json"
    bad.write_text(json.dumps({"result": raw["result"].replace('"AMP_EN"', '"AMP_EN_X"')}))
    step("反例：网表改名应失败", py + [str(ROOT / "tools/check_board_vs_netlist.py"), str(bad)], expect_fail=True)

    for test, srcs in (("protocol_test", ["protocol.c", "controller.c"]), ("controller_test", ["controller.c"]),
                       ("pointer_test", ["pointer.c"]),
                       ("audio_test", ["audio_dsp.c"]),
                       ("devcfg_test", ["devcfg.c", "pointer.c", "protocol.c", "controller.c"])):
        exe = Path(tmp) / test
        cc = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-g",
              "-fsanitize=address,undefined", f"-I{CORE / 'include'}",
              *[str(CORE / s) for s in srcs], str(ROOT / "tests/host" / f"{test}.c"), "-lm", "-o", str(exe)]
        step(f"编译 {test}", cc)
        if exe.exists():
            step(f"运行 {test}", [str(exe)])

    # 调参小工具：对端是固件同一份 C 代码
    shim = Path(tmp) / "devcfg_shim"
    step("编译 devcfg_shim", ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-g",
                              "-fsanitize=address,undefined", f"-I{CORE / 'include'}",
                              *[str(CORE / s) for s in ("devcfg.c", "pointer.c", "protocol.c", "controller.c")],
                              str(ROOT / "tests/host/devcfg_shim.c"), "-lm", "-o", str(shim)])
    if shim.exists():
        step("运行 e24ctl_test（调参工具 × 固件 C 代码）", py + [str(ROOT / "tests/host/e24ctl_test.py"), str(shim)])
    step("e24ctl list（hidapi 可加载）", [sys.executable, str(ROOT / "tools/e24ctl.py"), "list"])

# 全链路：真实固件 C 代码接真实上位机 JS（需要 node）
step("全链路模拟（固件 × 上位机）", ["node", str(ROOT / "tests/link_sim/run.mjs")])

out = ROOT / "reports"
out.mkdir(exist_ok=True)
(out / "host-tests.json").write_text(json.dumps(
    {"scope": "电脑端纯逻辑与配置检查；非 MCU 执行、非实物验证", "results": results}, ensure_ascii=False, indent=2) + "\n")
failed = [r for r in results if r["status"] != "PASS"]
print(f"{len(results) - len(failed)}/{len(results)} 通过")
sys.exit(1 if failed else 0)
