# Linux 版

Linux 版位于 `linux/`，是一个 Python 3 + GTK3 + GStreamer 启动器，不依赖 .NET、WPF 或 DWM。它在鼠标所在的显示器上全屏播放本地 MP4，同时后台启动 Codex 桌面客户端，并在配置的时间点淡出、把屏幕交还给客户端。

只有 Codex 还没运行时才播放动画。已经在运行（`ClientProcessNames` 里的进程存在）时，点图标只做打开/聚焦，不再重复播一遍。

## 依赖

- Python 3.8 以上，`python3-gi`、`gir1.2-gtk-3.0`、`gir1.2-gstreamer-1.0`
- `gstreamer1.0-gtk3`（提供 `gtksink`，把视频画进 GTK 窗口）
- `gstreamer1.0-libav`（H.264 / AAC 解码；换用自己的 MP4 时通常都需要）
- 已安装 Codex 桌面客户端

Ubuntu 上一条命令装齐：

```sh
sudo apt-get install -y python3-gi gir1.2-gtk-3.0 gir1.2-gstreamer-1.0 gstreamer1.0-gtk3 gstreamer1.0-libav
```

## 安装与运行

```sh
./linux/install.sh                  # 检查依赖，写入 ~/.local/share/applications/dragon-codex-boot.desktop
./linux/install.sh --install-deps   # 缺依赖时用 apt 自动安装
./linux/install.sh --replace-codex-entry   # 额外把 Codex 自己的桌面入口指向本启动器
./linux/uninstall.sh                # 只移除应用菜单入口
```

安装后在应用列表里搜索 "Dragon Codex Boot" 即可启动。加上 `--replace-codex-entry` 后，点原来的 Codex / ChatGPT 图标也会先播放动画：脚本把该入口的 `Exec` 改成启动器，原文件备份为 `*.desktop.dragon-backup`，`uninstall.sh` 会还原。播放失败时启动器会直接打开 Codex，不会让你打不开软件。

也可以直接运行：

```sh
python3 linux/dragon-codex-boot.py --config linux/launcher.json
```

`Esc` 或右上角按钮可跳过动画，跳过后使用 0.18 秒快速淡出。

## 配置

默认读取 `linux/launcher.json`；若存在 `~/.config/dragon-codex-boot/launcher.json`，则优先使用后者。也可用 `--config` 指定。

| 字段 | 说明 |
| --- | --- |
| `Video` | 视频路径，相对路径按配置文件所在目录解析 |
| `ClientCommand` | 启动客户端的命令数组；留空则自动探测 `codex-desktop`、`chatgpt-desktop`、`chatgpt`、`codex`，再查 `.desktop` 文件 |
| `HoldAt` | 到达该秒数时暂停，等待客户端就绪 |
| `TransitionStart` / `TransitionEnd` | 淡出开始/结束时间，两者之差就是淡出时长 |
| `MaxWaitSeconds` | 等待客户端的最长秒数，超时后继续播放 |
| `Volume` | 0.0–1.0 |
| `Fullscreen` | 是否全屏；为 `false` 时按 `PlayerWidth`/`PlayerHeight` 缩放到主显示器 |
| `ClientReadyDelaySeconds` | 启动客户端后至少等待多久才认为就绪 |
| `ClientProcessNames` | 用于判断"已经在运行"的进程名列表，默认 `["ChatGPT"]`；置空则每次都播放 |
| `MatchClientWindow` | 默认 `true`：动画按 Codex 窗口的大小和位置显示；找不到窗口或非 X11 时退回全屏 |
| `ClientWindowClasses` | 用于匹配窗口的 `WM_CLASS` 关键字（小写子串），默认 `["chatgpt", "codex"]` |

换成自己的动画时，把 `Video` 指向你的 MP4，并按视频的实际分镜修改 `HoldAt`、`TransitionStart`、`TransitionEnd`。这些时间点不是通用模板。

## 与 Windows / macOS 版的差别

- 不把真实 Codex 窗口嵌进动画里的屏幕区域。Linux 上没有 DWM 缩略图那样的接口，也没有申请截图或辅助功能权限的跨桌面方案，因此和 macOS 版一样采用整屏淡出交接。
- 默认只新增自己的应用菜单项。`--replace-codex-entry` 才会改写当前用户目录里的 Codex 入口副本，官方安装目录不动，可用 `uninstall.sh` 还原；它只影响点击图标，不影响已运行进程。
- 从图标启动时传入的参数（例如 `codex://` 链接）会原样转发给客户端。
- 默认不是全屏，而是覆盖 Codex 窗口本身（含标题栏），多显示器下也只占那一块区域。找不到窗口（例如 Wayland 会话）时退回全屏，并显示在鼠标指针所在的那块显示器上。
- 第一次运行会等窗口出现再播；之后按上次的位置立刻开始播放，窗口出现后再自动校正一次，所以动画不会比客户端窗口更晚出现。
- 视频保持原始比例等比显示；窗口和视频比例不同时可能出现黑边，但不会在副屏切换裁切管线造成黑屏。
- 窗口使用带 alpha 的视觉，让 GNOME 不把全屏动画按“直通”处理。直通会临时改掉 NVIDIA 的缩放和输出模式，副屏上会黑一下并把窗口挤到主屏；NVIDIA 双屏 + 缩放的机器上请保留这段设置。
- 关闭动画窗口后，焦点由窗口管理器交还给之前的窗口。若 Codex 没有自动获得焦点，点一下它的窗口即可。

## 验证

```sh
./scripts/test-linux.sh
```

脚本检查 Python 语法、配置字段与时间轴顺序，并在有图形会话且安装了 `gstreamer1.0-libav` 时验证解码、客户端探测，以及一次带淡出的完整播放。它不会启动真实的 Codex 客户端（测试配置里用 `sleep` 代替），也不会验证焦点交接和窗口管理器差异，这些需要在桌面上手动确认。

只检查环境不播放：

```sh
python3 linux/dragon-codex-boot.py --config linux/launcher.json --verify
```
