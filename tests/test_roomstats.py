"""直播间在线人数客户端:用线程内 fake server 验证真实 HTTP 参数与解析。"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from bilidm_overlay.roomstats import (
    BilibiliRoomStatsClient,
    RoomStats,
    RoomStatsError,
    format_count,
)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静默
        pass

    def _send(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        self.server.requests.append((path, query))
        if path.endswith("/getRoomBaseInfo"):
            if self.server.base_fails:
                self._send({"code": -352, "message": "risk control"})
                return
            by_room = {}
            for rid in query.get("room_ids", []):
                if rid == "7777":
                    by_room["545068"] = {
                        "room_id": 545068,
                        "uid": 8739477,
                        "uname": "老实憨厚的笑笑",
                        "title": "德云色 S赛启动",
                        "parent_area_name": "网游",
                        "area_name": "英雄联盟",
                        "live_status": 1,
                        "online": 2_239_173,
                        "attention": 2_873_982,
                        "short_id": 7777,
                    }
                elif rid == "689422":
                    by_room["689422"] = {
                        "room_id": 689422,
                        "uid": 9318551,
                        "uname": "未定义项目",
                        "title": "vibe coding",
                        "parent_area_name": "知识",
                        "area_name": "AI应用·机器人",
                        "live_status": 0,
                        "online": 0,
                        "attention": 1123,
                        "short_id": 0,
                    }
            self._send({"code": 0, "message": "OK", "data": {"by_room_ids": by_room}})
            return
        if path.endswith("/getOnlineGoldRank"):
            if self.server.rank_fails:
                self._send({"code": -500, "message": "rank down"})
                return
            room_id = query.get("roomId", [""])[0]
            self._send(
                {
                    "code": 0,
                    "message": "OK",
                    "data": {"onlineNum": 137646, "onlineNumText": "13万+"}
                    if room_id == "545068"
                    else {"onlineNum": 0, "onlineNumText": "0"},
                }
            )
            return
        self._send({"code": 404, "message": "not found"}, code=404)


@pytest.fixture()
def stats_server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    srv.requests = []
    srv.rank_fails = False
    srv.base_fails = False
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()


def _client(srv):
    return BilibiliRoomStatsClient(live_base=f"http://127.0.0.1:{srv.server_port}")


def test_fetch_short_id_maps_real_room_and_online_count(stats_server):
    stats = _client(stats_server).fetch(["7777", "689422"])
    assert set(stats) == {"bilibili:7777", "bilibili:689422"}

    live = stats["bilibili:7777"]
    assert live.room_id == "545068"
    assert live.uid == "8739477"
    assert live.live is True
    assert live.online == 137646
    assert live.online_text == "13万+"
    assert live.online_label == "在线 13万+"
    assert live.area == "网游 · 英雄联盟"

    offline = stats["bilibili:689422"]
    assert offline.live is False
    assert offline.online is None
    assert offline.status_text == "未开播"
    assert offline.online_label == ""


def test_fetch_batches_room_ids_as_repeated_params(stats_server):
    _client(stats_server).fetch(["7777", "689422"])
    base_calls = [q for p, q in stats_server.requests if p.endswith("/getRoomBaseInfo")]
    assert base_calls
    assert base_calls[0]["room_ids"] == ["7777", "689422"]
    assert base_calls[0]["req_biz"] == ["web_room_componet"]


def test_offline_room_skips_online_rank_request(stats_server):
    _client(stats_server).fetch(["689422"])
    assert not [p for p, _ in stats_server.requests if p.endswith("/getOnlineGoldRank")]


def test_online_rank_failure_falls_back_to_popularity(stats_server):
    stats_server.rank_fails = True
    live = _client(stats_server).fetch(["7777"])["bilibili:7777"]
    assert live.live is True
    assert live.online is None
    assert live.online_text == ""
    assert live.popularity == 2_239_173
    assert live.online_label == "人气 223.9万"


def test_base_info_error_raises(stats_server):
    stats_server.base_fails = True
    client = BilibiliRoomStatsClient(live_base=f"http://127.0.0.1:{stats_server.server_port}")
    with pytest.raises(RoomStatsError) as exc:
        client.fetch(["7777"])
    assert exc.value.code == -352


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0"),
        (9999, "9999"),
        (10000, "1万"),
        (12345, "1.2万"),
        (137646, "13.8万"),
        (100_000_000, "1亿"),
        (123_456_789, "1.2亿"),
    ],
)
def test_format_count(value, expected):
    assert format_count(value) == expected


def test_room_status_text():
    assert RoomStats(live_status=1).status_text == "直播中"
    assert RoomStats(live_status=2).status_text == "轮播中"
    assert RoomStats(live_status=0).status_text == "未开播"
