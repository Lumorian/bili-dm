# Bilidm Overlay 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Arch/Wayland/niri 桌面上以悬浮点击穿透窗口展示 B 站直播间弹幕,数据链路 UniBarrage → dmnotifier(float 插件) → Unix socket → Bilidm Overlay。

**Architecture:** 复用 kotonoha 的 Wayland layer-shell platform 层(uv path 依赖),overlay 是独立的 PyQt6 程序(作为 socket 服务端);dmnotifier 本地新增 float consumer 插件(客户端,断线每 2s 重连)把弹幕以 JSON lines 推给 overlay。纯逻辑(解析/样式/生命周期/配置/socket 协议)全部可无头测试。

**Tech Stack:** Python 3.13 (uv)、PyQt6、qasync、kotonoha (path 依赖,自带原生 libkoto-layer.so)、Go (dmnotifier 插件)、pytest/pytest-asyncio/pytest-cov。

**Spec:** `docs/superpowers/specs/2026-08-21-bilidm-overlay-design.md`(执行者须先读它)

## Global Constraints

- 环境:Arch Linux,Wayland + niri;所有命令在 `overlay/` 项目目录下执行,除非注明
- socket 默认路径:`$XDG_RUNTIME_DIR/bilidm-danmaku.sock`(运行时展开)
- 协议:`type` 小写(`chat`/`gift`/`superchat`/`subscribe`);`platform` 小写;JSON lines,每行一条,即时丢弃不重放
- dmnotifier 配置中 `messagetypes` 用大写开头:`[Chat, Gift, Subscribe, SuperChat]`(与 dmnotifier 现有约定一致)
- 背压:chat 队列 500 丢最旧;礼物/SC/订阅队列 50 丢最旧,先排水;`platform`/`rid` 字段恒在
- Python `>=3.13`;纯逻辑(pydanmaku/model/style/lifecycle/config/client)覆盖率 ≥ 80%
- 不改 kotonoha、UniBarrage 源码;dmnotifier 只在 `plugins/consumers/float/` + `cmd/dmnotifier/main.go` 加一行 import
- 行数上限默认 30,TTL 默认 60s;窗口默认左下角(24,100),宽 420,透明度 0.85,点击穿透默认开

---

### Task 1: overlay 项目脚手架与依赖

**Files:**
- Create: `overlay/pyproject.toml`, `overlay/.gitignore`, `overlay/README.md`, `overlay/src/bilidm_overlay/__init__.py`, `overlay/src/bilidm_overlay/danmaku/__init__.py`

**Interfaces:**
- Consumes: 无(本任务只搭壳)
- Produces: 可运行的 uv 项目;入口 `bilidm-overlay = bilidm_overlay.main:entry_point`(main.py 在 Task 8 创建,此时先不写入口,任务 8 再加)

- [ ] **Step 1: 安装系统依赖并确认 uv**

Run:
```bash
sudo pacman -S cmake qt6-base qt6-wayland layer-shell-qt uv
uv --version
python3 --version
```
Expected: uv ≥ 0.4;python 无 3.13 也没关系,uv 会下载(下一步)。

- [ ] **Step 2: 初始化 pyproject.toml**

Create `pyproject.toml`:

```toml
[project]
name = "bilidm-overlay"
version = "0.1.0"
description = "Floating click-through danmaku overlay for bilibili live rooms (Wayland)"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "PyQt6",
    "qasync",
    "kotonoha",
]

[tool.uv.sources]
kotonoha = { path = "../kotonoha" }

[project.scripts]
bilidm-overlay = "bilidm_overlay.main:entry_point"

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-asyncio",
    "pytest-cov",
    "ruff",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/bilidm_overlay"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
```

Run(`uv sync --extra dev` 会同时编译 kotonoha 的原生桥,第一次较久):
```bash
uv python pin 3.13
uv sync --extra dev
uv run python -c "import kotonoha.platform; print('platform ok')"
```
Expected: `platform ok`。

- [ ] **Step 3: 建包骨架与 .gitignore**

Create `src/bilidm_overlay/__init__.py`(空文件)与 `src/bilidm_overlay/danmaku/__init__.py`(空文件)。

Create `.gitignore`:

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
.coverage
htmlcov/
dist/
```

Create `README.md`(先写一行标题 `# Bilidm Overlay`,内容 Task 10 补全)。

- [ ] **Step 4: 验证项目可安装**

Run:
```bash
uv run python -c "import bilidm_overlay; print('ok')"
```
Expected: `ok`。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore README.md src/
git commit -m "chore: 初始化 bilidm-overlay uv 项目(依赖 kotonoha platform 层)"
```

---

### Task 2: 弹幕消息模型 model.py

**Files:**
- Create: `overlay/src/bilidm_overlay/danmaku/model.py`
- Test: `overlay/tests/test_model.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `@dataclass(slots=True) Danmaku` 字段:`time: datetime | None`、`platform: str`、`rid: str`、`type: str`(小写归一)、`name: str`、`content: str`、`item: str | None = None`、`num: int = 1`、`price: float | None = None`
  - `parse_message(line: str) -> Danmaku`(坏行抛 `ValueError`,由调用方捕获)

- [ ] **Step 1: 写失败测试**

Create `tests/test_model.py`:

```python
from datetime import datetime

import pytest

from bilidm_overlay.danmaku.model import Danmaku, parse_message


def test_parses_chat_line():
    line = '{"time":"2026-08-21T20:00:00+08:00","platform":"bilibili","rid":"689422","type":"chat","name":"Alice","content":"你好"}'
    d = parse_message(line)
    assert d.type == "chat"
    assert d.name == "Alice"
    assert d.content == "你好"
    assert d.platform == "bilibili"
    assert d.rid == "689422"
    assert d.time == datetime(2026, 8, 21, 20, 0, 0, tzinfo=__import__("datetime").timezone.utc)
    assert d.item is None


def test_parses_gift_line():
    line = '{"time":"2026-08-21T20:00:00+08:00","platform":"bilibili","rid":"689422","type":"gift","name":"Bob","item":"辣条","num":20,"price":0.1}'
    d = parse_message(line)
    assert d.type == "gift"
    assert d.item == "辣条"
    assert d.num == 20
    assert d.price == 0.1


def test_parses_superchat_line():
    line = '{"time":"2026-08-21T20:00:00+08:00","platform":"bilibili","rid":"689422","type":"superchat","name":"Carol","content":"加油!","price":30}'
    d = parse_message(line)
    assert d.type == "superchat"
    assert d.price == 30


def test_parses_subscribe_line():
    line = '{"time":"2026-08-21T20:00:00+08:00","platform":"bilibili","rid":"689422","type":"subscribe","name":"Dave","item":"大航海","num":1}'
    d = parse_message(line)
    assert d.type == "subscribe"
    assert d.item == "大航海"


def test_normalizes_unknown_type_to_lowercase():
    d = parse_message('{"type":"EnterRoom","name":"Eve"}')
    assert d.type == "enterroom"
    assert d.name == "Eve"


def test_missing_time_becomes_none():
    d = parse_message('{"type":"chat","name":"F"}')
    assert d.time is None
    assert d.content == ""


def test_bad_json_raises_value_error():
    with pytest.raises(ValueError):
        parse_message("not json")
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_model.py -v`
Expected: FAIL(`ImportError: cannot import name 'parse_message'`)

- [ ] **Step 3: 最小实现**

Create `src/bilidm_overlay/danmaku/model.py`:

```python
"""弹幕消息模型与 UniBarrage JSON lines 解析。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Danmaku:
    time: datetime | None = None
    platform: str = ""
    rid: str = ""
    type: str = "unknown"
    name: str = ""
    content: str = ""
    item: str | None = None
    num: int = 1
    price: float | None = None


def parse_message(line: str) -> Danmaku:
    """解析一行 JSON 弹幕;坏输入抛 ValueError。"""
    raw = json.loads(line)
    if not isinstance(raw, dict):
        raise ValueError(f"message must be a JSON object: {line!r}")
    d = Danmaku(
        platform=str(raw.get("platform", "")),
        rid=str(raw.get("rid", "")),
        type=str(raw.get("type", "unknown")).lower(),
        name=str(raw.get("name", "")),
        content=str(raw.get("content", "")),
    )
    raw_time = raw.get("time")
    if raw_time:
        d.time = datetime.fromisoformat(str(raw_time))
    if "item" in raw:
        d.item = str(raw["item"])
    if "num" in raw:
        d.num = int(raw["num"])
    if "price" in raw:
        d.price = float(raw["price"])
    return d
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_model.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/bilidm_overlay/danmaku/model.py tests/test_model.py
git commit -m "feat: 弹幕消息模型与 JSON 解析"
```

