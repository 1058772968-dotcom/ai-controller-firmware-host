# 重新生成 README 截图

| 文件 | 内容 |
|---|---|
| `host-bench.png` | 网页实机上位机，虚拟手柄模式，逐项测试跑完前 3 项（连接与固件、陀螺仪校准、遥测） |
| `island-poc.png` | 灵动岛 POC 首屏 |
| `capture.py` | 生成上面两张图的脚本 |

两张图的数据都来自页面自带的「虚拟手柄」，是模拟数据，不代表实物。

在仓库根目录运行：

```bash
python3 -m pip install playwright
```

```bash
python3 docs/assets/capture.py
```

脚本优先用本机的 Google Chrome。没有 Chrome 时先运行 `python3 -m playwright install chromium`，脚本会自动改用 Playwright 自带的 Chromium。

原图约 1–1.3 MB，提交前用 Pillow 缩到 256 色（README 里的两张约 60 KB 和 190 KB）。
