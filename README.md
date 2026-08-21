# Bilidm Overlay

漂浮在 B 站直播间上方的弹幕悬浮窗(Wayland):以半透明点击穿透窗口滚动展示真实弹幕,聊天、礼物、SC、订阅四种类型各有样式,按年龄淡出。

数据链路:`UniBarrage` → `dmnotifier`(float 插件)→ Unix socket → `bilidm-overlay`(PyQt6/QtWayland layer-shell)。

## 功能

- 悬浮滚动墙:Chat/礼物/SC/订阅分别着色与加粗/描边,行数上限 + TTL 淡出
- 按房间过滤(multi-room 合并显示或 per-room 独立窗口),详情在 `~/.config/bilidm-overlay/config.yaml`
- 全窗口点击穿透(默认开;托盘菜单可切),不挡鼠标点选下层窗口(穿透与设置项经托盘菜单验证,未做物理点击注入测试)
- dmnotifier 断线自动重连(重连期间窗口显示"离线,连接中…")
- 无头演示:`uv run bilidm-overlay --demo`

## 依赖(Arch)

```bash
sudo pacman -S uv qt6-wayland iproute2 noto-fonts-cjk
# 其余(PyQt6 等)由 uv 管理:cd overlay && uv sync
```

- `uv` — 项目与运行器(overlay 用 `uv run --project "$ROOT"`)
- `qt6-wayland` — QtWayland 与 layer-shell 插件(悬浮窗位置与穿透)
- `iproute2` — `start.sh` 检查 UniBarrage 端口用的 `ss`
- `noto-fonts-cjk` — 中文渲染
- `UniBarrage` — 本地弹幕服务(127.0.0.1:7777/8080,先启动)
- `dmnotifier` — 弹幕转发器;需含 float 插件(本地构建或设置 `DMNOTIFIER_BIN` 指向带插件的二进制)

## 用法

```bash
# 一键拉起:注册 UniBarrage 监听 → 无头管道(dmnotifier run)→ 悬浮窗
scripts/start.sh --room bilibili:689422

# 多房间,或带 cookie(bilibili:789422:COOKIE 格式,只取前两个冒号)
scripts/start.sh --room bilibili:689422 --room bilibili:789422

# 停止:停止 UniBarrage 监听 + 杀掉 overlay
scripts/stop.sh --room bilibili:689422
```

**弹幕只有在一个管道进程运行时才会出现。** `scripts/start.sh` 依次做三件事:`dmnotifier start <room>`(向 UniBarrage 注册监听,并把房间写入 dmnotifier 的 config history)→ `dmnotifier run`(无头管道进程,按 history 自动订阅,经 float 插件把弹幕写入 socket)→ 最后拉起悬浮窗。如果你用别的方式启动悬浮窗(例如直接 `uv run bilidm-overlay --room bilibili:689422`),需要先有一个管道进程在跑——要么开着 `dmnotifier` TUI 并在里面订阅房间,要么手动 `dmnotifier start <room> && dmnotifier run`(后台运行、日志走 stderr);否则窗口只显示"dmnotifier 离线,连接中…"。

> 只有注册监听(`dmnotifier start`,即上式里的 cookie)需要"platform:rid[:cookie]"形态;cookie 仅被 UniBarrage 用以拉取弹幕,悬浮窗侧不解析。按房间过滤时(`config.yaml` 的 per-room 模式或 `--per-room`),过滤键就是 `platform:rid` 本身(cookie 不参与匹配)。

> 当前 dmnotifier 二进制需要 float 插件且支持 `run` 子命令才能把弹幕推给 overlay;仓库内默认查找 `../dmnotifier/dmnotifier`,也可显式指定:
>
> ```bash
> DMNOTIFIER_BIN=/path/to/dmnotifier-with-float scripts/start.sh --room bilibili:689422
> ```
>
> `dmnotifier start/stop/list` 仅管理 UniBarrage 远端监听;`dmnotifier run` 才是无头管道进程本身(消息推进由 float 插件完成,见 dmnotifier 配置 `~/.config/dmnotifier/config.yaml`;想用 TUI 人工管理也可以,等效)。

> 已知限制:悬浮窗目前渲染在屏幕**左上角**——Wayland layer-shell 的锚点定在 Top|Left(kotonoha 桥接层如此生成)。规格里的左下角定位需要 kotonoha 桥接层支持底部锚点,属于跨仓库变更,已列入待办追踪;当前版本用户看到的是左上角悬浮窗。

## niri keybind 示例

绑定 `Mod+G` 直接拉起叠加层(UniBarrage 需已在运行,只需成功启动过一次):

```niri
binds = { Mod+G = spawn "bash" "-c" "/home/lumorian/Projects/bili-dm/overlay/scripts/start.sh --room bilibili:689422" }
```

## 配置

- `~/.config/bilidm-overlay/config.yaml` — 悬浮窗宽度/位置/字号/透明度/行数/TTL/点击穿透(缺省即内置默认)
- `~/.config/dmnotifier/config.yaml` — dmnotifier 侧:pipeline 插件(需启用 `float`)

## 开发

```bash
uv run pytest --cov=bilidm_overlay --cov-report=term-missing   # 纯逻辑 ≥ 80%
uv run bilidm-overlay --demo                                   # 视觉效果
uv run python scripts/demo_client.py                            # 假客户端注入 socket(配合运行中的 overlay)
```