---

### Task 3: 类型样式映射 style.py

**Files:**
- Create: `overlay/src/bilidm_overlay/danmaku/style.py`
- Test: `overlay/tests/test_style.py`

**Interfaces:**
- Consumes: `Danmaku`(Task 2)
- Produces:
  - `@dataclass(frozen=True, slots=True) StyleSpec` 字段:`name_color: str`、`text_color: str`、`prefix: str`、`border: bool`、`size_scale: float`
  - `style_for(d: Danmaku) -> StyleSpec`
  - `PLATFORM_COLORS: dict[str, str]`(bilibili/douyin/kuaishou/douyu/huya/xiaohongshu + 默认色)

- [ ] **Step 1: 写失败测试**

Create `tests/test_style.py`:

```python
from bilidm_overlay.danmaku.model import Danmaku
from bilidm_overlay.danmaku.style import PLATFORM_COLORS, style_for


def make(**kw):
    base = dict(type="chat", name="Alice", content="hi")
    base.update(kw)
    return Danmaku(**base)


def test_chat_uses_platform_color():
    spec = style_for(make(platform="bilibili"))
    assert spec.name_color == PLATFORM_COLORS["bilibili"]
    assert spec.prefix == ""
    assert spec.border is False
    assert spec.size_scale == 1.0


def test_gift_amber_with_prefix():
    spec = style_for(make(type="gift", item="辣条", num=20))
    assert spec.prefix == "🎁 "
    assert spec.name_color == "#F5A623"
    assert spec.border is False


def test_superchat_gold_border_bigger():
    spec = style_for(make(type="superchat", price=30))
    assert spec.prefix == "💰 "
    assert spec.border is True
    assert spec.size_scale == 1.25
    assert spec.name_color == "#FFD700"


def test_subscribe_blue_purple():
    spec = style_for(make(type="subscribe", item="大航海", num=1))
    assert spec.prefix == "🏴‍☠️ "
    assert spec.name_color == "#7B68EE"


def test_unknown_type_is_grey():
    spec = style_for(make(type="enterroom", name="Eve"))
    assert spec.prefix == ""
    assert spec.name_color == "#9AA0A6"
    assert spec.text_color == "#B8BCC2"


def test_unknown_platform_falls_back():
    spec = style_for(make(platform="weird"))
    assert spec.name_color == PLATFORM_COLORS["default"]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_style.py -v`
Expected: FAIL(`ImportError`)

- [ ] **Step 3: 最小实现**

Create `src/bilidm_overlay/danmaku/style.py`:

```python
"""消息类型 → 视觉样式映射(纯逻辑,无 Qt 依赖)。"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Danmaku

PLATFORM_COLORS: dict[str, str] = {
    "bilibili": "#FB7299",
    "douyin": "#FE2C55",
    "kuaishou": "#FF6A00",
    "douyu": "#FF6E00",
    "huya": "#F8B300",
    "xiaohongshu": "#FF2442",
    "default": "#8A8B93",
}


@dataclass(frozen=True, slots=True)
class StyleSpec:
    name_color: str
    text_color: str
    prefix: str
    border: bool
    size_scale: float


def style_for(d: Danmaku) -> StyleSpec:
    if d.type == "gift":
        return StyleSpec("#F5A623", "#FFD591", "🎁 ", False, 1.0)
    if d.type == "superchat":
        return StyleSpec("#FFD700", "#FFF7D6", "💰 ", True, 1.25)
    if d.type == "subscribe":
        return StyleSpec("#7B68EE", "#C5B8F0", "🏴‍☠️ ", False, 1.0)
    if d.type == "chat":
        return StyleSpec(PLATFORM_COLORS.get(d.platform, PLATFORM_COLORS["default"]), "#FFFFFF", "", False, 1.0)
    return StyleSpec("#9AA0A6", "#B8BCC2", "", False, 0.95)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_style.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/bilidm_overlay/danmaku/style.py tests/test_style.py
git commit -m "feat: 弹幕样式映射(类型/平台色/高亮)"
```

---

### Task 4: 滚动墙生命周期 lifecycle.py

**Files:**
- Create: `overlay/src/bilidm_overlay/danmaku/lifecycle.py`
- Test: `overlay/tests/test_lifecycle.py`

**Interfaces:**
- Consumes: `Danmaku`(Task 2)
- Produces:
  - `@dataclass(slots=True) Row` 字段:`msg: Danmaku`、`born: float`
  - `class Wall`:`__init__(self, max_rows: int = 30, ttl: float = 60.0)`;`add(self, msg: Danmaku, now: float) -> None`;`prune(self, now: float) -> None`;`snapshot(self) -> list[Row]`(旧→新);`alpha_of(self, row: Row, now: float) -> float`(TTL 过半后线性淡出,到期 0)

- [ ] **Step 1: 写失败测试**

Create `tests/test_lifecycle.py`:

```python
from bilidm_overlay.danmaku.lifecycle import Wall
from bilidm_overlay.danmaku.model import Danmaku


def msg(content="hi"):
    return Danmaku(name="A", content=content)


def test_add_and_snapshot_order():
    wall = Wall(max_rows=3, ttl=60)
    wall.add(msg("1"), now=0.0)
    wall.add(msg("2"), now=1.0)
    rows = wall.snapshot()
    assert len(rows) == 2
    assert rows[0].msg.content == "1"
    assert rows[1].msg.content == "2"
    assert rows[1].born == 1.0


def test_max_rows_evicts_oldest():
    wall = Wall(max_rows=3, ttl=60)
    for i, t in enumerate([0.0, 1.0, 2.0, 3.0]):
        wall.add(msg(str(i)), now=t)
    assert [r.msg.content for r in wall.snapshot()] == ["1", "2", "3"]


def test_prune_expires_by_ttl():
    wall = Wall(max_rows=10, ttl=60)
    wall.add(msg("old"), now=0.0)
    wall.add(msg("new"), now=50.0)
    wall.prune(now=61.0)
    assert [r.msg.content for r in wall.snapshot()] == ["new"]


def test_alpha_fade_curve():
    wall = Wall(max_rows=10, ttl=60)
    wall.add(msg("x"), now=0.0)
    assert wall.alpha_of(wall.snapshot()[0], now=0.0) == 1.0
    assert wall.alpha_of(wall.snapshot()[0], now=45.0) == 0.5
    assert wall.alpha_of(wall.snapshot()[0], now=60.0) == 0.0
    assert wall.alpha_of(wall.snapshot()[0], now=90.0) == 0.0
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_lifecycle.py -v`
Expected: FAIL(`ImportError`)

- [ ] **Step 3: 最小实现**

Create `src/bilidm_overlay/danmaku/lifecycle.py`:

```python
"""滚动墙的纯逻辑:有界行数、TTL 淘汰、淡出曲线(无 Qt 依赖,可无头测试)。"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Danmaku


@dataclass(slots=True)
class Row:
    msg: Danmaku
    born: float  # 单调时钟秒


class Wall:
    def __init__(self, max_rows: int = 30, ttl: float = 60.0) -> None:
        self._max_rows = max_rows
        self._ttl = ttl
        self._rows: list[Row] = []

    def add(self, msg: Danmaku, now: float) -> None:
        self.prune(now)
        self._rows.append(Row(msg=msg, born=now))
        if len(self._rows) > self._max_rows:
            del self._rows[: len(self._rows) - self._max_rows]

    def prune(self, now: float) -> None:
        self._rows = [r for r in self._rows if now - r.born <= self._ttl]

    def snapshot(self) -> list[Row]:
        return list(self._rows)

    def clear(self) -> None:
        self._rows.clear()

    def alpha_of(self, row: Row, now: float) -> float:
        """TTL 前一半 1.0,后一半线性淡出到 0,过期 0。"""
        age = max(0.0, now - row.born)
        if age >= self._ttl:
            return 0.0
        half = self._ttl / 2
        if age <= half:
            return 1.0
        return 1.0 - (age - half) / half
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_lifecycle.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/bilidm_overlay/danmaku/lifecycle.py tests/test_lifecycle.py
git commit -m "feat: 滚动墙生命周期(行数上限/TTL/淡出曲线)"
```

