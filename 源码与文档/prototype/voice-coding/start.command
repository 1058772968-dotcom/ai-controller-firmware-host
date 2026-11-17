#!/bin/bash
# 双击启动：起本机服务，再用 Chrome 的应用窗口打开界面。关掉这个终端窗口就停服务。
set -u
cd "$(dirname "$0")" || exit 1

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v node >/dev/null 2>&1; then
  echo "找不到 node（需要 20 以上）。装一个再来：brew install node"
  read -r -p "按回车关闭…" _
  exit 1
fi

DATA_DIR="$HOME/.voice-coding"
mkdir -p "$DATA_DIR"
LOG="$DATA_DIR/server.log"
: > "$LOG"

echo "启动本机服务…"
node src/server.mjs >> "$LOG" 2>&1 &
SERVER_PID=$!
cleanup() { kill "$SERVER_PID" 2>/dev/null; }
trap cleanup EXIT INT TERM

URL=""
for _ in $(seq 1 120); do
  URL=$(grep -o 'http://127\.0\.0\.1:[0-9]*' "$LOG" 2>/dev/null | head -1)
  [ -n "$URL" ] && break
  sleep 0.1
done

if [ -z "$URL" ]; then
  echo "服务没起来。日志：$LOG"
  tail -20 "$LOG"
  read -r -p "按回车关闭…" _
  exit 1
fi

if [ -d "/Applications/Google Chrome.app" ]; then
  # 三个 disable-* 是为了后台不被降频：手柄的 HOST 租约 750 ms，KEEPALIVE 200 ms 一次，
  # 窗口失焦或被人挡住时如果计时器被 Chrome 降频，租约就会过期，按住 V 也不出声。
  open -na "Google Chrome" --args --app="$URL" --window-size=1320,900 \
    --disable-background-timer-throttling --disable-backgrounding-occluded-windows --disable-renderer-backgrounding
else
  echo "没装 Chrome，用默认浏览器打开；麦克风授权可能被拦，建议装 Chrome。"
  open "$URL"
fi

echo
echo "呆毛语音 Coding 已启动：$URL"
echo "第一次用要点两件事："
echo "  1) 页面里允许麦克风（地址栏左边的图标）"
echo "  2) 系统设置 → 隐私与安全性 → 辅助功能，把终端/Chrome 勾上（要往别的应用里打字）"
echo "关掉这个窗口就停服务。"
echo
wait "$SERVER_PID"
