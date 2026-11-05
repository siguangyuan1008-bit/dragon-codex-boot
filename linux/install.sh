#!/usr/bin/env bash
# 安装 Dragon Codex Boot 到当前用户的应用菜单，并检查运行依赖。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHER="$ROOT/linux/dragon-codex-boot.py"
CONFIG="$ROOT/linux/launcher.json"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENTRY="$APPS/dragon-codex-boot.desktop"

install_deps=0
for arg in "$@"; do
    case "$arg" in
        --install-deps) install_deps=1 ;;
        -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
        *) echo "未知参数：$arg" >&2; exit 2 ;;
    esac
done

missing=()
python3 -c 'import gi; gi.require_version("Gtk", "3.0"); gi.require_version("Gst", "1.0")' 2>/dev/null \
    || missing+=(python3-gi gir1.2-gtk-3.0 gir1.2-gstreamer-1.0)
for pair in "gtksink:gstreamer1.0-gtk3" "avdec_h264:gstreamer1.0-libav"; do
    gst-inspect-1.0 "${pair%%:*}" >/dev/null 2>&1 || missing+=("${pair#*:}")
done

if [ ${#missing[@]} -gt 0 ]; then
    if [ "$install_deps" -eq 1 ]; then
        echo "安装依赖：${missing[*]}"
        sudo apt-get install -y "${missing[@]}"
    else
        echo "缺少依赖，请先运行：" >&2
        echo "  sudo apt-get install -y ${missing[*]}" >&2
        echo "或重新执行：$0 --install-deps" >&2
        exit 1
    fi
fi

mkdir -p "$APPS"
chmod +x "$LAUNCHER"
cat > "$ENTRY" <<EOF
[Desktop Entry]
Type=Application
Name=Dragon Codex Boot
Comment=播放启动动画后打开 Codex
Exec=$(command -v python3) $LAUNCHER --config $CONFIG
Icon=applications-development
Terminal=false
Categories=Utility;
StartupNotify=false
EOF

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" || true
echo "已安装：$ENTRY"
echo "验证：$LAUNCHER --config $CONFIG --verify"
"$LAUNCHER" --config "$CONFIG" --verify
