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

for backup in "$APPS"/*.desktop.dragon-backup; do
    [ -f "$backup" ] || continue
    restored="${backup%.dragon-backup}"
    mv -f "$backup" "$restored"
    echo "已恢复：$restored"
done

for marker in "$APPS"/*.desktop.dragon-created; do
    [ -f "$marker" ] || continue
    created="${marker%.dragon-created}"
    rm -f "$created" "$marker"
    echo "已移除替换入口：$created"
done

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" || true
