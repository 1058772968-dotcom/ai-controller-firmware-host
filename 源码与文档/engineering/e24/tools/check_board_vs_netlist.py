#!/usr/bin/env python3
"""把 spec/board.json 与嘉立创EDA 导出的网表比对，防止固件引脚和原理图对不上。

用法：
  python3 -I tools/check_board_vs_netlist.py [网表.json]
不给参数时使用 board.json 里 source.netlist 指向的归档快照。
网表可以是 sch_Netlist.getNetlist() 的原始字符串 JSON，也可以是 bridge /execute 的返回包装。

检查三件事：
  1. board.json 每个引脚：U1 上对应 IOxx 的网络名一致；
  2. U1 上每个有网络的 IO 都在 board.json 里登记（防止硬件加了线固件不知道）；
  3. non_gpio_nets（EN）一致。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]
SKIP_NETS = {"GND", "3V3", ""}


def load_netlist(path):
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict) and "result" in data and isinstance(data["result"], str):
        data = json.loads(data["result"])
    elif isinstance(data, str):
        data = json.loads(data)
    return data


def mcu_pins(netlist, designator):
    for comp in netlist["components"].values():
        if comp["props"].get("Designator") == designator:
            return comp["props"].get("Manufacturer Part", ""), list(comp["pinInfoMap"].values())
    raise SystemExit(f"网表里找不到 {designator}")


def main():
    board = json.loads((ROOT / "spec/board.json").read_text())
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT / board["source"]["netlist"]
    netlist = load_netlist(src)
    part, pins = mcu_pins(netlist, board["source"]["mcu_designator"])
    errors = []
    if part != board["mcu"]:
        errors.append(f"主控型号不一致：网表 {part}，board.json {board['mcu']}")

    gpio_net = {}
    other_net = {}
    for p in pins:
        m = re.fullmatch(r"IO(\d+)", p["name"])
        if m:
            gpio_net[int(m.group(1))] = p["net"] or ""
        else:
            other_net[p["name"]] = p["net"] or ""

    declared = {}
    for name, p in board["pins"].items():
        g, want = p["gpio"], p["net"]
        declared[g] = name
        got = gpio_net.get(g)
        if got is None:
            errors.append(f"{name}: U1 上没有 IO{g}")
        elif got != want:
            errors.append(f"{name}: GPIO{g} 网表是 {got or '未连接'}，board.json 写 {want}")

    for g, net in sorted(gpio_net.items()):
        if net not in SKIP_NETS and g not in declared:
            errors.append(f"GPIO{g} 在网表里接了 {net}，board.json 没登记")

    for pin_name, want in board["non_gpio_nets"].items():
        got = other_net.get(pin_name)
        if got != want:
            errors.append(f"{pin_name}: 网表 {got}，board.json {want}")

    print(f"网表：{src}")
    print(f"U1 {part}：{sum(1 for n in gpio_net.values() if n)} 个 IO 有网络，board.json 登记 {len(board['pins'])} 个")
    if errors:
        print("FAIL\n  " + "\n  ".join(errors))
        return 1
    print("PASS 引脚与网表一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
