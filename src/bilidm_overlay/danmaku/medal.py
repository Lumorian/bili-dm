"""粉丝勋章 / 大航海:官方样式的纯逻辑(无 Qt 依赖,可无头测试)。

对应线上 `bfe-live-room` 的 `chat-history-panel` 行内元素。用 headless Chrome 把线上
CSS 跑起来量出的真实盒子(12px 基准,Arial/微软雅黑):

```
.chat-item.danmaku-item   height 30  = padding 5 + line-box 20 + padding 5
  .fans-medal-item-ctnr   高 16, margin-left 4, margin-right 3
    .fans-medal-item      高 15, radius 8, padding 2 6 2 2
      .fans-medal-label.guard  padding-left 12(留给绝对定位的航海图标)
        .fans-medal-content    宽 24(两个汉字),margin-right 2,视觉缩到 83.33%
      .fans-medal-level       宽 4(1 位数)/ 8(2 位)/ 15(3 位),高 12
  .user-name              line-height 20
  .danmaku-item-right     line-height 20
```

要点:**`transform:scale(.8333)` 只影响视觉,不影响布局** —— 勋章名在排版里仍占
24px(两个汉字),绘制时再缩到 83.33%。航海图标 `left:6px;margin-left:-12px` 是
绝对定位,左缘溢出胶囊 6px、**不计入胶囊宽度**。
"""

from __future__ import annotations

from dataclasses import dataclass

# 大航海等级 → 名称(1 总督 / 2 提督 / 3 舰长,与 blivedm guard_level 一致)
GUARD_LEVEL_NAMES: dict[int, str] = {1: "总督", 2: "提督", 3: "舰长"}

# 基准字号 12px 下的官方像素值(渲染时按 cfg 字号等比缩放)
BASE_FONT_PX = 12.0
PILL_HEIGHT = 15.0
PILL_RADIUS = 8.0
PILL_PAD_RIGHT = 6.0
PILL_PAD_LEFT = 2.0
LABEL_TEXT_GAP = 2.0  # .fans-medal-content{margin-right:2px}
PILL_TEXT_SCALE = 0.8333  # .fans-medal-content{transform:scale(.8333)}(仅视觉)
GUARD_ICON = 20.0  # .medal-deco.medal-guard{width:20px;height:20px}
GUARD_PAD_LEFT = 12.0  # .fans-medal-label.guard{padding-left:12px}
# .medal-deco.medal-guard{position:absolute;left:6px;margin-left:-12px} 相对 .fans-medal-label,
# label 左缘 = 胶囊左缘 + 2px(pill 左内边距),故图标左缘 = 胶囊左缘 + 2 + 6 - 12 = 胶囊左缘 - 4。
GUARD_ICON_OFFSET = PILL_PAD_LEFT + 6.0 - 12.0  # = -4px,图标左缘溢出胶囊 4px
MEDAL_MARGIN_LEFT = 4.0  # .fans-medal-item-ctnr{margin-left:4px}
MEDAL_MARGIN_RIGHT = 3.0  # .fans-medal-item-ctnr{margin-right:3px}
MEDAL_CTNR_HEIGHT = 16.0  # .fans-medal-item-ctnr{height:16px}


def level_slot_width(level: int) -> float:
    """等级数字占位宽:.one-digit-level{4px} / 默认 8px / .three-digits-level{15px}。"""
    if level < 10:
        return 4.0
    if level > 99:
        return 15.0
    return 8.0


def guard_name(guard_level: int) -> str:
    return GUARD_LEVEL_NAMES.get(guard_level, "")


@dataclass(frozen=True, slots=True)
class Medal:
    """一枚粉丝勋章(`fansMedal` 展示所需字段)。"""

    name: str
    level: int
    color_start: str = "#9C9C9C"
    color_end: str = "#9C9C9C"
    color_border: str = "#9C9C9C"
    color_text: str = "#FFFFFF"
    guard_level: int = 0

    @property
    def is_guard(self) -> bool:
        """舰长/提督/总督:左内边距 12px 留给 20px 航海图标。"""
        return self.guard_level > 0

    @property
    def pad_left(self) -> float:
        """胶囊左内边距合计:胶囊自身 2px + 舰长款 label 再让出 12px 图标位。

        官方量值:舰长款 54.02 = 2 + 12 + 24.02(名字) + 2 + 8(等级) + 6;
        普通款 42.02 = 2 + 24.02 + 2 + 8 + 6。
        """
        return PILL_PAD_LEFT + (GUARD_PAD_LEFT if self.is_guard else 0.0)

    def pill_width(self, measure_text) -> float:
        """胶囊总宽(px)= 左内边距 + 勋章名(布局宽度,不缩放) + 2px + 等级槽位 + 6px。

        measure_text 返回**未缩放**的名字宽度(`transform` 只影响绘制)。
        """
        return (
            self.pad_left
            + measure_text(self.name)
            + LABEL_TEXT_GAP
            + level_slot_width(self.level)
            + PILL_PAD_RIGHT
        )


def medal_from(msg_medal) -> Medal | None:
    """把协议里的 `MedalInfo` 转成渲染模型;未佩戴(等级 0 / 无名字)返回 None。"""
    if msg_medal is None or msg_medal.level <= 0 or not msg_medal.name:
        return None
    start = msg_medal.color_start or msg_medal.color_end or msg_medal.color_border or "#9C9C9C"
    return Medal(
        name=msg_medal.name,
        level=msg_medal.level,
        color_start=start,
        color_end=msg_medal.color_end or start,
        color_border=msg_medal.color_border or start,
        color_text=msg_medal.color_text or "#FFFFFF",
        guard_level=msg_medal.guard_level,
    )
