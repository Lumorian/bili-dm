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
