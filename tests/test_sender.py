"""发弹幕:纯逻辑(sender)与回显去重(echo)。

网络部分用线程内 fake HTTP server 走真实 urllib 路径(与 test_api.py 同款),
不 mock urllib —— 请求形态(表单字段、csrf、cookie 头)本身就是被测对象。
"""

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from bilidm_overlay.danmaku.echo import EchoTracker
from bilidm_overlay.danmaku.model import Danmaku
from bilidm_overlay.sender import (
    MAX_LEN,
    BilibiliSender,
    SendError,
    SendTarget,
    message_for,
    parse_csrf,
    pick_observed_room,
    resolve_target,
    split_room,
    validate_text,
)

# --- 纯逻辑 ---


def test_split_room_keeps_cookie_colons():
    assert split_room("bilibili:689422") == ("bilibili", "689422", "")
    # cookie 自己带冒号(自定义段),只切两刀
    assert split_room("bilibili:689422:SESSDATA=a%2Cb; bili_jct=x:y") == (
        "bilibili",
        "689422",
        "SESSDATA=a%2Cb; bili_jct=x:y",
    )


def test_parse_csrf_finds_bili_jct():
    assert parse_csrf("SESSDATA=abc; bili_jct=deadbeef; DedeUserID=1") == "deadbeef"
    assert parse_csrf("bili_jct = spaced ") == "spaced"
    assert parse_csrf("SESSDATA=abc") == ""


def test_validate_text_rules():
    assert validate_text("") == "弹幕不能为空"
    assert validate_text("   ") == "弹幕不能为空"
    assert validate_text("啊" * MAX_LEN) is None
    assert "最多" in validate_text("啊" * (MAX_LEN + 1))


def test_message_for_is_actionable():
    assert "未登录" in message_for(-101)
    assert "bili_jct" in message_for(-111)
    # 未知码:把服务端原话透出来,别吞成"未知错误"
    assert message_for(12345, "什么情况") == "什么情况"
    assert "12345" in message_for(12345)


class _Cfg:
    def __init__(self, **kw):
        self.rooms = kw.get("rooms", ["bilibili:689422"])
        self.send_cookie = kw.get("send_cookie", "")


def test_resolve_target_prefers_room_cookie(monkeypatch):
    monkeypatch.setattr(
        "bilidm_overlay.sender.dmnotifier_history_cookie", lambda p, r: "SESSDATA=hist; bili_jct=h"
    )
    target = resolve_target(_Cfg(rooms=["bilibili:1:SESSDATA=room; bili_jct=r"]))
    assert target == SendTarget("bilibili", "1", "SESSDATA=room; bili_jct=r")


def test_resolve_target_falls_back_to_config_cookie(monkeypatch):
    monkeypatch.setattr("bilidm_overlay.sender.dmnotifier_history_cookie", lambda p, r: "")
    target = resolve_target(_Cfg(rooms=["bilibili:1"], send_cookie="SESSDATA=cfg; bili_jct=c"))
    assert target.cookie == "SESSDATA=cfg; bili_jct=c"


def test_resolve_target_falls_back_to_dmnotifier_history(monkeypatch):
    monkeypatch.setattr(
        "bilidm_overlay.sender.dmnotifier_history_cookie",
        lambda p, r: "SESSDATA=hist; bili_jct=h" if (p, r) == ("bilibili", "1") else "",
    )
    assert resolve_target(_Cfg(rooms=["bilibili:1"])).cookie == "SESSDATA=hist; bili_jct=h"


def test_resolve_target_uses_window_room_in_per_room_mode(monkeypatch):
    monkeypatch.setattr("bilidm_overlay.sender.dmnotifier_history_cookie", lambda p, r: "")
    cfg = _Cfg(rooms=["bilibili:1", "bilibili:2"])
    assert resolve_target(cfg, room_filter="bilibili:2").rid == "2"


def test_resolve_target_honours_window_room_not_in_config(monkeypatch):
    """窗口是手动 --room 起的(不在 cfg.rooms 里):仍要发到它,别发错房间。"""
    monkeypatch.setattr("bilidm_overlay.sender.dmnotifier_history_cookie", lambda p, r: "")
    cfg = _Cfg(rooms=[])
    assert resolve_target(cfg, room_filter="bilibili:689422") == SendTarget(
        "bilibili", "689422", ""
    )


def test_resolve_target_uses_observed_room_when_unconfigured(monkeypatch):
    """一条房间都没配,但弹幕在流:发到那个房间。"""
    monkeypatch.setattr("bilidm_overlay.sender.dmnotifier_history_cookie", lambda p, r: "SESSDATA=h; bili_jct=h")
    target = resolve_target(_Cfg(rooms=[]), None, "bilibili:1813444381")
    assert target == SendTarget("bilibili", "1813444381", "SESSDATA=h; bili_jct=h")


