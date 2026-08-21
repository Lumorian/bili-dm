# Bilidm Overlay — 悬浮直播弹幕设计文档

- 日期:2026-08-21
- 状态:待实现
- 支持环境:Arch Linux / Wayland / niri(兼容任何实现 `wlr-layer-shell` 的合成器)

## 1. 背景与目标

在桌面(Linux + Wayland/niri)上实时观看 B 站直播时,把弹幕以**悬浮窗**形式展示在屏幕角落,不阻挡正在看的内容,且**点击穿透**不干扰鼠标操作。属于"看主播同时瞄弹幕"的形态,与直播主流的桌面弹幕助手一致。

已有三个克隆在上游仓库中,本设计不重复造轮子:

| 项目 | 角色 | 状态 |
|------|------|------|
| UniBarrage | 统一弹幕代理:多平台采集 → 标准 WS 广播(:7777)+ API(:8080) | 已部署运行中(pid 独立进程) |
| dmnotifier | UniBarrage 客户端:多路订阅 + 消息管道 + 插件系统(consumer/filter/transform) | 需要本地新增一个 consumer 插件 |
| kotonoha | Wayland 悬浮层实现:layer-shell 桥 + 半透明+点击穿透+拖拽,platform 层已解耦成干净接口 | 作为库被依赖,零改动 |

**目标**:`UniBarrage → dmnotifier → Unix socket → 新悬浮弹幕程序`,一条命令拉起,悬浮窗显示弹幕。

## 2. 关键技术事实(探索结论)

- 系统:`WAYLAND_DISPLAY=wayland-1`、`XDG_SESSION_TYPE=wayland`、桌面 niri;niri 实现 `wlr-layer-shell`,kotonoha 的悬浮能力可用(毛玻璃协议不支持,表现为无模糊的半透明,可接受)
- kotonoha `platform/` 是可独立复用的模块:`DefaultOverlayPlatformFactory`、`QtWindowHost`、`OverlayPlatform`、`WindowPolicy` 等契约,原生桥 `layer_shell_bridge.cpp` 经 CMake 编译为 `libkoto-layer.so`(随 kotonoha wheel 安装)
- kotonoha 的歌词管线(`overlay.py`、`lyrics/`、`providers/mpris.py`)**不在复用范围**
- dmnotifier 插件接口:`plugin.ConsumerPlugin` + `plugin.Register(name, New, PluginInfo{...})`,在 `cmd/dmnotifier/main.go` 中 import 注册;配置在 `$XDG_CONFIG_HOME/dmnotifier/config.yaml`
- UniBarrage 部署在本机 `127.0.0.1:7777`(WS)/ `127.0.0.1:8080`(API)

## 3. 总体架构

```
UniBarrage (:7777 WS, 已部署)
      │ 订阅 bilibili:rid(可选 cookie)
      ▼
dmnotifier (Go, 本地新增 float consumer 插件)
      │ JSON lines → Unix socket $XDG_RUNTIME_DIR/bilidm-danmaku.sock
      ▼  ← overlay 是 socket 服务端,插件为客户端,可重连
Bilidm Overlay (PyQt6 + kotonoha.platform 悬浮层,新独立 git 仓库)
      │
      ▼
滚动墙渲染(角落半透明面板,点击穿透,行数/TTL 淘汰)
```

数据流要点:

- **单向、不重放**:overlay 离线期间的弹幕丢弃,不落盘不补发(live 场景预期)
- **overlay 可任意开关**:插件每 2s 重连,不影响 dmnotifier
- **分组在 overlay**:消息携带 `platform/rid`,合并/分窗选择由 overlay 配置决定;插件只转发不分流

### 仓库布局

```
bili-dm/
├── UniBarrage/            # 不动
├── dmnotifier/            # 本地改动:plugins/consumers/float/ + main.go 注册
├── kotonoha/              # 不动,uv path 依赖
└── overlay/               # ★ 新独立 git 仓库
    ├── pyproject.toml
    ├── src/bilidm_overlay/
    │   ├── main.py        # CLI + qasync 事件循环
    │   ├── window.py      # 悬浮窗(封装 kotonoha.platform host)
    │   ├── client.py      # Unix socket 服务端,接插件连接
    │   ├── danmaku/
    │   │   ├── model.py   # 消息模型 / JSON 解析
    │   │   ├── wall.py    # 滚动墙 QWidget(QPainter 自定义绘制)
    │   │   ├── style.py   # 类型→样式映射
    │   │   └── lifecycle.py # 行数上限 / TTL 淘汰(纯逻辑)
    │   └── config.py      # XDG 配置加载与默认值
    ├── scripts/start.sh   # 一键拉起
    ├── scripts/stop.sh
    └── docs/superpowers/specs/   # 本文件(spec)
```

