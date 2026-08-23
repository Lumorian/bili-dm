from datetime import datetime

import pytest

from bilidm_overlay.danmaku.model import Danmaku, parse_message


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
