#!/bin/bash
# 用本机已有的 ESP-IDF v5.2.3（与 REV A 相同，不切换版本、不改 SDK）。
# 构建目录放在 iCloud 之外，避免几百 MB 中间文件被同步：~/.cache/ai-key-e24/build-<档位>
# 档位：E24_PROFILE=link（默认，联调）、bringup（点亮）或 micpoc（联调 + 麦克风常开，放宽 AUD 02，只烧台架板）
# 用法：tools/idf.sh build | E24_PROFILE=bringup tools/idf.sh -p /dev/cu.usbmodemXXXX flash monitor
set -o pipefail
export IDF_PATH=/Users/linxiansheng/esp-idf
export IDF_TOOLS_PATH=/Users/linxiansheng/.cache/ai-key-rev-a/esp-idf-5.2.3
want="v5.2.3"; got="$(git -C "$IDF_PATH" describe --tags 2>/dev/null || cat "$IDF_PATH/version.txt" 2>/dev/null)"
[ "$got" = "$want" ] || { echo "ESP-IDF 版本是 ${got:-未知}，需要 $want；不自动切换。" >&2; exit 2; }
. "$IDF_PATH/export.sh" >/dev/null || exit $?
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 -I "$ROOT/tools/gen_board.py" --check
PROFILE="${E24_PROFILE:-link}"
case "$PROFILE" in link|bringup|micpoc) ;; *) echo "E24_PROFILE 只能是 link、bringup 或 micpoc" >&2; exit 2;; esac
exec idf.py -C "$ROOT/firmware" -B "$HOME/.cache/ai-key-e24/build-$PROFILE" \
  -D SDKCONFIG="$ROOT/firmware/sdkconfig.$PROFILE" \
  -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.$PROFILE.defaults" "$@"