---

### Task 5: 配置 config.py

**Files:**
- Create: `overlay/src/bilidm_overlay/config.py`
- Test: `overlay/tests/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `@dataclass(slots=True) Config` 字段(默认值即 Global Constraints):`socket`、`mode: str`、`rooms: list[str]`、`position: list[int]`、`width: int`、`max_rows: int`、`ttl_seconds: float`、`font_family: str`、`font_size: int`、`opacity: float`、`click_through: bool`、`hide_when_idle_seconds: int`、`no_tray: bool`
  - `default_socket_path() -> str`(= `$XDG_RUNTIME_DIR/bilidm-danmaku.sock`)
  - `load(path: Path | None = None) -> Config`(yaml 加载 + 环境变量展开,缺省文件用默认值)
  - `merge_cli(cfg: Config, args: argparse.Namespace) -> Config`

- [ ] **Step 1: 写失败测试**

Create `tests/test_config.py`:

```python
import argparse
from pathlib import Path

from bilidm_overlay.config import Config, default_socket_path, load, merge_cli


def test_default_socket_uses_runtime_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert default_socket_path() == f"{tmp_path}/bilidm-danmaku.sock"


def test_defaults():
    cfg = Config()
    assert cfg.mode == "merged"
    assert cfg.max_rows == 30
    assert cfg.ttl_seconds == 60.0
    assert cfg.click_through is True
    assert cfg.opacity == 0.85
    assert cfg.position == [24, 100]


def test_load_expands_env_and_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    f = tmp_path / "cfg.yaml"
    f.write_text("socket: $XDG_RUNTIME_DIR/test.sock\nwidth: 600\nrooms:\n  - bilibili:689422\n")
    cfg = load(f)
    assert cfg.socket == f"{tmp_path}/test.sock"
    assert cfg.width == 600
    assert cfg.rooms == ["bilibili:689422"]
    # 未写的字段保持默认
    assert cfg.ttl_seconds == 60.0


def test_load_missing_file_is_defaults(tmp_path):
    cfg = load(tmp_path / "nope.yaml")
    assert cfg.mode == "merged"


def test_merge_cli_overrides():
    cfg = Config()
    args = argparse.Namespace(room=["bilibili:689422"], socket="/tmp/x.sock", no_tray=True,
                              merged=None, per_room=None)
    merged = merge_cli(cfg, args)
    assert merged.rooms == ["bilibili:689422"]
    assert merged.socket == "/tmp/x.sock"
    assert merged.no_tray is True
    # flags 未给时不变
    assert merged.mode == "merged"


def test_merge_cli_per_room_flag_wins():
    cfg = Config()
    args = argparse.Namespace(room=["bilibili:1", "bilibili:2"], merged=None, per_room=True,
                              socket=None, no_tray=None)
    assert merge_cli(cfg, args).mode == "per-room"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL(`ImportError`)

- [ ] **Step 3: 最小实现**

Create `src/bilidm_overlay/config.py`:

```python
"""XDG 配置加载:yaml + 环境变量展开 + CLI 合并。"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_ENV_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


def default_socket_path() -> str:
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "bilidm-danmaku.sock")


@dataclass(slots=True)
class Config:
    socket: str = field(default_factory=default_socket_path)
    mode: str = "merged"  # merged | per-room
    rooms: list[str] = field(default_factory=list)
    position: list[int] = field(default_factory=lambda: [24, 100])
    width: int = 420
    max_rows: int = 30
    ttl_seconds: float = 60.0
    font_family: str = "Noto Sans CJK SC"
    font_size: int = 13
    opacity: float = 0.85
    click_through: bool = True
    hide_when_idle_seconds: int = 0
    no_tray: bool = False


def _expand(s: str) -> str:
    def repl(m: re.Match) -> str:
        return os.environ.get(m.group(1), "")

    return _ENV_RE.sub(repl, s)


def load(path: Path | None = None) -> Config:
    cfg = Config()
    p = path or Path(os.path.expanduser("~/.config/bilidm-overlay/config.yaml"))
    if not p.is_file():
        return cfg
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    for k, v in data.items():
        if not hasattr(cfg, k):
            continue
        if k == "socket" and isinstance(v, str):
            v = _expand(v)
        setattr(cfg, k, v)
    return cfg


def merge_cli(cfg: Config, args: argparse.Namespace) -> Config:
    if getattr(args, "room", None):
        cfg.rooms = list(args.room)
    if getattr(args, "socket", None):
        cfg.socket = _expand(args.socket)
    if getattr(args, "per_room", None):
        cfg.mode = "per-room"
    elif getattr(args, "merged", None):
        cfg.mode = "merged"
    if getattr(args, "no_tray", None):
        cfg.no_tray = True
    return cfg
```

(`pyproject.toml` 需要加 `yaml` 依赖——`uv add pyyaml`,在 Step 4 前执行。)

- [ ] **Step 4: 运行确认通过**

Run:
```bash
uv add pyyaml
uv run pytest tests/test_config.py -v
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/bilidm_overlay/config.py tests/test_config.py pyproject.toml uv.lock
git commit -m "feat: XDG 配置加载与 CLI 合并"
```

---

### Task 6: Unix socket 服务端 client.py

**Files:**
- Create: `overlay/src/bilidm_overlay/client.py`
- Test: `overlay/tests/test_client.py`

**Interfaces:**
- Consumes: `parse_message`、`Danmaku`(Task 2)
- Produces:
  - `class DanmakuServer`:`__init__(self, socket_path: str, on_message: Callable[[Danmaku], None])`;`async start(self) -> None`;`async stop(self) -> None`;`connected(self) -> bool`(当前是否有活跃客户端连接,供状态行显示)
  - `ensure_stale_socket_removed(socket_path: str) -> None`(可连接→抛 `OSError("socket already in use")`;`ConnectionRefusedError`→删除)

- [ ] **Step 1: 写失败测试**

Create `tests/test_client.py`:

```python
import asyncio
import os

import pytest

from bilidm_overlay.client import DanmakuServer, ensure_stale_socket_removed
from bilidm_overlay.danmaku.model import Danmaku


async def test_receives_messages(tmp_path):
    sock = str(tmp_path / "d.sock")
    got: list[Danmaku] = []
    srv = DanmakuServer(sock, got.append)
    await srv.start()
    try:
        reader, writer = await asyncio.open_unix_connection(sock)
        writer.write(b'{"type":"chat","name":"A","content":"hi"}\n')
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.close()
        await writer.wait_closed()
    finally:
        await srv.stop()
    assert got and got[0].name == "A" and got[0].content == "hi"


async def test_bad_line_skipped_not_crash(tmp_path):
    sock = str(tmp_path / "d.sock")
    got: list[Danmaku] = []
    srv = DanmakuServer(sock, got.append)
    await srv.start()
    try:
        reader, writer = await asyncio.open_unix_connection(sock)
        writer.write(b"not json\n")
        writer.write(b'{"type":"chat","name":"B"}\n')
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.close()
        await writer.wait_closed()
    finally:
        await srv.stop()
    assert len(got) == 1 and got[0].name == "B"


async def test_multiline_frame(tmp_path):
    sock = str(tmp_path / "d.sock")
    got: list[Danmaku] = []
    srv = DanmakuServer(sock, got.append)
    await srv.start()
    try:
        reader, writer = await asyncio.open_unix_connection(sock)
        writer.write(b'{"type":"chat","name":"C"}\n{"type":"chat","name":"D"}\n')
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.close()
        await writer.wait_closed()
    finally:
        await srv.stop()
    assert [g.name for g in got] == ["C", "D"]


def test_stale_socket_removed(tmp_path):
    sock = os.path.join(str(tmp_path), "stale.sock")
    s = __import__("socket").socket(__import__("socket").AF_UNIX, __import__("socket").SOCK_STREAM)
    s.bind(sock)
    s.close()  # 无人监听 -> 属于残留文件
    ensure_stale_socket_removed(sock)
    assert not os.path.exists(sock)


def test_live_socket_not_removed(tmp_path):
    sock = os.path.join(str(tmp_path), "live.sock")
    import socket

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(sock)
    s.listen(1)
    with pytest.raises(OSError, match="already in use"):
        ensure_stale_socket_removed(sock)
    s.close()
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_client.py -v`
Expected: FAIL(`ImportError`)

