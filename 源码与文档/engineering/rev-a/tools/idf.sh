#!/bin/bash
# Use the user's existing v5.2.3 checkout. Do not switch SDK revisions.
set -o pipefail
export IDF_PATH=/Users/linxiansheng/esp-idf
export IDF_TOOLS_PATH=/Users/linxiansheng/.cache/ai-key-rev-a/esp-idf-5.2.3
. "$IDF_PATH/export.sh" || exit $?
set -eu
exec "$@"
