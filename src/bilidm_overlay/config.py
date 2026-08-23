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
    height: int = 400
    max_rows: int = 80
    ttl_seconds: float = 30.0
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