## 4. 组件设计

### 4.1 dmnotifier float 插件

- 位置:`dmnotifier/plugins/consumers/float/float.go`;注册:`cmd/dmnotifier/main.go` 加 import
- 实现 `plugin.ConsumerPlugin`;配置字段(插件级):`socket`(路径,默认 `$XDG_RUNTIME_DIR/bilidm-danmaku.sock`)、`queueSize`(默认 500)
- 启用方式:dmnotifier `config.yaml` 的 `pipeline.plugins` 追加:

  ```yaml
  - name: float
    enabled: true
    messagetypes: [Chat, Gift, Subscribe, SuperChat]
  ```

  `EnterRoom`/`Like` 由此处过滤(overlay 侧不做类型过滤决策)
- **连接模型**:overlay bind socket(服务端);插件启动时与断开后均每 2s 尝试连接
- **背压**:当队列满:丢弃最旧 `Chat`;`Gift`/`SuperChat`/`Subscribe` 单独限量(50),满了才丢,保证重要消息优先
- 断连期间消息静默丢弃,无缓冲

### 4.2 消息协议(JSON lines,每行一条)

```json
{"time":"2026-08-21T14:23:45+08:00","platform":"bilibili","rid":"689422","type":"chat","name":"Alice","content":"主播你好呀"}
{"time":"...","platform":"bilibili","rid":"689422","type":"gift","name":"Bob","item":"辣条","num":20,"price":0.1}
{"time":"...","platform":"bilibili","rid":"689422","type":"superchat","name":"Carol","content":"加油!","price":30}
{"time":"...","platform":"bilibili","rid":"689422","type":"subscribe","name":"Dave","item":"大航海","num":1,"price":150}
```

- `type` 小写:`chat` / `gift` / `superchat` / `subscribe`;`platform` 小写(`bilibili` 等)
- 字段为 UniBarrage 对应消息的直通+归一化;`platform/rid` 恒在
- overlay 解析失败的行:跳过并 log,不中断

### 4.3 Bilidm Overlay 程序

- 包名 `bilidm_overlay`,入口 `bilidm-overlay`;主要处理循环 `qasync` 集成 asyncio
- `client.py`:以 asyncio 服务端监听 Unix socket(标准库 `asyncio.start_server`,无需 aiohttp);每连接按行解析 JSON 进队列;启动时探测残留 socket:`ECONNREFUSED` 删除重建
- **窗口**:用 `kotonoha.platform` 的 `DefaultOverlayPlatformFactory` + `QtWindowHost` 创建悬浮表面(无边框/layer-shell 置顶/半透明/点击穿透;非 layer-shell 环境回退为普通置顶窗)
- 组件划分:
  - `danmaku/model.py` — 消息数据类与解析(纯逻辑,可测)
  - `danmaku/lifecycle.py` — 有界列表:行数上限、TTL 淘汰、按 rid 分组过滤(纯逻辑,可测)
  - `danmaku/style.py` — 类型 → 颜色/前缀/图标映射(纯逻辑,可测)
  - `danmaku/wall.py` — QWidget 单 widget 自绘(QPainter),行按年龄计算 alpha;`QTimer` ~30fps 重绘
  - `window.py` — 悬浮窗装配:wall + 状态行 + 托盘
  - `config.py` — 配置加载/默认值
- **渲染行为**:
  - 新行底部插入,短暂淡入;超 `maxRows`(30)移除最旧;`ttlSeconds`(60)过半渐隐后移除
  - `chat`:平台色昵称 + 白正文;`gift`:琥珀 `🎁 昵称 赠送 <礼物>x<数量>`;`superchat`:金框大字 + `¥<价格>`;`subscribe`:蓝紫 `🏴☠️ 昵称 <航海名>x<次数>`;未知类型:小字灰
  - 合并模式单房间时隐藏来源标签;多房间显示 `B站/689422` 前缀;`per-room` 模式每 rid 一窗,各自过滤同一流
  - 点击穿透默认开;关闭时可拖拽。`QSystemTrayIcon`:切换穿透 / 设置对话框 / 退出
  - `hideWhenIdleSeconds > 0` 时无消息 N 秒后隐藏,来消息弹出(默认 0 常驻)