- [ ] **Step 3: 最小实现**

Create `src/bilidm_overlay/client.py`:

```python
"""Unix socket 服务端:接收 dmnotifier float 插件的 JSON lines。"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Callable

from .danmaku.model import Danmaku, parse_message

logger = logging.getLogger(__name__)


def ensure_stale_socket_removed(socket_path: str) -> None:
    """探测残留 socket:能连上说明有人在用,抛错;连接被拒说明是残留文件,删除。"""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(socket_path)
    except ConnectionRefusedError:
        os.unlink(socket_path)
    except FileNotFoundError:
        pass  # 不存在,无需处理
    else:
        raise OSError(f"socket already in use: {socket_path}")
    finally:
        s.close()


class DanmakuServer:
    def __init__(self, socket_path: str, on_message: Callable[[Danmaku], None]) -> None:
        self._path = socket_path
        self._on_message = on_message
        self._server: asyncio.Server | None = None
        self._conns: set[asyncio.StreamWriter] = set()

    def connected(self) -> bool:
        return bool(self._conns)

    async def start(self) -> None:
        ensure_stale_socket_removed(self._path)
        self._server = await asyncio.start_unix_server(self._handler, path=self._path)

    async def stop(self) -> None:
        for writer in list(self._conns):
            writer.close()
        self._conns.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        try:
            os.unlink(self._path)
        except FileNotFoundError:
            pass

    async def _handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._conns.add(writer)
        try:
            while line := await reader.readline():
                if not line.strip():
                    continue
                try:
                    self._on_message(parse_message(line.decode("utf-8", errors="replace")))
                except ValueError as exc:
                    logger.warning("skipping bad danmaku line: %s", exc)
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        finally:
            self._conns.discard(writer)
            writer.close()
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_client.py -v`
Expected: 5 passed

- [ ] **Step 5: 覆盖率检查(本任务起纯逻辑已达 80% 目标)**

Run: `uv run pytest --cov=bilidm_overlay --cov-report=term-missing`
Expected: 全模块合计 ≥ 80%(model/style/lifecycle/config/client 均被覆盖)

- [ ] **Step 6: Commit**

```bash
git add src/bilidm_overlay/client.py tests/test_client.py
git commit -m "feat: Unix socket 服务端(残留清理/坏行跳过)"
```

---

### Task 7: 滚动墙渲染 widget wall.py

**Files:**
- Create: `overlay/src/bilidm_overlay/danmaku/wall.py`
- Test: `overlay/tests/test_wall_offscreen.py`

**Interfaces:**
- Consumes: `Wall`、`Row`(Task 4)、`style_for`/`StyleSpec`(Task 3)
- Produces:
  - `class WallWidget(QWidget)`:`__init__`;`update_wall(self, wall: Wall, now: float) -> None`(存行列供 paint);`set_font(self, family: str, size: int) -> None`;`set_panel_opacity(self, opacity: float) -> None`;`paintEvent` 自绘(Chat 行前缀平台色昵称 + 白字,礼物/SC/订阅带样式;按 `alpha_of` 淡出;超宽自动折行)

- [ ] **Step 1: 写 offscreen 冒烟测试**

Create `tests/test_wall_offscreen.py`(GUI 部分只做冒烟,不追求覆盖率):

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QPaintEvent, QPainter
from PyQt6.QtWidgets import QApplication

from bilidm_overlay.danmaku.lifecycle import Wall
from bilidm_overlay.danmaku.model import Danmaku
from bilidm_overlay.danmaku.wall import WallWidget


def test_paints_rows_without_error():
    app = QApplication.instance() or QApplication([])
    widget = WallWidget()
    widget.resize(400, 300)
    wall = Wall(max_rows=5, ttl=60)
    wall.add(Danmaku(type="chat", platform="bilibili", name="A", content="你好"), now=0.0)
    wall.add(Danmaku(type="gift", name="B", item="辣条", num=20), now=1.0)
    wall.add(Danmaku(type="superchat", name="C", content="加油!", price=30), now=1.5)
    widget.update_wall(wall, now=2.0)
    painter = QPainter(widget)
    widget.paintEvent(QPaintEvent(widget.rect()))
    painter.end()
    assert widget.row_count() == 3  # 三行均已入墙,绘制过程无异常


