#!/usr/bin/env python3
"""重新生成 README 截图：用「虚拟手柄」打开网页上位机，跑前 3 项逐项测试后截图；再截灵动岛 POC 首屏。

截图里的数据都是虚拟手柄模拟的，不代表实物。
用法（在仓库根目录）：python3 docs/assets/capture.py
依赖：pip install playwright；浏览器用本机 Google Chrome（channel="chrome"），
没装 Chrome 时先运行 playwright install chromium，脚本会自动改用自带的 Chromium。
"""
import pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROTO = ROOT / "源码与文档" / "prototype"
OUT = pathlib.Path(__file__).resolve().parent


def launch(p):
    try:
        return p.chromium.launch(channel="chrome")
    except Exception:
        return p.chromium.launch()


with sync_playwright() as p:
    b = launch(p)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto((PROTO / "AI键盘-实机上位机.html").as_uri())
    pg.wait_for_timeout(500)
    pg.click("#useSim")
    pg.wait_for_timeout(2500)
    for _ in range(3):  # 连接与固件、陀螺仪校准、遥测
        pg.click("#benchRun")
        pg.wait_for_timeout(4500)
        if pg.is_enabled("#benchNext"):
            pg.click("#benchNext")
            pg.wait_for_timeout(300)
    pg.screenshot(path=str(OUT / "host-bench.png"), full_page=True)

    pg.goto((PROTO / "AI键盘-灵动岛POC演示.html").as_uri())
    pg.wait_for_timeout(2500)
    pg.screenshot(path=str(OUT / "island-poc.png"))
    b.close()
print("saved:", OUT / "host-bench.png", OUT / "island-poc.png")
