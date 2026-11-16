#!/usr/bin/env python3
"""检查 partitions.csv：不重叠、app 64KB 对齐、总量不超过 board.json 的 Flash 容量、含双 OTA。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def num(s):
    s = s.strip()
    if s.upper().endswith("K"):
        return int(s[:-1], 0) * 1024
    if s.upper().endswith("M"):
        return int(s[:-1], 0) * 1024 * 1024
    return int(s, 0)


def main():
    flash = json.loads((ROOT / "spec/board.json").read_text())["flash_bytes"]
    rows = []
    for line in (ROOT / "firmware/partitions.csv").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name, ptype, sub, off, size = [c.strip() for c in line.split(",")[:5]]
        rows.append((name, ptype, sub, num(off), num(size)))
    errors = []
    end_prev, prev = 0x9000, "bootloader+分区表"
    for name, ptype, sub, off, size in rows:
        if off < end_prev:
            errors.append(f"{name} 起点 0x{off:X} 与 {prev} 重叠")
        if ptype == "app" and off % 0x10000:
            errors.append(f"{name} 未按 64KB 对齐")
        end_prev, prev = off + size, name
    if end_prev > flash:
        errors.append(f"分区结束于 0x{end_prev:X}，超过 Flash 0x{flash:X}")
    subs = {r[2] for r in rows}
    for need in ("ota_0", "ota_1", "ota"):
        if need not in subs:
            errors.append(f"缺少 {need}")
    for name, ptype, sub, off, size in rows:
        print(f"  {name:<9} 0x{off:06X}–0x{off + size:06X}  {size // 1024:>5} KB")
    print(f"  合计结束 0x{end_prev:X} / Flash 0x{flash:X}")
    if errors:
        print("FAIL\n  " + "\n  ".join(errors))
        return 1
    print("PASS 分区表")
    return 0


if __name__ == "__main__":
    sys.exit(main())