- **CLI**:

  ```
  bilidm-overlay --room bilibili:689422 [--room ...] [--merged|--per-room]
                 [--socket PATH] [--config PATH] [--no-tray] [--demo]
  ```

  `--demo`:内部生成假消息流跑 UI,用于调试与验收

### 4.4 配置 `~/.config/bilidm-overlay/config.yaml`

```yaml
socket: $XDG_RUNTIME_DIR/bilidm-danmaku.sock   # 变量在运行时展开
mode: merged              # merged | per-room
rooms:                    # 用于来源标签与分窗过滤
  - bilibili:689422
position: [24, 100]       # 左下角偏移(px)
width: 420
maxRows: 30
ttlSeconds: 60
font: [Noto Sans CJK SC, 13]
opacity: 0.85
clickThrough: true
hideWhenIdleSeconds: 0
```

CLI 参数优先于配置文件。

## 5. 启动脚本

`overlay/scripts/start.sh`(幂等,可重复执行):

1. 探测 `127.0.0.1:7777` 存活;否则报错并提示先启动 UniBarrage(不代管其进程)
2. `dmnotifier start`(对每个 `--room` 传入;自动从 config/CLI 读取;已订阅则跳过)
3. 后台拉起 `bilidm-overlay`,`wait` 等待退出

`stop.sh`:`dmnotifier stop` + 结束 overlay 进程。README 附 niri keybind 示例。

## 6. 错误处理与健壮性

| 故障 | 行为 |
|------|------|
| overlay 被杀/重开 | float 插件每 2s 重连;期间消息丢弃,不影响 dmnotifier |
| dmnotifier 未运行 | overlay 空窗,状态行"dmnotifier 离线,重连中…";消息来即恢复 |
| UniBarrage 断线 | dmnotifier 自身 WS 重连处理;overlay 无感知 |
| 残留 socket 文件 | 启动时探测:可连则复用;`ECONNREFUSED` 删除重建 |
| 背压溢出 | 插件有界队列:丢最旧 Chat;礼物/SC 限量保护 |
| 解析坏行 | 跳过并 log |
| sigterm/sigint | 干净退出,移除 socket 文件 |

## 7. 测试策略

- **overlay(pytest,无头)**:model 解析、style 映射、lifecycle(行数/TTL/分窗过滤)、config 默认值与 CLI 覆盖;目标 80%+ 覆盖(纯逻辑部分)
- **float 插件(Go test)**:序列化 JSON 行、背压丢弃、重连循环(短 tick 注入)
- **GUI**:手动验收(`--demo` + 真实房间);自动化视觉回归不做(个人工具,成本>收益),计划文档中给出手动清单
- **集成冒烟**:start.sh 真实订阅 + 肉眼确认悬浮/穿透/高亮

## 8. 依赖与打包

- `overlay/pyproject.toml`:uv 管理;Python `>=3.13`(kotonoha 基准版本)
- 依赖:`PyQt6`、`qasync`、`kotonoha = { path = "../kotonoha" }`(锁定克隆 commit;kotonoha 构建时自动编译原生桥)
- 开发依赖:`pytest`、`pytest-asyncio`、`ruff`
- kotonoha 的 license:`MIT AND LGPL-2.1-or-later`(blur 协议随编译产物),依赖即遵守,无需复制文件
- dmnotifier 侧改动保留在其自身仓库(本地提交)

## 9. 非目标

- 不做头像/房间头像(留后续)
- 不推 dmnotifier 上游、不改 kotonoha/UniBarrage 源码
- 不代管 UniBarrage 进程与升级
- 不做历史重放/本地落盘
- 不做 Web/浏览器端实现

## 10. 验收标准

- [ ] `scripts/start.sh` 一键拉起:真实订阅 bilibili 房间,悬浮窗显示弹幕滚动墙
- [ ] 点击穿透:鼠标可透过悬浮窗操作桌面/游戏/浏览器
- [ ] Chat 常规行、gift/superchat/subscribe 高亮显示;EnterRoom/Like 不出现
- [ ] overlay `kill` 后 `dmnotifier list` 正常、重开 overlay 自动恢复显示
- [ ] 每房一窗模式(per-room)正确按 rid 过滤
- [ ] `pytest` 与 `go test ./...` 通过,纯逻辑部分覆盖率 ≥ 80%
