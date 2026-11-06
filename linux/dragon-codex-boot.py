#!/usr/bin/env python3
"""Dragon Codex Boot for Linux.

Plays a local startup animation fullscreen, launches the Codex desktop client
in the background, then hands the screen back to it.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gdk, GLib, Gst, Gtk  # noqa: E402

DEFAULTS = {
    "DisplayName": "Dragon Codex Boot",
    "Video": "media/startup.mp4",
    "ClientCommand": [],
    "HoldAt": 11.3,
    "TransitionStart": 12.7,
    "TransitionEnd": 13.65,
    "MaxWaitSeconds": 60,
    "Volume": 1.0,
    "Fullscreen": True,
    "PlayerWidth": 1920,
    "PlayerHeight": 1080,
    "ClientReadyDelaySeconds": 1.0,
    "ClientProcessNames": ["ChatGPT"],
    "MatchClientWindow": True,
    "ClientWindowClasses": ["chatgpt", "codex"],
}

CLIENT_CANDIDATES = ("codex-desktop", "chatgpt-desktop", "chatgpt", "codex")
DESKTOP_DIRS = (
    "~/.local/share/applications",
    "/usr/share/applications",
    "~/.local/share/flatpak/exports/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    "/var/lib/snapd/desktop/applications",
)


def state_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    path = os.path.join(base, "dragon-codex-boot")
    os.makedirs(path, exist_ok=True)
    return path


LOG_PATH = os.path.join(state_dir(), "last-run.log")


def report(message):
    line = "%s %s" % (time.strftime("%H:%M:%S"), message)
    print("[DragonCodexBoot] %s" % message, file=sys.stderr, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def find_config(explicit):
    if explicit:
        return os.path.abspath(explicit)
    candidates = [
        os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                     "dragon-codex-boot", "launcher.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "launcher.json"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def load_config(path):
    if not path:
        raise SystemExit("找不到 launcher.json，请用 --config 指定。")
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)
    missing = [key for key in DEFAULTS if key not in config]
    merged = dict(DEFAULTS, **config)
    return merged, os.path.dirname(os.path.abspath(path)), missing


def parse_exec(exec_line):
    """Turn a .desktop Exec value into an argv list."""
    return [token for token in shlex.split(exec_line) if not token.startswith("%")]


def find_client():
    for name in CLIENT_CANDIDATES:
        found = shutil.which(name)
        if found:
            return [found]
    for directory in DESKTOP_DIRS:
        directory = os.path.expanduser(directory)
        if not os.path.isdir(directory):
            continue
        for entry in sorted(os.listdir(directory)):
            if not entry.endswith(".desktop"):
                continue
            try:
                with open(os.path.join(directory, entry), encoding="utf-8") as handle:
                    text = handle.read()
            except OSError:
                continue
            if "x-scheme-handler/codex" not in text and "Name=Codex" not in text:
                continue
            for line in text.splitlines():
                if line.startswith("Exec="):
                    if "dragon-codex-boot" in line:
                        continue  # 跳过被替换成启动器自己的入口，避免自我循环
                    argv = parse_exec(line[5:])
                    if argv and shutil.which(argv[0]):
                        return argv
    return None


def resolve_video(config, config_dir):
    path = os.path.expanduser(config["Video"])
    if not os.path.isabs(path):
        path = os.path.join(config_dir, path)
    return os.path.abspath(path)


def client_running(names):
    """看 /proc 里有没有同名进程，用来区分「冷启动」和「再点一次图标」。"""
    if not names:
        return False
    me = os.getpid()
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == me:
            continue
        try:
            with open("/proc/%s/comm" % entry, encoding="utf-8") as handle:
                if handle.read().strip() in names:
                    return True
        except OSError:
            continue
    return False


def _rect(monitor):
    """Gdk.Rectangle 的 == 不可靠，转成元组比较。"""
    geometry = monitor.get_geometry()
    return (geometry.x, geometry.y, geometry.width, geometry.height)


def cached_rect_path():
    return os.path.join(state_dir(), "window.json")


def load_cached_rect():
    try:
        with open(cached_rect_path(), encoding="utf-8") as handle:
            rect = json.load(handle)
        return (int(rect["x"]), int(rect["y"]), int(rect["w"]), int(rect["h"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_cached_rect(rect):
    try:
        with open(cached_rect_path(), "w", encoding="utf-8") as handle:
            json.dump({"x": rect[0], "y": rect[1], "w": rect[2], "h": rect[3]}, handle)
    except OSError:
        pass


def _x11(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_window_geometry(info):
    """从 xwininfo 输出里取出可见窗口的物理像素矩形。"""
    if "IsViewable" not in info:
        return None
    fields = {}
    for line in info.splitlines():
        key, _, value = line.strip().partition(":")
        if key in ("Absolute upper-left X", "Absolute upper-left Y", "Width", "Height"):
            try:
                fields[key] = int(value)
            except ValueError:
                return None
    if len(fields) != 4:
        return None
    return (fields["Absolute upper-left X"], fields["Absolute upper-left Y"],
            fields["Width"], fields["Height"])


def find_client_window(classes):
    """返回 Codex 主窗口的物理像素矩形 (x, y, w, h)，X11 之外返回 None。"""
    listing = _x11("xprop", "-root", "_NET_CLIENT_LIST")
    if "#" not in listing:
        return None
    for window_id in listing.split("#", 1)[1].replace(",", " ").split():
        if not any(name in _x11("xprop", "-id", window_id, "WM_CLASS").lower()
                   for name in classes):
            continue
        info = _x11("xwininfo", "-id", window_id)
        geometry = parse_window_geometry(info)
        if geometry:
            return geometry
    return None


def missing_plugins():
    wanted = {"gtksink": "gstreamer1.0-gtk3", "avdec_h264": "gstreamer1.0-libav"}
    missing = []
    for element, package in wanted.items():
        if Gst.ElementFactory.find(element) is None:
            missing.append(package)
    return sorted(set(missing))


class Launcher:
    def __init__(self, config, config_dir):
        self.config = config
        self.config_dir = config_dir
        self.video = resolve_video(config, config_dir)
        self.client_cmd = config["ClientCommand"] or find_client()
        self.client = None
        self.launched_at = 0.0
        self.held = False
        self.finishing = False
        self.fade_started_at = 0.0
        self.fade_seconds = 0.0
        self.window = None
        self.player = None
        self.bus = None

    def build_window(self, rect=None):
        window = Gtk.Window(title=self.config["DisplayName"])
        window.set_decorated(False)
        window.set_keep_above(True)
        window.set_skip_taskbar_hint(True)
        window.set_skip_pager_hint(True)
        window.connect("key-press-event", self.on_key)
        window.connect("destroy", lambda *_: Gtk.main_quit())
        # An alpha-capable visual keeps mutter from unredirecting the fullscreen
        # window; that unredirect toggles NVIDIA's scaling/mode and flashes black.
        visual = window.get_screen().get_rgba_visual()
        if visual is not None:
            window.set_visual(visual)
        window.set_app_paintable(True)
        window.realize()
        css = Gtk.CssProvider()
        css.load_from_data(b"window { background-color: #000000; }")
        Gtk.StyleContext.add_provider_for_screen(
            window.get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        sink = Gst.ElementFactory.make("gtksink", "video-sink")
        if sink is None:
            raise SystemExit("缺少 gtksink：请安装 gstreamer1.0-gtk3。")
        video_widget = sink.get_property("widget")

        overlay = Gtk.Overlay()
        overlay.add(video_widget)
        skip = Gtk.Button(label="跳过 · Esc")
        skip.set_halign(Gtk.Align.END)
        skip.set_valign(Gtk.Align.START)
        skip.set_margin_top(16)
        skip.set_margin_end(16)
        skip.connect("clicked", lambda *_: self.skip())
        overlay.add_overlay(skip)
        window.add(overlay)

        windowed_size = None
        if rect is None and not self.config["Fullscreen"]:
            windowed_size = self.scaled_size(window)
            window.set_default_size(*windowed_size)
            window.set_position(Gtk.WindowPosition.CENTER)

        self.window = window
        self.sink = sink
        window.show_all()
        if rect is not None:
            scale = self.display_scale(window.get_display(), rect)
            window.move(rect[0] // scale, rect[1] // scale)
            window.resize(rect[2] // scale, rect[3] // scale)
        elif self.config["Fullscreen"]:
            display = window.get_display()
            _, pointer_x, pointer_y = display.get_default_seat().get_pointer().get_position()
            monitor = (display.get_monitor_at_point(pointer_x, pointer_y)
                       or display.get_primary_monitor() or display.get_monitor(0))
            target = _rect(monitor)
            index = next((i for i in range(display.get_n_monitors())
                          if _rect(display.get_monitor(i)) == target), 0)
            window.fullscreen_on_monitor(window.get_screen(), index)
        return window

    @staticmethod
    def display_scale(display, rect):
        """客户端矩形是物理像素，GTK 用逻辑像素，按所在显示器的缩放换算。"""
        center_x, center_y = rect[0] + rect[2] // 2, rect[1] + rect[3] // 2
        for index in range(display.get_n_monitors()):
            monitor = display.get_monitor(index)
            geometry = monitor.get_geometry()
            scale = monitor.get_scale_factor() or 1
            if (geometry.x * scale <= center_x < (geometry.x + geometry.width) * scale
                    and geometry.y * scale <= center_y < (geometry.y + geometry.height) * scale):
                return scale
        return 1

    def wait_for_client_window(self):
        deadline = time.monotonic() + 8
        classes = [name.lower() for name in self.config["ClientWindowClasses"]]
        while time.monotonic() < deadline:
            rect = find_client_window(classes)
            if rect:
                report("WINDOW matched %dx%d+%d+%d" % (rect[2], rect[3], rect[0], rect[1]))
                save_cached_rect(rect)
                return rect
            time.sleep(0.25)
        report("WARNING: 没等到客户端窗口，改用全屏")
        return None

    def adjust_to_window(self, attempts=40):
        """先按上次的位置播，客户端窗口出现后再校正一次，避免动画晚于窗口。"""
        if self.finishing:
            return False
        classes = [name.lower() for name in self.config["ClientWindowClasses"]]
        rect = find_client_window(classes)
        if rect:
            save_cached_rect(rect)
            scale = self.display_scale(self.window.get_display(), rect)
            current = self.window.get_position() + self.window.get_size()
            if current != (rect[0] // scale, rect[1] // scale,
                           rect[2] // scale, rect[3] // scale):
                self.window.move(rect[0] // scale, rect[1] // scale)
                self.window.resize(rect[2] // scale, rect[3] // scale)
                report("WINDOW adjusted %dx%d+%d+%d" % (rect[2], rect[3], rect[0], rect[1]))
            return False
        if attempts > 1:
            GLib.timeout_add(250, self.adjust_to_window, attempts - 1)
        return False

    def scaled_size(self, window):
        width = int(self.config["PlayerWidth"])
        height = int(self.config["PlayerHeight"])
        display = window.get_display()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geometry = monitor.get_workarea()
        scale = min(geometry.width / width, geometry.height / height, 1.0)
        return max(1, int(width * scale)), max(1, int(height * scale))

    def build_player(self):
        player = Gst.ElementFactory.make("playbin", "player")
        if player is None:
            raise SystemExit("缺少 playbin：请安装 gstreamer1.0-plugins-base。")
        player.set_property("video-sink", self.sink)
        player.set_property("uri", Gst.filename_to_uri(self.video))
        player.set_property("volume", float(self.config["Volume"]))
        bus = player.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", lambda *_: self.skip())
        bus.connect("message::error", self.on_error)
        self.player = player
        self.bus = bus

    def on_error(self, _bus, message):
        error, debug = message.parse_error()
        report("PLAYBACK failed: %s (%s)" % (error.message, debug.splitlines()[0] if debug else ""))
        self.skip()

    def on_key(self, _window, event):
        if event.keyval == 65307:  # Escape
            self.skip()
            return True
        return False

    def launch_client(self):
        if not self.client_cmd:
            report("WARNING: 没有找到 Codex 客户端，只播放动画。")
            return
        report("TARGET launching: %s" % " ".join(self.client_cmd))
        try:
            self.client = subprocess.Popen(
                self.client_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.launched_at = time.monotonic()
        except OSError as error:
            report("ERROR: Codex 启动失败：%s" % error)

    def client_ready(self):
        if self.client is None:
            return True
        elapsed = time.monotonic() - self.launched_at
        if elapsed < float(self.config["ClientReadyDelaySeconds"]):
            return False
        # A single-instance client may exit immediately when it only re-focused
        # the running window, so a clean exit still counts as ready.
        return self.client.poll() is None or self.client.returncode == 0

    def start(self):
        if not os.path.isfile(self.video):
            raise SystemExit("找不到启动视频：%s" % self.video)
        cached = load_cached_rect() if self.config["MatchClientWindow"] else None
        if cached:
            self.build_window(cached)
            self.build_player()
            report("START video=%s" % self.video)
            self.player.set_state(Gst.State.PLAYING)
            self.started_at = time.monotonic()
            self.launch_client()
            GLib.timeout_add(250, self.adjust_to_window)
            GLib.timeout_add(50, self.tick)
            return
        self.launch_client()
        rect = self.wait_for_client_window() if self.config["MatchClientWindow"] else None
        self.build_window(rect)
        self.build_player()
        report("START video=%s" % self.video)
        self.player.set_state(Gst.State.PLAYING)
        self.started_at = time.monotonic()
        GLib.timeout_add(50, self.tick)

    def position(self):
        ok, position = self.player.query_position(Gst.Format.TIME)
        return position / Gst.SECOND if ok else None

    def tick(self):
        if self.finishing:
            return False
        position = self.position()
        if position is None:
            return True

        if (position >= float(self.config["HoldAt"]) and not self.held
                and not self.client_ready()):
            self.held = True
            self.player.set_state(Gst.State.PAUSED)
            report("HOLD at %.2fs waiting for client" % position)
            return True

        if self.held:
            if time.monotonic() - self.started_at > float(self.config["MaxWaitSeconds"]):
                report("WARNING: 等待 Codex 超时，继续播放。")
                self.held = False
                self.player.set_state(Gst.State.PLAYING)
            elif self.client_ready():
                self.held = False
                report("TARGET ready, resuming")
                self.player.set_state(Gst.State.PLAYING)
            return True

        if position >= float(self.config["TransitionStart"]) and self.client_ready():
            self.handoff()
            return False
        return True

    def skip(self):
        if self.finishing:
            return
        self.handoff(fast=True)

    def handoff(self, fast=False):
        if self.finishing:
            return
        self.finishing = True
        self.fade_seconds = 0.18 if fast else max(
            0.1, float(self.config["TransitionEnd"]) - float(self.config["TransitionStart"]))
        self.fade_started_at = time.monotonic()
        report("HANDOFF fade=%.2fs" % self.fade_seconds)
        GLib.timeout_add(16, self.fade_step)

    def fade_step(self):
        progress = (time.monotonic() - self.fade_started_at) / self.fade_seconds
        if progress >= 1.0:
            self.window.hide()
            self.player.set_state(Gst.State.NULL)
            report("FINISHED")
            Gtk.main_quit()
            return False
        self.window.set_opacity(max(0.0, 1.0 - progress))
        return True


def verify(config, config_dir, client_cmd):
    video = resolve_video(config, config_dir)
    problems = []
    if not os.path.isfile(video):
        problems.append("找不到视频：%s" % video)
    missing = missing_plugins()
    if missing:
        problems.append("缺少 GStreamer 插件包：%s" % ", ".join(missing))
    if not client_cmd:
        problems.append("没有找到 Codex 桌面客户端")
    if problems:
        for problem in problems:
            report("VERIFY FAIL: %s" % problem)
        return 1

    player = Gst.ElementFactory.make("playbin", "verify")
    player.set_property("uri", Gst.filename_to_uri(video))
    player.set_state(Gst.State.PAUSED)
    message = player.get_bus().timed_pop_filtered(
        10 * Gst.SECOND, Gst.MessageType.ERROR | Gst.MessageType.ASYNC_DONE)
    if message is None or message.type == Gst.MessageType.ERROR:
        detail = message.parse_error()[0].message if message else "超时"
        report("VERIFY FAIL: 无法解码视频：%s" % detail)
        player.set_state(Gst.State.NULL)
        return 1
    ok, duration = player.query_duration(Gst.Format.TIME)
    player.set_state(Gst.State.NULL)
    report("VERIFY OK: %.1fs; client=%s; video=%s"
           % (duration / Gst.SECOND, " ".join(client_cmd), video))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Dragon Codex Boot (Linux)")
    parser.add_argument("--config", help="launcher.json 路径")
    parser.add_argument("--verify", action="store_true", help="只检查环境与视频，不播放")
    args, extra_args = parser.parse_known_args()

    config_path = find_config(args.config)
    config, config_dir, missing = load_config(config_path)
    if missing:
        report("WARNING: 配置缺少字段，使用默认值：%s" % ", ".join(missing))

    Gst.init(None)
    client_cmd = (config["ClientCommand"] or find_client() or []) + extra_args

    if args.verify:
        return verify(config, config_dir, client_cmd)

    if client_running(config["ClientProcessNames"]):
        report("ALREADY RUNNING: 只打开/聚焦客户端，不播动画")
        if config["MatchClientWindow"]:
            # 顺手刷新窗口位置，避免下次冷启动按旧位置起播。
            rect = find_client_window([name.lower() for name in config["ClientWindowClasses"]])
            if rect:
                save_cached_rect(rect)
        if client_cmd:
            subprocess.Popen(client_cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        return 0

    launcher = Launcher(config, config_dir)
    launcher.client_cmd = client_cmd
    try:
        launcher.start()
    except SystemExit as error:
        # 播放失败时不能连累客户端：仍然把 Codex 打开。
        report("ERROR: %s" % (error.code or "启动失败"))
        if client_cmd:
            report("FALLBACK: 直接启动客户端")
            subprocess.Popen(client_cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        return 1
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
