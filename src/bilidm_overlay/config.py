"""XDG 配置加载:yaml + 环境变量展开 + CLI 合并。"""

from __future__ import annotations

import argparse
import dataclasses
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .api import default_api_address, default_api_token

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
    height: int = 400
    max_rows: int = 80
    font_family: str = "Noto Sans CJK SC"
    font_size: int = 12  # 官方聊天列表基准字号 12px
    opacity: float = 0.85
    theme: str = "dark"  # dark | light:官方 bili-theme 的 --bg2/--text2 两套令牌
    click_through: bool = True
    hide_when_idle_seconds: int = 0
    no_tray: bool = False
    # 直播间在线人数(右上角徽标):开播状态 + 当前在线用户,来自 B 站公开接口。
    # 关掉后完全不发网络请求;刷新间隔只影响请求频率,不影响弹幕实时性。
    show_online: bool = True
    online_refresh_seconds: int = 30
    # 发弹幕:卡片底部输入条(官方弹幕姬同款)。cookie 是发送用的登录态
    # (需含 SESSDATA + bili_jct),留空则沿用 --room 里带的 cookie 或
    # dmnotifier history 中该房间的 cookie。
    send_enabled: bool = True
    send_cookie: str = ""
    # UniBarrage 连接(房间管理对话框用;默认与 dmnotifier 的 server 段一致)
    api_address: str = field(default_factory=default_api_address)
    api_token: str = field(default_factory=default_api_token)


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
        if k in ("socket", "send_cookie") and isinstance(v, str):
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
    if getattr(args, "no_send", None):
        cfg.send_enabled = False
    if getattr(args, "send_cookie", None):
        cfg.send_cookie = args.send_cookie
    if getattr(args, "theme", None):
        cfg.theme = args.theme
    return cfg


def save(cfg: Config, path: Path | None = None) -> None:
    """把当前配置写回 yaml(位置/尺寸等运行时留存)。"""
    p = path or Path(os.path.expanduser("~/.config/bilidm-overlay/config.yaml"))
    p.parent.mkdir(parents=True, exist_ok=True)
    data = dataclasses.asdict(cfg)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