def test_resolve_target_config_beats_observed(monkeypatch):
    monkeypatch.setattr("bilidm_overlay.sender.dmnotifier_history_cookie", lambda p, r: "")
    cfg = _Cfg(rooms=["bilibili:689422"])
    assert resolve_target(cfg, None, "bilibili:999").rid == "689422"


def test_resolve_target_falls_back_to_dmnotifier_history_rooms(tmp_path, monkeypatch):
    """刚启动还没收到弹幕:dmnotifier history 说明这台机器在收哪个房间,就发它。"""
    _write_dmnotifier_config(
        tmp_path,
        monkeypatch,
        'history:\n  - platform: douyu\n    rid: "1"\n'
        '  - platform: bilibili\n    rid: "1813444381"\n',
    )
    assert resolve_target(_Cfg(rooms=[])) == SendTarget("bilibili", "1813444381", "")


def test_dmnotifier_history_rooms_reads_config(tmp_path, monkeypatch):
    _write_dmnotifier_config(
        tmp_path,
        monkeypatch,
        'history:\n  - platform: bilibili\n    rid: "1"\n  - platform: douyu\n    rid: "2"\n'
        "  - platform: bilibili\n",
    )
    from bilidm_overlay.sender import dmnotifier_history_rooms

    assert dmnotifier_history_rooms() == ["bilibili:1", "douyu:2"], "缺 rid 的条目要丢掉"


def test_resolve_target_none_without_config_or_observation(monkeypatch):
    monkeypatch.setattr("bilidm_overlay.sender.dmnotifier_history_cookie", lambda p, r: "")
    assert resolve_target(_Cfg(rooms=[]), None, None) is None


def test_pick_observed_room_rules():
    assert pick_observed_room(None, "bilibili:1") == "bilibili:1"
    assert pick_observed_room("bilibili:1", None) == "bilibili:1"
    assert pick_observed_room("bilibili:1", "bilibili:2") == "bilibili:1", "已定 B 站房间不跳"
    assert pick_observed_room("douyu:1", "bilibili:2") == "bilibili:2", "来 B 站的换成它"
    assert pick_observed_room("douyu:1", "douyu:2") == "douyu:1", "其余保留先到的"


def test_resolve_target_prefers_bilibili_in_merged_mode(monkeypatch):
    """发送接口只有 B 站有:合并模式下别挑到别的平台去。"""
    monkeypatch.setattr("bilidm_overlay.sender.dmnotifier_history_cookie", lambda p, r: "")
    cfg = _Cfg(rooms=["douyu:9999", "bilibili:2"])
    assert resolve_target(cfg).platform == "bilibili"


def test_resolve_target_none_without_rooms():
    assert resolve_target(_Cfg(rooms=[])) is None


def _write_dmnotifier_config(tmp_path, monkeypatch, text):
    p = tmp_path / "dmnotifier.yaml"
    p.write_text(text, encoding="utf-8")
    monkeypatch.setattr("bilidm_overlay.sender.dmnotifier_config_path", lambda: str(p))


def test_dmnotifier_history_cookie_reads_config(tmp_path, monkeypatch):
    _write_dmnotifier_config(
        tmp_path,
        monkeypatch,
        'history:\n  - platform: bilibili\n    rid: "1"\n    cookie: SESSDATA=x; bili_jct=y\n',
    )
    from bilidm_overlay.sender import dmnotifier_history_cookie

    assert dmnotifier_history_cookie("bilibili", "1") == "SESSDATA=x; bili_jct=y"
    assert dmnotifier_history_cookie("bilibili", "2") == ""


# --- 回显去重 ---


def _dm(content: str, uid: str = "42") -> Danmaku:
    return Danmaku(type="chat", name="me", content=content, uid=uid)


def test_echo_consumes_matching_push_once():
    clock = {"t": 100.0}
    tracker = EchoTracker(clock=lambda: clock["t"])
    tracker.expect("hello")
    assert tracker.consume(_dm("hello")) is True
    assert tracker.consume(_dm("hello")) is False, "同一条回推只能抵扣一次"
    assert tracker.pending_count() == 0


def test_echo_leaves_other_people_alone():
    clock = {"t": 100.0}
    tracker = EchoTracker(clock=lambda: clock["t"])
    tracker.expect("hello", uid="42")
    assert tracker.consume(_dm("hello", uid="99")) is False, "别人的同一句话不能被吞"


def test_echo_binds_uid_after_send_succeeded():
    clock = {"t": 100.0}
    tracker = EchoTracker(clock=lambda: clock["t"])
    tracker.expect("hello")  # 按下发送时还不知道自己的 uid
    tracker.bind_uid("42")
    assert tracker.consume(_dm("hello", uid="99")) is False
    assert tracker.consume(_dm("hello", uid="42")) is True


