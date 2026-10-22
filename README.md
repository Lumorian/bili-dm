# Bilidm Overlay

漂浮在 B 站直播间上方的弹幕悬浮窗(Wayland):以半透明点击穿透窗口滚动展示真实弹幕,聊天、礼物、SC、订阅四种类型各有样式,弹幕保留至被新弹幕顶替。

数据链路:`UniBarrage` → `dmnotifier`(float 插件)→ Unix socket → `bilidm-overlay`(PyQt6/QtWayland layer-shell)。

## 功能

- 悬浮滚动墙:Chat/礼物/SC/订阅分别着色与加粗/描边;**行数按面板高度自适应,新消息自动滚到底部**;无时间淡出——弹幕一直保留,直到新弹幕顶替旧行(墙内按行数上限计数淘汰)
- **可上下翻阅历史**:滚轮(一次 3 行)、右侧细滚动条(可拖)、PageUp/PageDown、Home/End、
  托盘「回到最新弹幕」;像素级滚动(上滚一点内容就动一点,不整行跳变)。往上翻时新弹幕
  不会把画面顶走,右下角提示「↓ N 条新弹幕」,点一下或滚到底即恢复跟随最新。
  历史深度 = `max_rows`(配置/设置里的「墙行数上限」,默认 80)—— 想看更久就把这个数调大。
  翻着历史时**不会被空闲隐藏**;锁定(穿透)态下鼠标在往外放行,翻阅需先解锁
- **房间管理在窗口内**:卡片右上角内嵌按钮带(🔒 锁 / ⚙ 设置,与卡片一体)或托盘「设置…」打开;对话框列出 UniBarrage 当前服务,可添加(平台+rid+可选 cookie)与删除,保存后 dmnotifier run 每 5s 自动对齐订阅,无需重启
- **窗口交互**:解锁(右上角锁按钮)后**窗口任意位置**左键拖动移动、右下角拖拽缩放(无可见手柄),位置/尺寸写入 `~/.config/bilidm-overlay/config.yaml` 下次启动恢复;锁按钮随状态切换闭锁/开锁图标——**锁定态除按钮带外全窗口点击穿透**(不挡鼠标,按钮带始终可点,解锁/设置无需托盘),解锁即可直接调整,无需进设置
- **圆角卡片**:面板 12px 圆角(客户端绘制;niri 侧 `layer-rule` 的 `geometry-corner-radius` 同步,阴影/模糊随形)
- **排版 1:1 对齐官方弹幕面板**:行内顺序与度量照抄 B 站直播间 `chat-history-panel`
  (`.chat-item{padding:5px}` + 20px 行框 = 30px 行高、`.chat-history-list{padding:5px 10px}`、
  昵称后 `" : "`);粉丝勋章按 `medal.vue` 画成 15px 高、8px 圆角的渐变胶囊(含舰长锚图标、
  等级槽位),礼物行 `昵称 赠送 礼物名 x20` 统一 `--pay_yellow`,上舰 `昵称 开通了 舰长`,
  醒目留言为整块卡片(渐变底 + 金额)。逐项参数与量测过程见
  `docs/superpowers/specs/2026-10-21-chat-panel-parity-design.md`
- **行首 24px 圆形头像**:官方行内没有头像,本项目保留在最左(唯一有意偏离);异步加载 +
  磁盘缓存(`~/.cache/bilidm-overlay/avatars/`),未就绪时灰色圆形占位(名字首字)
- **深/浅两套官方配色**:`theme: dark`(默认,`--bg2:#101011`)/ `light`(`#F6F7F8`),
  令牌取自官方 bili-theme;CLI `--theme`、设置对话框、`config.yaml` 均可切换
- **发弹幕(仿官方弹幕姬)**:卡片底部一条输入条(官方面板输入条的位置),20 字上限、
  回车即发、发送后立刻本地回显(官方同样即时上屏),WebSocket 把同一条回推回来时不重复插入;
  走官方 `msg/send`(短号自动换成真实房间号,csrf 取 cookie 里的 `bili_jct`),
  失败在输入条里就地说明原因(未登录/缺 csrf/太频繁/被风控…),不打网络就能确定的错误先本地拦住。
  **发到哪个房间不需要额外配置**:per-room 窗口发自己那个房间 → `config.yaml` 的 `rooms` →
  正在收的弹幕带来的那个房间(dmnotifier 订阅的)→ dmnotifier `config.yaml` 的 history。
  也就是说「能看就能发」——收弹幕不需要登录,cookie 只用于发送;
  cookie 取值顺序:`--room bilibili:rid:cookie` → `config.yaml` 的 `send_cookie` →
  dmnotifier history 里该房间的 cookie。锁定(穿透)时输入框只读并提示「解锁后可发送弹幕」
