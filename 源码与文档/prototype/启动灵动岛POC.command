#!/bin/zsh
# 双击运行：在本机起一个只监听 127.0.0.1 的静态服务，用 Chrome 打开灵动岛 POC。
# WebHID（连接 AI KEY 实物）只在安全上下文里可用，file:// 打开不行，必须走 http://127.0.0.1。
# 关闭这个终端窗口或按 Ctrl+C 即停止服务。

cd "${0:A:h}" || exit 1
PAGE="${ISLAND_POC_PAGE:-AI键盘-灵动岛POC演示.html}"
PORT="${ISLAND_POC_PORT:-8896}"

if [[ ! -f "$PAGE" ]]; then
  echo "找不到 $PAGE。请先在 prototype 目录运行：npm run build:island"
  read -k1 "?按任意键退出…"; exit 1
fi
# iCloud「优化存储」可能只留占位文件，先确保本地有完整内容。
brctl download "$PAGE" >/dev/null 2>&1

ENC=$(/usr/bin/python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$PAGE")
URL="http://127.0.0.1:$PORT/$ENC"

open_page() {
  [[ -n "$ISLAND_POC_NO_OPEN" ]] && return
  open -a "Google Chrome" "$URL" 2>/dev/null || open "$URL"
}

# 从 8896 起找端口：已经是本页的服务（例如上次没关）就直接打开；被别的程序占用就往后顺延。
for _ in {1..10}; do
  URL="http://127.0.0.1:$PORT/$ENC"
  if curl -fsI "$URL" >/dev/null 2>&1; then
    echo "服务已在运行：$URL"
    open_page; exit 0
  fi
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 || break
  echo "端口 $PORT 已被其他程序占用，改用 $((PORT + 1))。"
  PORT=$((PORT + 1))
done

/usr/bin/python3 -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null; echo; echo "已停止服务。"' EXIT INT TERM

for _ in {1..60}; do curl -fsI "$URL" >/dev/null 2>&1 && break; sleep 0.1; done
if ! kill -0 $SRV 2>/dev/null; then
  echo "服务没能启动（端口 $PORT）。"; read -k1 "?按任意键退出…"; exit 1
fi

open_page
echo "已启动：$URL"
echo "接实物：插上 AI KEY，在页面里点连接并选择设备。需要 Chrome / Edge。"
echo "关闭这个窗口或按 Ctrl+C 即停止服务。"
wait $SRV
