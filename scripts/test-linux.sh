#!/usr/bin/env bash
# Linux 版自检：语法、配置、解码、以及一次带淡出的完整播放。
# 播放检查需要桌面会话；无 DISPLAY 时跳过。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHER="$ROOT/linux/dragon-codex-boot.py"
CONFIG="$ROOT/linux/launcher.json"
failures=0

fail() { echo "FAIL: $*" >&2; failures=$((failures + 1)); }
pass() { echo "ok: $*"; }

python3 -m py_compile "$LAUNCHER" && pass "python 语法" || fail "python 语法"

python3 - "$CONFIG" <<'PY' && pass "配置校验" || fail "配置校验"
import json, sys
required = ["DisplayName", "Video", "ClientCommand", "HoldAt", "TransitionStart",
            "TransitionEnd", "MaxWaitSeconds", "Volume", "Fullscreen",
            "PlayerWidth", "PlayerHeight", "ClientReadyDelaySeconds"]
config = json.load(open(sys.argv[1], encoding="utf-8"))
missing = [key for key in required if key not in config]
assert not missing, "缺少字段: %s" % missing
assert config["HoldAt"] <= config["TransitionStart"] < config["TransitionEnd"], "时间轴顺序不对"
PY

if ! python3 -c 'import gi; gi.require_version("Gtk", "3.0")' 2>/dev/null; then
    fail "缺少 python3-gi / GTK3"
elif [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    echo "skip: 无图形会话，跳过播放检查"
elif ! gst-inspect-1.0 avdec_h264 >/dev/null 2>&1; then
    echo "skip: 未安装 gstreamer1.0-libav，跳过播放检查"
else
    if "$LAUNCHER" --config "$CONFIG" --verify; then pass "解码与客户端检测"; else fail "解码与客户端检测"; fi

    cat > /tmp/dragon-codex-boot-test.json <<EOF
{
  "DisplayName": "Dragon Codex Boot Test",
  "Video": "$ROOT/media/startup.mp4",
  "ClientCommand": ["sleep", "20"],
  "HoldAt": 1.0,
  "TransitionStart": 2.5,
  "TransitionEnd": 3.5,
  "MaxWaitSeconds": 15,
  "Volume": 0.0,
  "Fullscreen": false,
  "PlayerWidth": 640,
  "PlayerHeight": 360,
  "ClientReadyDelaySeconds": 0.5,
  "ClientProcessNames": []
}
EOF
    if timeout 30 "$LAUNCHER" --config /tmp/dragon-codex-boot-test.json >/tmp/dragon-codex-boot-test.log 2>&1 \
        && grep -q "FINISHED" /tmp/dragon-codex-boot-test.log; then
        pass "播放与淡出交接"
    else
        fail "播放与淡出交接"
        tail -5 /tmp/dragon-codex-boot-test.log >&2
    fi
fi

if [ "$failures" -eq 0 ]; then
    echo "全部通过"
    exit 0
fi
echo "$failures 项失败" >&2
exit 1