def test_echo_expires_so_repeated_text_still_lands():
    clock = {"t": 100.0}
    tracker = EchoTracker(window=8.0, clock=lambda: clock["t"])
    tracker.expect("666")
    clock["t"] = 120.0  # 期望过期:回推压根没来
    assert tracker.pending_count() == 0
    assert tracker.consume(_dm("666")) is False, "过期后同内容的正常弹幕必须照常显示"


def test_echo_cancel_on_failure():
    clock = {"t": 100.0}
    tracker = EchoTracker(clock=lambda: clock["t"])
    tracker.expect("hello")
    tracker.cancel("hello")
    assert tracker.consume(_dm("hello")) is False


def test_echo_ignores_blank_text():
    tracker = EchoTracker()
    tracker.expect("   ")
    assert tracker.pending_count() == 0


def test_echo_caps_pending():
    tracker = EchoTracker(clock=lambda: 0.0)
    for i in range(20):
        tracker.expect(f"m{i}")
    assert tracker.pending_count() <= 8


# --- 真 HTTP 路径 ---


class _Handler(BaseHTTPRequestHandler):
    # 跨实例累计的请求记录(测试在 fixture 里清空)
    requests: ClassVar[list[dict]] = []

    def log_message(self, *a):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/room/v1/Room/get_info"):
            self._send(200, {"code": 0, "data": {"room_id": 689422}})
        elif self.path == "/x/web-interface/nav":
            self._send(200, {"code": 0, "data": {"isLogin": True, "mid": 42,
                                                "uname": "我", "face": "https://x/a.jpg"}})
        else:
            self._send(404, {"code": 404, "message": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode()
        form = {
            k: urllib.parse.unquote(v)
            for k, v in (part.split("=", 1) for part in raw.split("&") if "=" in part)
        }
        type(self).requests.append({"path": self.path, "form": form,
                                    "cookie": self.headers.get("Cookie", "")})
        self._send(200, {"code": 0, "message": "ok"})


@pytest.fixture(autouse=True)
def _isolate_dmnotifier_history(tmp_path, monkeypatch):
    """房间解析会兜底读 dmnotifier config:默认指到不存在的路径,免得测试依赖本机配置。
    需要真读的那几条用例自己把路径指到 tmp。"""
    monkeypatch.setattr(
        "bilidm_overlay.sender.dmnotifier_config_path", lambda: str(tmp_path / "absent.yaml")
    )


@pytest.fixture()
def live_server():
    _Handler.requests = []
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _sender(url: str) -> BilibiliSender:
    return BilibiliSender(live_base=url, api_base=url, timeout=3.0)


def test_send_posts_official_fields(live_server):
    target = SendTarget("bilibili", "689422", "SESSDATA=s; bili_jct=csrf-token")
    _sender(live_server).send(target, "  你好  ")
    req = _Handler.requests[-1]
    assert req["path"] == "/msg/send"
    form = req["form"]
    assert form["msg"] == "你好", "正文要原样发出(去掉首尾空白)"
    assert form["roomid"] == "689422"
    assert form["csrf"] == "csrf-token" and form["csrf_token"] == "csrf-token"
    assert form["mode"] == "1" and form["color"] == "16777215"
    assert req["cookie"] == "SESSDATA=s; bili_jct=csrf-token", "发弹幕必须带上登录 cookie"


def test_send_resolves_short_room_id(live_server):
    sender = _sender(live_server)
    target = SendTarget("bilibili", "123", "SESSDATA=s; bili_jct=c")
    sender.send(target, "hi")
    assert _Handler.requests[-1]["form"]["roomid"] == "689422", "短号要用真实房间号发送"


def test_send_without_csrf_fails_before_network(live_server):
    with pytest.raises(SendError) as exc:
        _sender(live_server).send(SendTarget("bilibili", "1", "SESSDATA=only"), "hi")
    assert exc.value.code == -111
    assert "bili_jct" in exc.value.message
    assert _Handler.requests == [], "缺 csrf 就别打网络,原因本地就能说清"


def test_send_rejects_blank_and_too_long(live_server):
    sender = _sender(live_server)
    target = SendTarget("bilibili", "1", "SESSDATA=s; bili_jct=c")
    with pytest.raises(SendError):
        sender.send(target, "  ")
    with pytest.raises(SendError):
        sender.send(target, "啊" * (MAX_LEN + 1))
    assert _Handler.requests == []


def test_send_rejects_other_platform(live_server):
    with pytest.raises(SendError) as exc:
        _sender(live_server).send(SendTarget("douyu", "1", "SESSDATA=s; bili_jct=c"), "hi")
    assert "B 站" in exc.value.message


def test_fetch_identity(live_server):
    identity = _sender(live_server).fetch_identity("SESSDATA=s; bili_jct=c")
    assert identity is not None
    assert (identity.uid, identity.name) == ("42", "我")
