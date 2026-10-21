"""粉丝勋章 / 大航海:官方度量与构造规则(纯逻辑)。"""

from bilidm_overlay.danmaku.medal import (
    GUARD_ICON,
    GUARD_ICON_OFFSET,
    GUARD_PAD_LEFT,
    PILL_HEIGHT,
    PILL_PAD_LEFT,
    PILL_PAD_RIGHT,
    PILL_RADIUS,
    PILL_TEXT_SCALE,
    guard_name,
    level_slot_width,
    medal_from,
)
from bilidm_overlay.danmaku.model import MedalInfo


def test_official_constants():
    assert (PILL_HEIGHT, PILL_RADIUS) == (15.0, 8.0)
    assert (PILL_PAD_LEFT, PILL_PAD_RIGHT) == (2.0, 6.0)
    assert (GUARD_ICON, GUARD_PAD_LEFT) == (20.0, 12.0)
    assert round(PILL_TEXT_SCALE, 4) == 0.8333


def test_guard_names_match_bilibili():
    assert guard_name(1) == "总督"
    assert guard_name(2) == "提督"
    assert guard_name(3) == "舰长"
    assert guard_name(0) == ""


def test_level_slot_width_classes():
    assert level_slot_width(1) == 4.0
    assert level_slot_width(9) == 4.0
    assert level_slot_width(10) == 8.0
    assert level_slot_width(99) == 8.0
    assert level_slot_width(100) == 15.0


def test_medal_from_ignores_unworn():
    assert medal_from(None) is None
    assert medal_from(MedalInfo(name="酷萨", level=0)) is None
    assert medal_from(MedalInfo(name="", level=5)) is None


def test_medal_from_falls_back_to_single_color():
    medal = medal_from(MedalInfo(name="酷萨", level=12, color_start="#638FFE"))
    assert medal is not None
    assert medal.color_end == "#638FFE"
    assert medal.color_border == "#638FFE"
    assert medal.color_text == "#FFFFFF"


def test_pill_width_matches_chrome_measured_boxes():
    """对齐 headless Chrome 量出的官方盒子(12px 基准,Arial/微软雅黑)。"""
    medal = medal_from(MedalInfo(name="酷萨", level=33, guard_level=3))
    assert medal is not None
    # 官方 54.02 = 2(胶囊左内边距) + 12(舰长图标位) + 24.02(名字) + 2 + 8(等级) + 6
    assert round(medal.pill_width(lambda text: 24.02), 2) == 54.02
    plain = medal_from(MedalInfo(name="酷萨", level=33))
    assert plain is not None
    # 官方 42.02 = 2 + 24.02 + 2 + 8 + 6
    assert round(plain.pill_width(lambda text: 24.02), 2) == 42.02


def test_name_width_is_layout_width_not_scaled():
    """transform:scale(.8333) 只影响视觉:排版仍按名字原宽计算。"""
    medal = medal_from(MedalInfo(name="酷萨", level=16))
    assert medal.pill_width(lambda text: 24.0) == 42.0
    assert PILL_TEXT_SCALE == 0.8333


def test_guard_icon_overflows_pill():
    """官方 .medal-deco.medal-guard{left:6px; margin-left:-12px}:图标左缘溢出胶囊 4px。"""
    medal = medal_from(MedalInfo(name="a", level=1, guard_level=3))
    assert medal.is_guard is True
    assert GUARD_ICON_OFFSET == PILL_PAD_LEFT + 6.0 - 12.0
    assert GUARD_ICON_OFFSET == -4.0
    assert medal.pad_left == PILL_PAD_LEFT + GUARD_PAD_LEFT


def test_medal_is_guard_flag():
    assert medal_from(MedalInfo(name="a", level=1, guard_level=3)).is_guard is True
    assert medal_from(MedalInfo(name="a", level=1)).is_guard is False
