"""弹幕消息模型与 UniBarrage JSON lines 解析。

字段对齐官方 `chat-history-panel` 的行内元素。协议在本项目里扩展了(见
`docs/superpowers/specs/2026-10-21-chat-panel-parity-design.md`):

- `avatar`:用户头像(官方行内不画,本项目按用户要求保留在行首)
- `medal`:粉丝勋章 `{name, level, color_start, color_end, color_border, color_text, guard_level, is_light}`
- `guard_level`:大航海等级(1 总督 / 2 提督 / 3 舰长 / 0 无)
- `user_level`:用户等级(渲染 `user-level-icon` 徽章)
- `name_color`:昵称自定义色(官方 `nameColor`;舰队成员为青色)
- `bg_color_start` / `bg_color_end` / `price_color`:醒目留言卡片配色
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class MedalInfo:
    """粉丝勋章(渲染胶囊用);`level` 为 0 视为未佩戴。"""

    name: str = ""
    level: int = 0
    color_start: str = ""
    color_end: str = ""
    color_border: str = ""
    color_text: str = ""
    guard_level: int = 0
    is_light: bool = True


@dataclass(slots=True)
class Danmaku:
    time: datetime | None = None
    platform: str = ""
    rid: str = ""
    type: str = "unknown"
    name: str = ""
    content: str = ""
    avatar: str = ""
    item: str | None = None
    num: int = 1
    price: float | None = None
    text: str = ""  # 结构化正文(dmnotifier 的 FormattedMessage.text);content 是组装整句
    uid: str = ""
    guard_level: int = 0
    user_level: int = 0
    name_color: str = ""
    medal: MedalInfo | None = None
    bg_color_start: str = ""
    bg_color_end: str = ""
    price_color: str = ""


def _as_int(value, default: int = 0) -> int:
    """宽松整型解析(协议里数字/字符串混用,坏值退回默认)。"""
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _parse_medal(raw) -> MedalInfo | None:
    """解析 `medal` 字段;等级为 0 或没有勋章名时返回 None(未佩戴)。"""
    if not isinstance(raw, dict):
        return None
    level = _as_int(raw.get("level", 0))
    name = str(raw.get("name", "") or "")
    if level <= 0 or not name:
        return None
    is_light = raw.get("is_light", True)
    if isinstance(is_light, str):
        is_light = is_light not in ("0", "false", "False", "")
    return MedalInfo(
        name=name,
        level=level,
        color_start=str(raw.get("color_start", "") or ""),
        color_end=str(raw.get("color_end", "") or ""),
        color_border=str(raw.get("color_border", "") or ""),
        color_text=str(raw.get("color_text", "") or ""),
        guard_level=_as_int(raw.get("guard_level", 0)),
        is_light=bool(is_light),
    )


def parse_message(line: str) -> Danmaku:
    """解析一行 JSON 弹幕;坏输入抛 ValueError。"""
    raw = json.loads(line)
    if not isinstance(raw, dict):
        # 保持对外契约:坏输入一律 ValueError(client.py 只捕获它)
        raise ValueError(f"message must be a JSON object: {line!r}")  # noqa: TRY004
    d = Danmaku(
        platform=str(raw.get("platform", "")),
        rid=str(raw.get("rid", "")),
        type=str(raw.get("type", "unknown")).lower(),
        name=str(raw.get("name", "")),
        content=str(raw.get("content", "")),
        text=str(raw.get("text", "") or ""),
        avatar=str(raw.get("avatar", "")),
        uid=str(raw.get("uid", "")),
        name_color=str(raw.get("name_color", "")),
        bg_color_start=str(raw.get("bg_color_start", "")),
        bg_color_end=str(raw.get("bg_color_end", "")),
        price_color=str(raw.get("price_color", "")),
        medal=_parse_medal(raw.get("medal")),
        guard_level=_as_int(raw.get("guard_level", 0)),
        user_level=_as_int(raw.get("user_level", 0)),
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
    # 未显式给 guard_level 时从勋章兜底(官方两处同源,协议里可能只带一处)
    if d.guard_level == 0 and d.medal is not None:
        d.guard_level = d.medal.guard_level
    # 结构化正文优先:dmnotifier 的 content 是「送出了 20 个 辣条 (2.00 元)」这类整句,
    # 官方面板按 [昵称 赠送 礼物名 xN] 分色渲染,需要未拼接的原词。
    if d.text:
        d.content = d.text
    return d
