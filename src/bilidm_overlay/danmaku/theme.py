"""官方直播间聊天面板(chfe-live-room `chat-history-panel`)配色令牌。

数值取自线上 bili-theme(laputa-css v11.0.1)的 `light.css` / `dark.css`:

| 令牌 | light | dark | 用途 |
|------|-------|------|------|
| `--bg2`(--Ga0) | #F6F7F8 | #101011 | 面板底色 |
| `--text2`(--Ga7) | #61666D | #A2A7AE | 弹幕正文 |
| `--text3`(--Ga5) | #9499A0 | #757A81 | 昵称 |
| `--pay_yellow`(--Ye5) | #FFB027 | #DB8700 | 礼物名/数量/金额 |
| `--brand_pink`(--Pi5) | #FF6699 | #D44E7D | 房管/主播标签 |
| 跨房标签 | #7DABF4 | #7DABF4 | `uni-live-mirror-tag` |

排班代码只引用这里,不在布局里写死色值(改主题只改这个文件)。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Theme:
    name: str
    bg: str  # 面板底色 --bg2
    text: str  # 弹幕正文 --text2
    name_text: str  # 昵称 --text3
    pay_yellow: str  # 礼物/舰队/醒目留言金额 --pay_yellow
    brand_pink: str  # 房管/主播标签 --brand_pink
    card_text: str  # 醒目留言卡片正文(卡片底色是亮黄,深浅主题都用深色字)
    divider: str  # 卡片/面板分隔线(--line_regular --Ga2)


LIGHT = Theme(
    name="light",
    bg="#F6F7F8",
    text="#61666D",
    name_text="#9499A0",
    pay_yellow="#FFB027",
    brand_pink="#FF6699",
    card_text="#333333",  # .card-item-middle-top-right{color:#333}
    divider="#E3E5E7",
)

# 悬浮窗默认深色:叠在直播画面上更接近直播姬客户端观感。
DARK = Theme(
    name="dark",
    bg="#101011",
    text="#A2A7AE",
    name_text="#757A81",
    pay_yellow="#DB8700",
    brand_pink="#D44E7D",
    card_text="#333333",  # SC 卡片底色不随主题变,正文始终深色(官方 #333)
    divider="#2F3134",
)

THEMES: dict[str, Theme] = {LIGHT.name: LIGHT, DARK.name: DARK}


def theme_for(name: str) -> Theme:
    """按配置名取主题;未知名字回退深色。"""
    return THEMES.get(name, DARK)


def panel_rgb(name: str) -> tuple[int, int, int]:
    """主题底色转 RGB 三元组(容器 QSS 的 rgba() 需要分量)。"""
    theme = theme_for(name)
    value = theme.bg.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