def test_clear_rows():
    app = QApplication.instance() or QApplication([])
    widget = WallWidget()
    widget.update_wall(Wall(), now=0.0)
    widget.update_wall(wall := Wall(), now=0.0)
    wall.add(Danmaku(name="A"), now=0.0)
    widget.update_wall(wall, now=0.0)
    wall.clear()
    widget.update_wall(wall, now=0.0)
    assert widget.row_count() == 0
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_wall_offscreen.py -v`
Expected: FAIL(`ImportError`)

- [ ] **Step 3: 最小实现**

Create `src/bilidm_overlay/danmaku/wall.py`:

```python
"""滚动墙渲染:单 widget 自绘,行按年龄淡出。"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QTextLayout
from PyQt6.QtWidgets import QWidget

from .lifecycle import Row, Wall
from .style import style_for


class WallWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._font = QFont()
        self._wall: Wall | None = None
        self._now = 0.0
        self._show_tag = False

    def set_font(self, family: str, size: int) -> None:
        self._font = QFont(family, size)
        self.update()

    def set_show_tag(self, show: bool) -> None:
        """合并模式多房间时,每行前缀显示 platform/rid 标签。"""
        self._show_tag = show
        self.update()

    def set_panel_opacity(self, opacity: float) -> None:
        self.setAutoFillBackground(True)
        pal = self.palette()
        bg = QColor(16, 16, 20)
        bg.setAlphaF(opacity)
        pal.setColor(self.backgroundRole(), bg)
        self.setPalette(pal)

    def update_wall(self, wall: Wall, now: float) -> None:
        self._wall = wall
        self._now = now
        self.update()

    def row_count(self) -> int:
        return len(self._wall.snapshot()) if self._wall else 0

    def paintEvent(self, event) -> None:
        del event
        if self._wall is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        rows = self._wall.snapshot()
        y = 6.0
        for row in rows:
            alpha = self._wall.alpha_of(row, self._now)
            if alpha <= 0.0:
                continue
            spec = style_for(row.msg)
            y = self._paint_row(painter, row, spec, y, alpha) + 4.0
        painter.end()

    def _paint_row(self, painter: QPainter, row: Row, spec, y: float, alpha: float) -> float:
        size = 13 * spec.size_scale
        font = QFont(self._font)
        font.setPixelSize(int(size))
        painter.setFont(font)
        fm = painter.fontMetrics()
        tag = ""
        if self._show_tag and row.msg.platform and row.msg.rid:
            tag = f"{row.msg.platform}/{row.msg.rid} "
        name = f"{spec.prefix}{row.msg.name} "
        text = f"{tag}{name}{row.msg.content}"
        color = QColor(spec.name_color)
        color.setAlphaF(alpha)
        painter.setPen(color)
        if fm.horizontalAdvance(text) > self.width() - 12:
            text = fm.elidedText(text, Qt.TextElideMode.ElideRight, self.width() - 12)
        painter.drawText(QRectF(6, y, self.width() - 12, fm.height()), Qt.AlignmentFlag.AlignVCenter, text)
        return y + fm.height()
```

(注:折行按"28 字宽"取宽并 elide,保证 v1 不溢出;后续要完整 wrap 再改 QTextLayout。)

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_wall_offscreen.py -v`
Expected: 2 passed

- [ ] **Step 5: 手工看效果**

Run:
```bash
QT_QPA_PLATFORM=offscreen uv run python -c "
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from PyQt6.QtWidgets import QApplication
from bilidm_overlay.danmaku.wall import WallWidget
from bilidm_overlay.danmaku.lifecycle import Wall
from bilidm_overlay.danmaku.model import Danmaku
app=QApplication([]); w=WallWidget(); w.resize(420,300)
wall=Wall(); wall.add(Danmaku(type='chat',platform='bilibili',name='Alice',content='你好'),0.0)
w.update_wall(wall,0.0); w.grab().save('/tmp/wall.png'); print('saved')
"
```
Expected: `/tmp/wall.png` 生成(无报错)。

- [ ] **Step 6: Commit**

```bash
git add src/bilidm_overlay/danmaku/wall.py tests/test_wall_offscreen.py
git commit -m "feat: 滚动墙自绘 widget(按年龄淡出+样式着色)"
```

---

### Task 8: 悬浮窗 window.py + 主入口 main.py(含 --demo 与托盘)

**Files:**
- Create: `overlay/src/bilidm_overlay/window.py`, `overlay/src/bilidm_overlay/main.py`
- Test: `overlay/tests/test_main_smoke.py`

**Interfaces:**
- Consumes:`Config`(Task 5)、`DanmakuServer`(Task 6)、`Wall`/`WallWidget`(Task 4/7)、`style_for`(Task 3)、`parse_message`(Task 2)
- Produces:
  - `class DanmakuWindow(QWidget)`:`__init__(self, cfg: Config, room_filter: str | None = None, show_tag: bool = False)`;`feed(self, d: Danmaku) -> None`(带 `room_filter` 时按 `platform:rid` 过滤,不匹配忽略);`set_passthrough(self, on: bool) -> None`;`set_status(self, text: str) -> None`;`status_text(self) -> str`;`row_count(self) -> int`;`show_window()/hide_window()`
  - 托盘:`__init__` 内按 `cfg.no_tray` 决定是否创建 `QSystemTrayIcon`;菜单项"切换点击穿透"(checkable,与 `set_passthrough` 联动)、"退出"(调 `QApplication.quit`)
  - `main.py`:`entry_point() -> None`(argparse:`--room` 可重复、`--merged`、`--per-room`、`--socket`、`--config`、`--no-tray`、`--demo`);`async def _demo_gen(sink) -> None`(每 0.4s 产一条假消息,chat/gift/superchat/subscribe 轮流);socket 服务端由 `entry_point` 持有,`on_message` 为广播函数(派发给全部窗口)

- [ ] **Step 1: 写失败测试(offscreen 冒烟)**

Create `tests/test_main_smoke.py`:

```python
import asyncio
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from bilidm_overlay.danmaku.model import Danmaku
from bilidm_overlay.window import DanmakuWindow


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _cfg(**kw):
    defaults = {
        "socket": "/tmp/none.sock", "mode": "merged", "rooms": ["bilibili:689422"],
        "width": 420, "max_rows": 30, "ttl_seconds": 60.0, "font_family": "monospace",
        "font_size": 13, "opacity": 0.85, "position": [24, 100], "click_through": True,
        "hide_when_idle_seconds": 0, "no_tray": True,
    }
    defaults.update(kw)
    return type("Cfg", (), defaults)


def test_window_accepts_danmaku(app):
    win = DanmakuWindow(_cfg())
    win.feed(Danmaku(type="chat", platform="bilibili", rid="689422", name="A", content="hi"))
    assert win.row_count() == 1
    win.set_passthrough(True)
    win.set_status("dmnotifier 离线")
    assert win.status_text() == "dmnotifier 离线"
    win.hide_window()


def test_per_room_filter_drops_other_rooms(app):
    win = DanmakuWindow(_cfg(), room_filter="bilibili:1")
    win.feed(Danmaku(type="chat", platform="bilibili", rid="2", name="A", content="other"))
    win.feed(Danmaku(type="chat", platform="bilibili", rid="1", name="B", content="mine"))
    assert win.row_count() == 1


def test_demo_generator_yields_messages(app):
    import bilidm_overlay.main as main

    async def _collect() -> None:
        sink: list[Danmaku] = []
        try:
            await asyncio.wait_for(main._demo_gen(sink), timeout=0.05)
        except asyncio.TimeoutError:
            pass  # demo gen 0.4s/条,0.05s 内只来得及产第一条
        assert len(sink) >= 1
        assert sink[0].type in {"chat", "gift", "superchat", "subscribe"}

    asyncio.run(_collect())
```

(注:`DanmakuWindow.__init__` 里布局常量与 `width` 用 `cfg.width`;`wall_widget.set_show_tag(show_tag)`。)

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_main_smoke.py -v`
Expected: FAIL(`ImportError`)

- [ ] **Step 3: 最小实现**

Create `src/bilidm_overlay/window.py`(装配 kotonoha platform,模式与 kotonoha `overlay.py:125-135` 相同):

```python
"""悬浮窗:基于 kotonoha.platform 的 Wayland layer-shell 装配。"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication, QLabel, QMenu, QStyle, QSystemTrayIcon, QVBoxLayout, QWidget

from kotonoha.platform import (
    DefaultOverlayPlatformFactory,
    LayerShellController,
    QtWindowHost,
    WindowPolicy,
    default_package_dir,
)

from .config import Config
from .danmaku.lifecycle import Wall
from .danmaku.model import Danmaku
from .danmaku.wall import WallWidget

logger = logging.getLogger(__name__)

RENDER_INTERVAL_MS = 30


class DanmakuWindow(QWidget):
    def __init__(self, cfg: Config, room_filter: str | None = None, show_tag: bool = False) -> None:
        super().__init__()
        self._cfg = cfg
        self._room_filter = room_filter
        self._wall = Wall(max_rows=cfg.max_rows, ttl=cfg.ttl_seconds)
        self._passthrough = cfg.click_through
        self._status = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(RENDER_INTERVAL_MS)

        self.setWindowTitle("Bilidm Overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        desktop = QGuiApplication.instance().property("xdg_current_desktop") or ""
        controller = LayerShellController(
            default_package_dir(), QGuiApplication.platformName(), desktop
        )
        self._host = QtWindowHost(self)
        self._platform = DefaultOverlayPlatformFactory(controller)(self._host)
        self._platform.prepare()
        self.set_passthrough(self._passthrough)

        self._wall_widget = WallWidget(self)
        self._wall_widget.set_font(cfg.font_family, cfg.font_size)
        self._wall_widget.set_panel_opacity(cfg.opacity)
        self._wall_widget.set_show_tag(show_tag)
        self._status_label = QLabel("", self)
        self._status_label.setStyleSheet("color: #9AA0A6; font-size: 11px; padding-left: 6px;")
        self._status_label.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._wall_widget)
        layout.addWidget(self._status_label)

        self._tray: QSystemTrayIcon | None = None
        if not cfg.no_tray:
            self._setup_tray()

    # --- 对外接口 ---
    def feed(self, d: Danmaku) -> None:
        if self._room_filter is not None:
            key = f"{d.platform}:{d.rid}"
            if d.rid and d.platform and key != self._room_filter:
                return
        self._wall.add(d, self._now())
        self.set_status("")
        if not self.isVisible():
            self.show()

    def row_count(self) -> int:
        return self._wall_widget.row_count()

    def status_text(self) -> str:
        return self._status

    def set_status(self, text: str) -> None:
        self._status = text
        self._status_label.setVisible(bool(text))
        self._status_label.setText(text)

    def set_passthrough(self, on: bool) -> None:
        self._passthrough = on
        self._host.apply_window_policy(
            WindowPolicy(
                transparent_for_input=on,
                mouse_events_transparent=on,
                does_not_accept_focus=True,
                recreate_surface=True,
            )
        )

    def show_window(self) -> None:
        self.show()

    def hide_window(self) -> None:
        self.hide()

    # --- 内部 ---
    def _now(self) -> float:
        import time as _t

        return _t.monotonic()

    def _tick(self) -> None:
        self._wall.prune(self._now())
        self._wall_widget.update_wall(self._wall, self._now())
        if self._cfg.hide_when_idle_seconds and self.row_count() == 0:
            self.hide_window()

    def _setup_tray(self) -> None:
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DesktopIcon)
        self._tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        toggle = menu.addAction("切换点击穿透")
        toggle.setCheckable(True)
        toggle.setChecked(self._passthrough)
        toggle.setToolTip("开启后鼠标可穿过悬浮窗;关闭后窗口可拖拽")
        toggle.triggered.connect(lambda on: self.set_passthrough(on))
        settings_action = menu.addAction("设置…")
        settings_action.triggered.connect(self._open_settings)
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(QApplication.instance().quit)
        self._tray.setContextMenu(menu)
        self._tray.show()

    def _open_settings(self) -> None:
        from .settings import SettingsDialog

        dialog = SettingsDialog(self, self._cfg)
        if dialog.exec():
            size, opacity, rows = dialog.values()
            self._cfg.font_size, self._cfg.opacity, self._cfg.max_rows = size, opacity, rows
            self._wall_widget.set_font(self._cfg.font_family, size)
            self._wall_widget.set_panel_opacity(opacity)
            # v1:行数上限即时生效,当前行清空重来;配置持久化到 yaml 属后续迭代
            self._wall = Wall(max_rows=rows, ttl=self._cfg.ttl_seconds)
