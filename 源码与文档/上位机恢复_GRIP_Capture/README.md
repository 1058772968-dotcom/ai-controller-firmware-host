# GRIP Capture 上位机（10-28 恢复版）

从压缩包 `AI编程手柄_Mac上位机旧版缓存_仅供恢复.zip` 恢复的可运行版本。只有编译好的字节码（.pyc），没有原始源码。

## 启动
双击 `启动上位机.command`。第一次运行会在 `~/.venvs/grip-capture-py39` 自动创建虚拟环境，并安装 PySide6 和 pyserial。
虚拟环境故意放在 iCloud 目录之外，免得同步几百 MB 的依赖。

## 限制
- 必须用 **Python 3.9**（系统自带的 `/usr/bin/python3`）。.pyc 文件和 Python 的小版本绑定，换成 3.10 及以上会无法加载。
- 不包含 10-30 的改动，也没有固件和原始源码，详见 `说明.txt`。
- 依赖版本：已在 PySide6 6.10.3 和 pyserial 3.5 下验证，自带的 12 项单元测试全部通过。

## 运行测试
```bash
QT_QPA_PLATFORM=offscreen ~/.venvs/grip-capture-py39/bin/python -c "import sys,unittest; sys.path.insert(0,'tests'); import test_capture; unittest.main(module=test_capture, argv=['t','-v'])"
```
