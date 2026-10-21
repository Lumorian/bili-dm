from datetime import datetime

import pytest

from bilidm_overlay.danmaku.model import parse_message


def test_parses_chat_line():
    line = '{"time":"2026-08-21T20:00:00+08:00","platform":"bilibili","rid":"689422","type":"chat","name":"Alice","content":"你好"}'
    d = parse_message(line)
    assert d.type == "chat"
    assert d.name == "Alice"
    assert d.content == "你好"
    assert d.platform == "bilibili"
    assert d.rid == "689422"
    assert d.time == datetime(2026, 8, 21, 12, 0, 0, tzinfo=__import__("datetime").timezone.utc)
    assert d.item is None


def test_parses_gift_line():
    line = '{"time":"2026-08-21T20:00:00+08:00","platform":"bilibili","rid":"689422","type":"gift","name":"Bob","item":"辣条","num":20,"price":0.1}'
    d = parse_message(line)
    assert d.type == "gift"
    assert d.item == "辣条"
    assert d.num == 20
    assert d.price == 0.1


def test_parses_superchat_line():
    line = '{"time":"2026-08-21T20:00:00+08:00","platform":"bilibili","rid":"689422","type":"superchat","name":"Carol","content":"加油!","price":30}'
    d = parse_message(line)
    assert d.type == "superchat"
    assert d.price == 30


def test_parses_subscribe_line():
    line = '{"time":"2026-08-21T20:00:00+08:00","platform":"bilibili","rid":"689422","type":"subscribe","name":"Dave","item":"大航海","num":1}'
    d = parse_message(line)
    assert d.type == "subscribe"
    assert d.item == "大航海"


def test_normalizes_unknown_type_to_lowercase():
    d = parse_message('{"type":"EnterRoom","name":"Eve"}')
    assert d.type == "enterroom"
    assert d.name == "Eve"


def test_missing_time_becomes_none():
    d = parse_message('{"type":"chat","name":"F"}')
    assert d.time is None
    assert d.content == ""


def test_bad_json_raises_value_error():
    with pytest.raises(ValueError):
        parse_message("not json")


def test_parses_avatar_field():
    d = parse_message('{"type":"chat","name":"A","avatar":"https://i0.hdslb.com/x.png"}')
    assert d.avatar == "https://i0.hdslb.com/x.png"


def test_missing_avatar_is_empty():
    d = parse_message('{"type":"chat","name":"A"}')
    assert d.avatar == ""


def test_parses_medal_and_guard_fields():
    line = (
        '{"type":"chat","name":"A","content":"hi","platform":"bilibili",'
        '"guard_level":3,"user_level":42,"name_color":"#00D1F1",'
        '"medal":{"name":"酷萨","level":33,"color_start":"#638FFE",'
        '"color_end":"#5B8AF5","color_border":"#638FFE","color_text":"#FFFFFF",'
        '"guard_level":3}}'
    )
    d = parse_message(line)
    assert d.guard_level == 3
    assert d.user_level == 42
    assert d.name_color == "#00D1F1"
    assert d.medal is not None
    assert d.medal.name == "酷萨"
    assert d.medal.level == 33
    assert d.medal.color_start == "#638FFE"
    assert d.medal.guard_level == 3


def test_unworn_medal_becomes_none():
    d = parse_message('{"type":"chat","medal":{"name":"酷萨","level":0}}')
    assert d.medal is None
    d2 = parse_message('{"type":"chat","medal":{}}')
    assert d2.medal is None


def test_guard_level_falls_back_to_medal():
    d = parse_message('{"type":"chat","medal":{"name":"酷萨","level":9,"guard_level":2}}')
    assert d.guard_level == 2


def test_numeric_fields_are_lenient():
    d = parse_message('{"type":"chat","guard_level":"3","user_level":"17"}')
    assert d.guard_level == 3
    assert d.user_level == 17
    bad = parse_message('{"type":"chat","guard_level":"x"}')
    assert bad.guard_level == 0


def test_parses_superchat_colors():
    d = parse_message(
        '{"type":"superchat","price":30,"bg_color_start":"#F2C55C",'
        '"bg_color_end":"#E9A100","price_color":"#FFFFFF"}'
    )
    assert d.bg_color_start == "#F2C55C"
    assert d.bg_color_end == "#E9A100"
    assert d.price_color == "#FFFFFF"
