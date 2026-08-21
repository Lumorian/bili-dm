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
