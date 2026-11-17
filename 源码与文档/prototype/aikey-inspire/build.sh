#!/bin/bash
# 编译并打包成 ~/Applications/AI KEY 灵感圈.app，用本机的 Apple Development 证书签名。
# 签名身份固定后，系统里授过的“辅助功能 / 屏幕录制”权限在重新编译后仍然有效。
# 用法：./build.sh          编译 + 打包 + 签名
#       ./build.sh test     只跑单元测试
#       ./build.sh run      打包后启动（先退出正在运行的旧版本）
set -euo pipefail
cd "$(dirname "$0")"
SCRATCH="$HOME/.cache/ai-key-inspire/build"     # 中间文件不进 iCloud
APP="$HOME/Applications/AI KEY 灵感圈.app"

# 测试页复制到 iCloud 之外：预览服务进程读不了 iCloud 目录（.claude/launch.json 的 inspire-fixture）
mkdir -p "$HOME/.cache/ai-key-inspire/fixtures" && cp Tests/fixtures/*.html "$HOME/.cache/ai-key-inspire/fixtures/"

if [ "${1:-}" = "test" ]; then
  exec swift test --scratch-path "$SCRATCH"
fi

swift build -c release --scratch-path "$SCRATCH" --product AIKeyInspire
swift build -c release --scratch-path "$SCRATCH" --product inspire-probe
BIN="$SCRATCH/release/AIKeyInspire"

TMP="$APP.tmp"
rm -rf "$TMP"
mkdir -p "$TMP/Contents/MacOS" "$TMP/Contents/Resources"
cp "$BIN" "$TMP/Contents/MacOS/AIKeyInspire"
cp Info.plist "$TMP/Contents/Info.plist"

# 只取证书的 SHA-1，不在输出里显示证书名（证书名里带邮箱）
SIGN_ID="$(security find-identity -v -p codesigning | awk '/Apple Development/ {print $2; exit}')"
if [ -n "$SIGN_ID" ]; then
  codesign --force --sign "$SIGN_ID" --identifier com.aikey.inspire "$TMP" >/dev/null 2>&1
  echo "已用 Apple Development 证书签名"
else
  codesign --force --sign - --identifier com.aikey.inspire "$TMP" >/dev/null 2>&1
  echo "没找到 Apple Development 证书，用临时签名：每次重新编译后都要重新授权"
fi
codesign --verify "$TMP"

if [ "${1:-}" = "run" ]; then
  pkill -x AIKeyInspire 2>/dev/null || true
fi
mkdir -p "$HOME/Applications"
rm -rf "$APP"
mv "$TMP" "$APP"
echo "已生成：$APP"
echo "探针：$SCRATCH/release/inspire-probe"

if [ "${1:-}" = "run" ]; then
  open "$APP"
fi
