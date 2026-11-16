#!/bin/zsh
# GRIP Capture 恢复版启动脚本：只能用 Python 3.9 运行（.pyc 与解释器小版本绑定）
cd "$(dirname "$0")"
VENV="$HOME/.venvs/grip-capture-py39"
if [ ! -x "$VENV/bin/python" ]; then
  echo "首次运行：创建 Python 3.9 虚拟环境并安装依赖…"
  /usr/bin/python3 -m venv "$VENV" || exit 1
  "$VENV/bin/pip" install PySide6 pyserial || exit 1
fi
exec "$VENV/bin/python" -m grip_capture