```

Create `src/bilidm_overlay/settings.py`:

```python
"""轻量设置对话框:v1 仅内存生效(字号/透明度/最大行数)。"""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QSpinBox

from .config import Config


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg: Config) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self.setWindowTitle("设置")
        layout = QFormLayout(self)
        self._font = QSpinBox(self)
        self._font.setRange(9, 40)
        self._font.setValue(cfg.font_size)
        self._opacity = QDoubleSpinBox(self)
        self._opacity.setRange(0.1, 1.0)
        self._opacity.setSingleStep(0.05)
        self._opacity.setValue(cfg.opacity)
        self._rows = QSpinBox(self)
        self._rows.setRange(5, 200)
        self._rows.setValue(cfg.max_rows)
        layout.addRow("字号", self._font)
        layout.addRow("透明度", self._opacity)
        layout.addRow("最大行数", self._rows)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self) -> tuple[int, float, int]:
        """返回 (font_size, opacity, max_rows),供窗口在 exec() 后应用。"""
        return self._font.value(), self._opacity.value(), self._rows.value()
```

Create `src/bilidm_overlay/main.py`:

```python
"""入口:CLI 解析、qasync 事件循环、socket 服务端装配、--demo 假消息流。"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import signal
import sys
from pathlib import Path

import qasync
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from .config import Config, load, merge_cli
from .client import DanmakuServer
from .danmaku.model import Danmaku
from .window import DanmakuWindow

logger = logging.getLogger(__name__)

DEMO_NAMES = ["Alice", "Bob", "Carol", "Dave", "Eve"]
DEMO_LINES = [
    "主播你好呀", "前排!!", "666666", "礼物闪电链!!!",
    "刚来,前面发生了什么", "这个主播的声线我爱了",
]


def _demo_danmaku(i: int) -> Danmaku:
    if i == 0:
        return Danmaku(type="chat", platform="bilibili", rid="689422",
                       name=random.choice(DEMO_NAMES), content=random.choice(DEMO_LINES))
    if i == 1:
        return Danmaku(type="gift", platform="bilibili", rid="689422",
                       name=random.choice(DEMO_NAMES), item="辣条",
                       num=random.randint(1, 99), price=0.1)
    if i == 2:
        return Danmaku(type="superchat", platform="bilibili", rid="689422",
                       name=random.choice(DEMO_NAMES), content="加油加油!",
                       price=random.choice([30, 50, 100]))
    return Danmaku(type="subscribe", platform="bilibili", rid="689422",
                   name=random.choice(DEMO_NAMES), item="大航海", num=1, price=150)


async def _demo_gen(sink: list[Danmaku]) -> None:
    """每 0.4s 产一条假消息,chat/gift/superchat/subscribe 轮流。"""
    for i in range(30):
        sink.append(_demo_danmaku(i % 4))
        await asyncio.sleep(0.4)


def _build_windows(cfg: Config) -> list[DanmakuWindow]:
    if cfg.mode == "per-room":
        windows = []
        for room in cfg.rooms:
            if not room:
                continue
            windows.append(DanmakuWindow(cfg, room_filter=room, show_tag=False))
        return windows or [DanmakuWindow(cfg)]
    # merged:多房间时显示来源标签
    return [DanmakuWindow(cfg, show_tag=len(cfg.rooms) > 1)]


def entry_point() -> None:
    parser = argparse.ArgumentParser(prog="bilidm-overlay",
                                     description="Floating danmaku overlay for bilibili live")
    parser.add_argument("--room", action="append", help="bilibili:689422(:cookie 可选,多路可重复)")
    parser.add_argument("--merged", action="store_true")
    parser.add_argument("--per-room", action="store_true")
    parser.add_argument("--socket")
    parser.add_argument("--config")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    cfg = load(Path(args.config) if args.config else None)
    cfg = merge_cli(cfg, args)

    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    windows = _build_windows(cfg)
    server: DanmakuServer | None = None
    if not args.demo:
        server = DanmakuServer(cfg.socket, lambda d: [w.feed(d) for w in windows])

        status_check = QTimer()
        status_check.setInterval(1000)

        def _update_status() -> None:
            text = "" if server.connected() else "dmnotifier 离线,连接中…"
            for w in windows:
                w.set_status(text)

        status_check.timeout.connect(_update_status)
        status_check.start()

    async def _run() -> None:
        if server is not None:
            await server.start()
        if args.demo:
            async def _demo_loop() -> None:
                for i in range(60):
                    for w in windows:
                        w.feed(_demo_danmaku(i % 4))
                    await asyncio.sleep(0.4)

            asyncio.create_task(_demo_loop())
        loop.add_signal_handler(signal.SIGINT, loop.stop)

    async def _stop() -> None:
        if server is not None:
            await server.stop()

    loop.create_task(_run())
    for w in windows:
        w.resize(cfg.width, 400)
        w.move(cfg.position[0], cfg.position[1])  # X11 回退下生效;layer-shell 下被合成器重定位,精确锚点属后续微调
        w.show()
    try:
        loop.run_forever()
    finally:
        loop.run_until_complete(_stop())


if __name__ == "__main__":
    entry_point()
```

`--demo` 时 `server` 为 None,`_run` 只装信号处理。demo 消息流通过验收辅助脚本 `overlay/scripts/demo_client.py` 注入(它是连接 socket 的假客户端,不修改 main.py):

```python
#!/usr/bin/env python3
"""验收辅助:作为假 dmnotifier 客户端,往 overlay socket 写 demo 弹幕。"""

import asyncio
import json
import os
import sys

from bilidm_overlay.main import _demo_danmaku


async def main() -> None:
    sock = os.environ.get("XDG_RUNTIME_DIR", "/tmp") + "/bilidm-danmaku.sock"
    reader, writer = await asyncio.open_unix_connection(sock)
    for i in range(30):
        d = _demo_danmaku(i % 4)
        payload = {"time": "2026-08-21T20:00:00+08:00", "platform": d.platform, "rid": d.rid,
                   "type": d.type, "name": d.name}
        if d.content:
            payload["content"] = d.content
        if d.item:
            payload["item"] = d.item
        if d.price is not None:
            payload["price"] = d.price
        writer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await writer.drain()
        await asyncio.sleep(0.4)
    writer.close()
    await writer.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
```

(脚本需在 overlay 项目 venv 里跑:`uv run --project "$ROOT" python scripts/demo_client.py`。)

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_main_smoke.py -v`
Expected: 2 passed(如 win.row_count 断言卡壳,先给 `_tick` 里补 `self._wall_widget.update_wall(...)` 后再跑)

- [ ] **Step 5: 创建验收辅助脚本并手工验收(真桌面,非 offscreen)**

先创建 `overlay/scripts/demo_client.py`(内容见上文代码块,末尾 `uv run --project "$ROOT"` 可运行),然后:

Run(终端 A):
```bash
uv run bilidm-overlay --demo
```
Expected: 角落出现半透明窗,弹幕/礼物/SC/订阅四种样式滚动出现;托盘右键可打开「设置…」对话框(改字号/透明度/行数立即生效)、「切换点击穿透」可切换;`Ctrl+C` 干净退出。

Run(终端 B —— socket 链路验收:真 overlay + 假客户端走完整协议):
```bash
uv run bilidm-overlay --no-tray &
sleep 2
uv run python scripts/demo_client.py
```
Expected: 悬浮窗内出现 demo_client 写入的弹幕;随后 `kill %1`,确认 socket 文件被清理:

```bash
ls -la $XDG_RUNTIME_DIR/bilidm-danmaku.sock   # 应不存在
```

- [ ] **Step 6: Commit**

```bash
git add src/bilidm_overlay/window.py src/bilidm_overlay/settings.py src/bilidm_overlay/main.py scripts/demo_client.py tests/test_main_smoke.py
git commit -m "feat: 悬浮窗平台装配 + 主入口(CLI/托盘/演示流)"
```

---

### Task 9: dmnotifier float 插件(Go)

**Files:**
- Create: `dmnotifier/plugins/consumers/float/float.go`, `dmnotifier/plugins/consumers/float/queue.go`, `dmnotifier/plugins/consumers/float/float_test.go`
- Modify: `dmnotifier/cmd/dmnotifier/main.go`(import 区加一行)

**Interfaces:**
- Consumes:`plugin.ConsumerPlugin`(`internal/plugin/interface.go`)、`models.Message`(`pkg/models/message.go`);注册方式 = `plugin.Register("float", New, plugin.PluginInfo{...})`
- Produces:
  - `func New() plugin.Plugin`
  - `type msgQueue`(queue.go):`newMsgQueue(cap int) *msgQueue`、`Push(m *models.Message) bool`(满→丢最旧,返回 true;nil m 返回 false)、`Pop() (*models.Message, bool)`、`Len() int`
  - `func marshalLine(m *models.Message) []byte`(按协议输出 JSON line;时间 `time.Now().Format(time.RFC3339)`;`type` 小写)
  - `func (c *FloatConsumer) Consume(ctx, msg) error`:chat→普通队列,gift/superchat/subscribe→优先队列
  - 连接器:`Start` 起 goroutine:每 2s 尝试 `net.Dial("unix", socket)`(经注入的 `dial func(network, addr string) (net.Conn, error)` 便于测试);连接后启动 writer 循环,优先队列先排空,写失败即断线重连

- [ ] **Step 1: 写失败测试(queue 与序列化)**

Create `dmnotifier/plugins/consumers/float/float_test.go`:

```go
package float

import (
	"encoding/json"
	"testing"

	"github.com/xifan2333/dmnotifier/pkg/models"
)

func chat(name, content string) *models.Message {
	return &models.Message{
		RID:      "689422",
		Platform: "bilibili",
		Type:     models.TypeChat,
		Data:     &models.ChatData{Name: name, Content: content},
	}
}

func TestQueueDropOldestWhenFull(t *testing.T) {
	q := newMsgQueue(3)
	for i := 0; i < 5; i++ {
		q.Push(chat("u", string(rune('0'+i))))
	}
	// 只剩最后 3 条
	got := q.Pop()
	if got == nil {
		t.Fatal("expected message")
	}
	if got.Data.(*models.ChatData).Content != "2" {
		t.Fatalf("expected oldest dropped, got %v", got.Data.(*models.ChatData).Content)
	}
	if q.Len() != 2 {
		t.Fatalf("expected len 2, got %d", q.Len())
	}
}

func TestQueueNilRejected(t *testing.T) {
	q := newMsgQueue(2)
	if q.Push(nil) {
		t.Fatal("nil must be rejected")
	}
}

func TestMarshalLineChat(t *testing.T) {
	line := marshalLine(chat("Alice", "你好"))
	var m map[string]any
	if err := json.Unmarshal(line, &m); err != nil {
		t.Fatal(err)
	}
	if m["type"] != "chat" || m["name"] != "Alice" || m["content"] != "你好" || m["platform"] != "bilibili" || m["rid"] != "689422" {
		t.Fatalf("bad chat line: %s", line)
	}
}

func TestMarshalLineGift(t *testing.T) {
	m := &models.Message{RID: "689422", Platform: "bilibili", Type: models.TypeGift,
		Data: &models.GiftData{Name: "Bob", Item: "辣条", Num: 20, Price: 0.1}}
	line := marshalLine(m)
	var out map[string]any
	if err := json.Unmarshal(line, &out); err != nil {
		t.Fatal(err)
	}
	if out["type"] != "gift" || out["item"] != "辣条" || out["num"] != float64(20) || out["price"] != 0.1 {
		t.Fatalf("bad gift line: %s", line)
	}
}
```

- [ ] **Step 2: 运行确认失败**

Run(在 `dmnotifier/` 目录):
```bash
go test ./plugins/consumers/float/... -v
```
Expected: 编译失败(`plugins/consumers/float` 目录及其中的类型不存在)

- [ ] **Step 3: 实现 queue.go 与 float.go**

Create `dmnotifier/plugins/consumers/float/queue.go`:

```go
package float

import (
	"sync"

	"github.com/xifan2333/dmnotifier/pkg/models"
)

// msgQueue 有界 FIFO,满了丢最旧;由 float 插件用于弹幕入队。
type msgQueue struct {
	mu  sync.Mutex
	buf []*models.Message
	cap int
}

func newMsgQueue(capacity int) *msgQueue {
	return &msgQueue{cap: capacity}
}

func (q *msgQueue) Push(m *models.Message) bool {
	if m == nil {
		return false
	}
	q.mu.Lock()
	defer q.mu.Unlock()
	if len(q.buf) >= q.cap {
		q.buf = q.buf[1:]
	}
	q.buf = append(q.buf, m)
	return true
}

func (q *msgQueue) Pop() (*models.Message, bool) {
	q.mu.Lock()
	defer q.mu.Unlock()
	if len(q.buf) == 0 {
		return nil, false
	}
	m := q.buf[0]
	q.buf = q.buf[1:]
	return m, true
}

func (q *msgQueue) Len() int {
	q.mu.Lock()
	defer q.mu.Unlock()
	return len(q.buf)
}
```

Create `dmnotifier/plugins/consumers/float/float.go`:

```go
package float

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"os"
	"time"

	"github.com/xifan2333/dmnotifier/internal/plugin"
	"github.com/xifan2333/dmnotifier/pkg/models"
)

const (
	defaultQueueSize = 500
	defaultPriority  = 50
	reconnectEvery   = 2 * time.Second
)

var configTemplate = []plugin.ConfigField{
	{Name: "socket", Type: plugin.FieldTypeString, Default: defaultSocket(), Desc: "Bilidm Overlay 的 Unix socket 路径"},
	{Name: "queue_size", Type: plugin.FieldTypeNumber, Default: float64(defaultQueueSize), Desc: "chat 队列上限"},
	{Name: "priority_size", Type: plugin.FieldTypeNumber, Default: float64(defaultPriority), Desc: "礼物/SC/订阅队列上限"},
}

func defaultSocket() string {
	if dir := os.Getenv("XDG_RUNTIME_DIR"); dir != "" {
		return dir + "/bilidm-danmaku.sock"
	}
	return "/tmp/bilidm-danmaku.sock"
}

// Consumer 将弹幕 JSON lines 推送到 overlay socket。
type Consumer struct {
	*plugin.BasePlugin

	socket   string
	normal   *msgQueue
	priority *msgQueue

	dial func(network, addr string) (net.Conn, error)
	stop chan struct{}
}

func New() plugin.Plugin {
	return &Consumer{BasePlugin: plugin.NewBasePlugin("float", plugin.TypeConsumer)}
}

func (c *Consumer) ConfigTemplate() []plugin.ConfigField {
	return configTemplate
}

func (c *Consumer) Init(ctx context.Context, config map[string]interface{}) error {
	if err := c.BasePlugin.Init(ctx, config); err != nil {
		return err
	}
	qSize := defaultQueueSize
	if v, ok := config["queue_size"].(float64); ok && v > 0 {
		qSize = int(v)
	}
	pSize := defaultPriority
	if v, ok := config["priority_size"].(float64); ok && v > 0 {
		pSize = int(v)
	}
	c.socket = defaultSocket()
	if v, ok := config["socket"].(string); ok && v != "" {
		c.socket = v
	}
	c.normal = newMsgQueue(qSize)
	c.priority = newMsgQueue(pSize)
	c.dial = net.Dial
	c.stop = make(chan struct{})
	return nil
}

func (c *Consumer) Start(ctx context.Context) error {
	go c.runLoop(ctx)
	return nil
}

func (c *Consumer) Stop(ctx context.Context) error {
	close(c.stop)
	return nil
}

// Consume 协议:chat→普通队列,gift/superchat/subscribe→优先队列。
func (c *Consumer) Consume(ctx context.Context, msg *models.Message) error {
	switch msg.Type {
	case models.TypeGift, models.TypeSuperChat, models.TypeSubscribe:
		c.priority.Push(msg)
	default:
		c.normal.Push(msg)
	}
	return nil
}

// marshalLine 序列化为协议 JSON line(输出层加 \n;type 必须小写,与协议一致)。
func marshalLine(m *models.Message) []byte {
	w := map[string]any{
		"time":     time.Now().Format(time.RFC3339),
		"platform": m.Platform,
		"rid":      m.RID,
		"type":     strings.ToLower(string(m.Type)),
	}
	switch d := m.Data.(type) {
	case *models.ChatData:
		w["name"] = d.Name
		w["content"] = d.Content
	case *models.GiftData:
		w["name"] = d.Name
		w["item"] = d.Item
		w["num"] = d.Num
		w["price"] = d.Price
	case *models.SubscribeData:
		w["name"] = d.Name
		w["item"] = d.Item
		w["num"] = d.Num
		w["price"] = d.Price
	case *models.SuperChatData:
		w["name"] = d.Name
		w["content"] = d.Content
		w["price"] = d.Price
	}
	b, _ := json.Marshal(w)
	return b
}

func (c *Consumer) runLoop(ctx context.Context) {
	for {
		conn, err := c.dial("unix", c.socket)
		if err != nil {
			log.Printf("float: %v, retry in %s", err, reconnectEvery)
			select {
			case <-ctx.Done():
				return
			case <-c.stop:
				return
			case <-time.After(reconnectEvery):
			}
			continue
		}
		c.drain(ctx, conn)
		select {
		case <-ctx.Done():
			return
		default:
		}
	}
}

func (c *Consumer) drain(ctx context.Context, conn net.Conn) {
	writer := bufio.NewWriter(conn)
	defer conn.Close()
	conn.SetWriteDeadline(time.Now().Add(5 * time.Second))
	for {
		// 优先队列先排空,再排普通
		if m, ok := c.priority.Pop(); ok {
			if err := c.write(writer, m); err != nil {
				return
			}
			continue
		}
		if m, ok := c.normal.Pop(); ok {
			if err := c.write(writer, m); err != nil {
				return
			}
			continue
		}
		select {
		case <-ctx.Done():
			return
		case <-c.stop:
			return
		case <-time.After(200 * time.Millisecond):
		}
		conn.SetWriteDeadline(time.Now().Add(5 * time.Second))
	}
}

func (c *Consumer) write(writer *bufio.Writer, m *models.Message) error {
	if _, err := writer.Write(marshalLine(m)); err != nil {
		return fmt.Errorf("float: write: %w", err)
	}
	if err := writer.WriteByte('\n'); err != nil {
		return fmt.Errorf("float: write newline: %w", err)
	}
	if err := writer.Flush(); err != nil {
		return fmt.Errorf("float: flush: %w", err)
	}
	return nil
}

func init() {
	plugin.Register("float", New, plugin.PluginInfo{
		Name:           "float",
		Type:           plugin.TypeConsumer,
		ConfigTemplate: configTemplate,
	})
}
```

(常量确认:`pkg/models/types.go` 中为 `TypeChat`/`TypeGift`/`TypeLike`/`TypeEnterRoom`/`TypeSubscribe`/`TypeSuperChat`/`TypeEndLive`,与上面代码一致;`platform` 字段为 `models.Platform` 命名类型,`json.Marshal` 输出字符串,无需转换。)

- [ ] **Step 4: 运行确认通过**

Run(在 `dmnotifier/` 目录):
```bash
go test -race ./plugins/consumers/float/... -v
```
Expected: 4 passed

- [ ] **Step 5: 注册插件**

Modify `dmnotifier/cmd/dmnotifier/main.go`:在 import 区 `"github.com/xifan2333/dmnotifier/plugins/consumers/webview"`(第 19 行)后加:

```go
_ "github.com/xifan2333/dmnotifier/plugins/consumers/float"
```

Run:
```bash
go build -o dmnotifier ./cmd/dmnotifier
go vet ./...
```
Expected: 编译成功,`dmnotifier` 二进制生成。

- [ ] **Step 6: 提交 dmnotifier 侧改动**

```bash
git add plugins/consumers/float/ cmd/dmnotifier/main.go
git commit -m "feat: 新增 float consumer 插件,把弹幕推送到 overlay Unix socket"
```

---

### Task 10: 启动脚本 + 集成冒烟

**Files:**
- Create: `overlay/scripts/start.sh`, `overlay/scripts/stop.sh`, `overlay/README.md`(补全)

**Interfaces:**
- Consumes:dmnotifier CLI(`start`/`stop`/`list`)、`bilidm-overlay` 入口、UniBarrage 端口 7777
- Produces:`start.sh [--room bilibili:689422[:cookie]]...`(幂等)、`stop.sh [--room ...]...`

- [ ] **Step 1: 写 start.sh**

Create `overlay/scripts/start.sh`:

```bash
#!/usr/bin/env bash
# 一键拉起:检查 UniBarrage → dmnotifier start → overlay。
# 用法: scripts/start.sh [--room bilibili:689422[:cookie]]...
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# 优先用仓库内构建的 dmnotifier 二进制;否则找 PATH 里的
DMNOTIFIER_BIN="${DMNOTIFIER_BIN:-}"
if [[ -z "$DMNOTIFIER_BIN" ]]; then
  if [[ -x "$ROOT/../dmnotifier/dmnotifier" ]]; then
    DMNOTIFIER_BIN="$ROOT/../dmnotifier/dmnotifier"
  else
    DMNOTIFIER_BIN="$(command -v dmnotifier || echo dmnotifier)"
  fi
fi
ROOM_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --room) ROOM_ARGS+=("$2"); shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

if ! ss -tln 2>/dev/null | grep -q ':7777 '; then
  echo "UniBarrage 未监听 127.0.0.1:7777,请先启动它(见 UniBarrage 仓库 readme)。" >&2
  exit 1
fi

for room in "${ROOM_ARGS[@]}"; do
  "$DMNOTIFIER_BIN" start "$room" || true   # 已订阅时跳过
  echo "已请求订阅 $room"
done

# 组装 --room 参数,透传给 overlay(房间分组/标签由 overlay 配置决定)
OVERLAY_ARGS=()
for room in "${ROOM_ARGS[@]}"; do
  OVERLAY_ARGS+=(--room "$room")
done

uv run --project "$ROOT" bilidm-overlay "${OVERLAY_ARGS[@]}" &
OVERLAY_PID=$!
echo "overlay pid: $OVERLAY_PID"
wait "$OVERLAY_PID"
```

- [ ] **Step 2: 写 stop.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOMS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --room) ROOMS+=("$2"); shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done
for room in "${ROOMS[@]}"; do
  dmnotifier stop "$room" || true
done
pkill -f "bilidm-overlay" || true
```

```bash
chmod +x scripts/start.sh scripts/stop.sh
```

- [ ] **Step 3: README 补全**

填写 `README.md`:功能简介、依赖(Arch:pacman 包+uv)、`scripts/start.sh --room bilibili:689422` 用法、niri keybind 示例:

```
binds = { Mod+G = spawn "bash" "-c" "/home/lumorian/Projects/bili-dm/overlay/scripts/start.sh --room bilibili:689422" }
```

- [ ] **Step 4: 集成冒烟(真实链路)**

Run:
```bash
cd /home/lumorian/Projects/bili-dm && \
  ./dmnotifier/dmnotifier list   # 确认可访问(UniBarrage 已起)
./overlay/scripts/start.sh --room bilibili:689422
```
Expected:悬浮窗出现,收到真实房间的弹幕滚动;鼠标可透过窗口点选下层元素;`dmnotifier list` 列出 `bilibili	689422`。

按 spec 第 10 节验收清单逐项打勾:点击穿透、Chat/礼物/SC/订阅样式、EnterRoom/Like 不出现、`kill` overlay 后 `dmnotifier list` 正常、重开 overlay 自动恢复、`go test ./...` 与 `uv run pytest --cov` 通过、覆盖率 ≥ 80%。

- [ ] **Step 5: Commit**

```bash
git add scripts/ README.md
git commit -m "feat: 一键启动/停止脚本与 README(含 niri keybind 示例)"
```

---

## 附录:验证命令汇总

```bash
# overlay 侧
cd /home/lumorian/Projects/bili-dm/overlay
uv run pytest --cov=bilidm_overlay --cov-report=term-missing   # 纯逻辑 ≥ 80%
uv run bilidm-overlay --demo                                   # 视觉效果

# dmnotifier 侧
cd /home/lumorian/Projects/bili-dm/dmnotifier
go test -race ./...                                            # 全部测试
go build -o dmnotifier ./cmd/dmnotifier
```
