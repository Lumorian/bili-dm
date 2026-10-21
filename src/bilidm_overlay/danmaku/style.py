"""消息类型 → 官方行内文案(纯逻辑,无 Qt 依赖)。

官方 `chat-history-panel` 每种消息的行内文案:

| 类型 | 行内结构 |
|------|----------|
| chat | `[勋章][昵称 : ][内容]` |
| gift | `[昵称][赠送][礼物名][x20][5连击]`,礼物名/数量/连击统一 `var(--pay_yellow)` |
| superchat | 卡片:头像 + 昵称 + 金额(右上)+ 正文 |
| subscribe | `[昵称][开通了][舰长]` |
| 其他(like/enterroom/…) | 灰色系统行 |

昵称后的分隔符官方是半角冒号加空格 `" : "`(`t.userInfo.username+(6!==t.dmType?" : ":" ")`)。
"""

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

# 行内类型:决定间距/卡片/配色分支
KIND_CHAT = "chat"
KIND_GIFT = "gift"
KIND_SUPERCHAT = "superchat"
KIND_SUBSCRIBE = "subscribe"
KIND_SYSTEM = "system"

# 官方昵称后的分隔符与礼物动作词(.gift-item .action 默认「赠送」)
NAME_SEPARATOR = " : "
GIFT_ACTION = "赠送"
SUBSCRIBE_ACTION = "开通了"


@dataclass(frozen=True, slots=True)
class StyleSpec:
    kind: str
    name_color: str  # 昵称色;空串表示用主题默认
    content_color: str  # 正文色;空串表示用主题默认


def kind_for(d: Danmaku) -> str:
    if d.type == KIND_GIFT:
        return KIND_GIFT
    if d.type == KIND_SUPERCHAT:
        return KIND_SUPERCHAT
    if d.type == KIND_SUBSCRIBE:
        return KIND_SUBSCRIBE
    if d.type == KIND_CHAT:
        return KIND_CHAT
    return KIND_SYSTEM


def style_for(d: Danmaku) -> StyleSpec:
    """返回配色分支;具体色值由主题(theme.py)填充,空串=跟随主题。"""
    kind = kind_for(d)
    if kind == KIND_CHAT:
        return StyleSpec(kind, d.name_color, "")
    if kind == KIND_GIFT:
        return StyleSpec(kind, d.name_color, "")
    if kind == KIND_SUPERCHAT:
        return StyleSpec(kind, d.name_color, d.price_color)
    if kind == KIND_SUBSCRIBE:
        return StyleSpec(kind, d.name_color, "")
    return StyleSpec(kind, "", "")


def gift_num_text(d: Danmaku) -> str:
    """礼物数量:`x20`(官方 `gift-num` 只在 num>1 时出现)。"""
    return f"x{d.num}" if d.num > 1 else ""


def gift_item_text(d: Danmaku) -> str:
    return d.item or ""


def subscribe_item_text(d: Danmaku) -> str:
    return d.item or ""


def system_text(d: Danmaku) -> str:
    """系统行文案(`interact-name` + 描述),对齐官方 `appendInteract` 文案。"""
    if d.type == "like":
        return "点赞了"
    if d.type == "enterroom":
        return "进入直播间"
    if d.type == "endlive":
        return "直播已结束"
    if d.type == "superchat_delete":
        return "醒目留言已删除"
    return d.content or ""
