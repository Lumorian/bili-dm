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
