"""直播间实时数据:B 站公开接口里的在线人数与开播状态。

B 站直播页顶部的「人气」并不是在线人数:room/v1/Room/get_info 的 online
是热度值(热门直播间动辄上千万),把它当在线数会差几个数量级。

真正对应「当前直播间在线用户」的是官方高能榜接口
xlive/general-interface/v1/rank/getOnlineGoldRank 返回的 onlineNum
(页面展示用的 onlineNumText 会缩写成 "13万+" / "9999+")。它需要主播 uid
和真实房间号,所以先调一次可批量查询的 getRoomBaseInfo:

1. getRoomBaseInfo → 真实房间号 / 主播 uid / 开播状态 / 标题 / 分区 / 人气 / 粉丝数
2. 对正在直播的房间 → getOnlineGoldRank → onlineNum / onlineNumText

网络是同步 urllib(与 api.py / sender.py 一致),调用方负责放到后台线程里跑。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

logger = logging.getLogger(__name__)

LIVE_BASE = "https://api.live.bilibili.com"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) bilidm-overlay"
REFERER = "https://live.bilibili.com/"
LIVE_STATUS_OFFLINE = 0
LIVE_STATUS_LIVE = 1
LIVE_STATUS_REPLAY = 2


class RoomStatsError(Exception):
    """拉取直播间数据失败;message 可直接写进日志/提示。"""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


@dataclass(frozen=True, slots=True)
class RoomStats:
    """一个直播间的实时快照(只填 B 站公开接口能拿到的字段)。"""

    platform: str = "bilibili"
    rid: str = ""  # 用户配置里的房间号(可能是短号)
    room_id: str = ""  # 真实房间号
    uid: str = ""  # 主播 uid
    uname: str = ""  # 主播昵称
    title: str = ""  # 直播间标题
    area: str = ""  # 「大分区 · 小分区」
    live_status: int = LIVE_STATUS_OFFLINE
    online: int | None = None  # 当前在线用户数;None = 没取到(不是 0)
    online_text: str = ""  # 官方缩写,如 "13万+" / "9999+"
    popularity: int = 0  # 人气值(热度,不是在线人数)
    attention: int = 0  # 粉丝数

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.rid}"

    @property
    def live(self) -> bool:
        return self.live_status == LIVE_STATUS_LIVE

    @property
    def status_text(self) -> str:
        if self.live:
            return "直播中"
        if self.live_status == LIVE_STATUS_REPLAY:
            return "轮播中"
        return "未开播"

    @property
    def online_label(self) -> str:
        """状态后面那一截:有在线数就用在线数,只有人气时才明说「人气」。"""
        if not self.live:
            return ""
        if self.online_text:
            return f"在线 {self.online_text}"
        if self.online is not None:
            return f"在线 {format_count(self.online)}"
        if self.popularity:
            return f"人气 {format_count(self.popularity)}"
        return "在线数未知"


def format_count(value: int | None) -> str:
    """按 B 站习惯缩写数字:9999 / 1.2万 / 13万 / 1.2亿。"""
    try:
        number = max(0, int(value or 0))
    except (TypeError, ValueError):
        return "0"
    if number < 10_000:
        return str(number)
    if number >= 100_000_000:
        text = f"{number / 100_000_000:.1f}"
        return _strip_zero(text) + "亿"
    text = f"{number / 10_000:.1f}"
    return _strip_zero(text) + "万"


def _strip_zero(text: str) -> str:
    return text.removesuffix(".0")


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_int_or_none(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _room_id_of(info: dict) -> str:
    return str(info.get("room_id") or "")


def _match_room(requested: str, by_room_ids: dict[str, dict]) -> tuple[str, dict] | None:
    """把用户给的房间号(可能是短号)对上接口返回的真实房间条目。"""
    if requested in by_room_ids:
        return requested, by_room_ids[requested]
    for real_id, info in by_room_ids.items():
        if str(info.get("short_id") or "") == requested:
            return real_id, info
    return None


class BilibiliRoomStatsClient:
    """同步拉取一批 B 站直播间的状态与在线人数。"""

    def __init__(self, live_base: str = LIVE_BASE, timeout: float = 5.0) -> None:
        self._live = live_base.rstrip("/")
        self._timeout = timeout

    def fetch(self, rids: Sequence[str] | Iterable[str]) -> dict[str, RoomStats]:
        """返回 {"bilibili:<请求时的 rid>": RoomStats};查询不到的房间直接省略。"""
        wanted = _clean_rids(rids)
        if not wanted:
            return {}
        by_room_ids = self._fetch_base_info(wanted)
        out: dict[str, RoomStats] = {}
        seen: set[str] = set()
        for rid in wanted:
            matched = _match_room(rid, by_room_ids)
            if matched is None:
                continue
            real_id, info = matched
            if real_id in seen:
                # 同一个房间既给了短号又给了真实号:只保留第一份,别让标签重复计数
                continue
            seen.add(real_id)
            out[f"bilibili:{rid}"] = self._stats_for(rid, real_id, info)
        return out

    # --- HTTP ---
    def _fetch_base_info(self, rids: Sequence[str]) -> dict[str, dict]:
        # 这个接口的批量参数是重复的 room_ids,逗号拼接会返回 -400(2026-10 实测)
        params = [("room_ids", rid) for rid in rids]
        params.append(("req_biz", "web_room_componet"))
        url = (
            f"{self._live}/xlive/web-room/v1/index/getRoomBaseInfo?{urllib.parse.urlencode(params)}"
        )
        payload = self._get(url)
        data = payload.get("data") or {}
        by = data.get("by_room_ids") or {}
        if not isinstance(by, dict):
            return {}
        return {str(k): v for k, v in by.items() if isinstance(v, dict)}

    def _fetch_online(self, uid: str, room_id: str) -> tuple[int | None, str]:
        url = (
            f"{self._live}/xlive/general-interface/v1/rank/getOnlineGoldRank"
            f"?ruid={urllib.parse.quote(uid)}"
            f"&roomId={urllib.parse.quote(room_id)}&page=1&pageSize=1"
        )
        payload = self._get(url)
        data = payload.get("data") or {}
        online = _as_int_or_none(data.get("onlineNum"))
        text = str(data.get("onlineNumText") or "")
        if online is None and not text:
            raise RoomStatsError(0, "在线人数响应为空")
        return online, text

    def _get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Referer": REFERER})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = _decode(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                payload = _decode(exc.read())
            except ValueError:
                raise RoomStatsError(exc.code, str(exc.reason)) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RoomStatsError(0, f"无法连接 B 站:{reason}") from exc
        except ValueError as exc:
            raise RoomStatsError(0, "B 站返回了无法解析的响应") from exc
        code = _as_int(payload.get("code", 0))
        if code != 0:
            message = str(payload.get("message") or payload.get("msg") or "未知错误")
            raise RoomStatsError(code, message)
        return payload

    def _stats_for(self, rid: str, real_id: str, info: dict) -> RoomStats:
        parent_area = str(info.get("parent_area_name") or "")
        area_name = str(info.get("area_name") or "")
        area = " · ".join(x for x in (parent_area, area_name) if x)
        stats = RoomStats(
            rid=rid,
            room_id=_room_id_of(info) or real_id,
            uid=str(info.get("uid") or ""),
            uname=str(info.get("uname") or ""),
            title=str(info.get("title") or ""),
            area=area,
            live_status=_as_int(info.get("live_status")),
            popularity=_as_int(info.get("online")),
            attention=_as_int(info.get("attention")),
        )
        if not stats.live or not stats.uid:
            return stats
        try:
            online, online_text = self._fetch_online(stats.uid, stats.room_id)
        except RoomStatsError as exc:
            # 在线接口失败不影响开播状态/标题/人气:标签退化成「人气 x」,不要整个消失
            logger.debug("拉取在线人数失败(忽略) room=%s: %s", rid, exc)
            return stats
        return replace(stats, online=online, online_text=online_text)


def _clean_rids(rids: Sequence[str] | Iterable[str]) -> list[str]:
    if isinstance(rids, str):
        rids = [rids]
    out: list[str] = []
    for rid in rids:
        value = str(rid or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _decode(raw: bytes) -> dict:
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    if not isinstance(payload, dict):
        raise ValueError(f"response is not a JSON object: {payload!r}")  # noqa: TRY004
    return payload