- 全窗口点击穿透(默认开;托盘菜单可切),不挡鼠标点选下层窗口(穿透与设置项经托盘菜单验证,未做物理点击注入测试)
- dmnotifier 断线自动重连(重连期间窗口显示"离线,连接中…")
- 无头演示:`uv run bilidm-overlay --demo`

## 排错:窗口拖不动 / 不穿透 / 停在左上角

**症状**:悬浮窗出现在屏幕左上角,鼠标拖不动它,点击也穿不过去(反过来它挡住下层窗口)。

**原因**:layer-shell 桥(`libkoto-layer.so`)依赖系统的 `layer-shell-qt`,而它跟着**系统**
Qt 编译;PyQt6 的 wheel 则固定自带一版 Qt。两者一大版本错开时,桥一 `dlopen` 就报

```
version `Qt_6.12' not found (required by /usr/lib/libLayerShellQtInterface.so.6)
```

于是 kotonoha 判定"本会话没有 layer-shell",适配器退化成**普通顶层窗**:Wayland 上
这种窗口既不能被客户端定位(所以 `move()` 无效、拖不动、位置记不住),也不能自绘
输入区域(所以穿透也失效)。2026-10 的 `qt6-base` 6.11→6.12 升级配 `layer-shell-qt`
6.8.0 正是这一情形。

**处理**:取一份与 venv 里 Qt 同 ABI 的 `layer-shell-qt`,由 overlay 在加载桥之前预载
(纯用户态,不装系统包、不需要 root):

```bash
overlay/scripts/fetch-layer-shell-qt.sh            # 下载到 ~/.cache/bilidm-overlay/layer-shell-qt/
```

`scripts/start.sh` 也会先跑一次 `fetch-layer-shell-qt.sh --ensure`,缺就补上。

**确认结果**:启动日志里出现

```
INFO bilidm_overlay.layershell_qt_compat: 已预载 ABI 兼容的 layer-shell-qt:...libLayerShellQtInterface.so.6.7.5
```

`niri msg layers` 里能看到 `{"namespace":"kotonoha",...,"layer":"Overlay"}`(而不是
`niri msg windows` 里多出一个 `Bilidm Overlay` 平铺窗)。若只有警告
"layer-shell 桥无法加载",说明取回失败,按提示重跑脚本。

> 换了 PyQt6 版本(venv 里的 Qt 变了)之后要重跑一次脚本:对照表在
> `fetch-layer-shell-qt.sh` 里(6.11 → layer-shell-qt 6.7.5-1,6.12 → 6.8.0-1)。

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

# 不要底部发送栏(纯展示):
uv run bilidm-overlay --room bilibili:689422 --no-send

# 单独给发送用的登录 cookie(不带 --room 里的 cookie 时):
uv run bilidm-overlay --room bilibili:689422 --send-cookie 'SESSDATA=…; bili_jct=…'

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

> 定位:锚点是 Top|Left(kotonoha 桥接层如此生成),位置由 `config.yaml` 的 `position` 决定并随拖动更新。wayland 上 `move()` 无效,启动时经桥的锚点设定——**前提是 layer-shell 真的可用**(见上面的排错一节);退化到普通顶层窗时合成器接管位置,拖动与位置记忆都不可用。

## niri keybind 示例

绑定 `Mod+G` 直接拉起叠加层(UniBarrage 需已在运行,只需成功启动过一次):

```niri
binds = { Mod+G = spawn "bash" "-c" "/home/lumorian/Projects/bili-dm/overlay/scripts/start.sh --room bilibili:689422" }
```

## 配置

- `~/.config/bilidm-overlay/config.yaml` — 悬浮窗宽度/位置/字号/主题(dark|light)/透明度/行数/点击穿透(缺省即内置默认),
  以及发弹幕的 `send_enabled` / `send_cookie`(后者含 `SESSDATA` 与 `bili_jct`,等同登录态,注意别外传)
- `~/.config/dmnotifier/config.yaml` — dmnotifier 侧:pipeline 插件(需启用 `float`)

## 开发

```bash
uv run pytest --cov=bilidm_overlay --cov-report=term-missing   # 纯逻辑 ≥ 80%
uv run bilidm-overlay --demo                                   # 视觉效果
uv run python scripts/demo_client.py                            # 假客户端注入 socket(配合运行中的 overlay)
```
