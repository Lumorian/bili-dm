from bilidm_overlay.danmaku import style as sty
from bilidm_overlay.danmaku.model import Danmaku, MedalInfo


def make(**kw):
    base = {"type": "chat", "name": "Alice", "content": "hi", "platform": "bilibili"}
    base.update(kw)
    return Danmaku(**base)


def test_chat_kind_and_no_forced_name_color():
    spec = sty.style_for(make())
    assert spec.kind == sty.KIND_CHAT
    assert spec.name_color == ""  # 昵称色交给主题/官方 nameColor
    assert spec.content_color == ""


def test_gift_kind_and_custom_name_color():
    spec = sty.style_for(make(type="gift", item="辣条", num=20, name_color="#FFFFFF"))
    assert spec.kind == sty.KIND_GIFT
    assert spec.name_color == "#FFFFFF"


def test_superchat_kind_carries_price_color():
    spec = sty.style_for(make(type="superchat", price=30, price_color="#333333"))
    assert spec.kind == sty.KIND_SUPERCHAT
    assert spec.content_color == "#333333"


def test_subscribe_kind():
    assert sty.style_for(make(type="subscribe", item="舰长")).kind == sty.KIND_SUBSCRIBE


def test_other_types_are_system_rows():
    assert sty.style_for(make(type="enterroom")).kind == sty.KIND_SYSTEM
    assert sty.style_for(make(type="like")).kind == sty.KIND_SYSTEM


def test_gift_num_text_only_when_more_than_one():
    assert sty.gift_num_text(make(type="gift", num=1)) == ""
    assert sty.gift_num_text(make(type="gift", num=20)) == "x20"


def test_system_text_matches_official_wording():
    assert sty.system_text(make(type="enterroom")) == "进入直播间"
    assert sty.system_text(make(type="like")) == "点赞了"


def test_name_separator_is_official():
    assert sty.NAME_SEPARATOR == " : "


def test_kind_for_chat_with_medal_stays_chat():
    medal = MedalInfo(name="酷萨", level=33, guard_level=3)
    assert sty.kind_for(make(medal=medal)) == sty.KIND_CHAT
