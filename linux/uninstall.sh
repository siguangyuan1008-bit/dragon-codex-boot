#!/usr/bin/env bash
# 移除 Dragon Codex Boot 的应用菜单入口，保留仓库文件与配置。
set -euo pipefail

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENTRY="$APPS/dragon-codex-boot.desktop"

if [ -f "$ENTRY" ]; then
    rm -f "$ENTRY"
    echo "已移除：$ENTRY"
else
    echo "没有找到 $ENTRY"
fi

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" || true
