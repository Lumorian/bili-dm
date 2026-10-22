"""发弹幕:B 站直播间弹幕发送(官方 `msg/send` 接口)。

官方弹幕姬(直播姬)在弹幕面板底部放了一条发送栏:输入框 + 「发送」,20 字上限,
回车即发。这里照抄这条交互,并把官方没明说的三件事定下来:

1. **cookie 从哪来** —— 发送必须带登录态(SESSDATA + bili_jct),而本项目订阅时
   本来就带着它。取值顺序:`--room bilibili:rid:cookie` 的房间链 →
   `config.yaml` 的 `cookie` → dmnotifier `config.yaml` 里同房间那条 history。
2. **csrf** —— `msg/send` 要求 `csrf`/`csrf_token` 等于 cookie 里的 `bili_jct`;
   只带 SESSDATA 的 cookie 根本发不出去,必须在点发送前就说清楚,而不是让用户对着
   一个 -111 猜。
3. **房间号** —— 用户手里可能是短号,`msg/send` 只认真实房间号,故先 `get_info`
   换一次并缓存。

网络是同步 urllib(与 api.py 一致);调用方负责放到线程里跑,别卡住 30ms 重绘。
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import yaml

logger = logging.getLogger(__name__)

MAX_LEN = 20  # 普通用户弹幕 20 字上限(官方输入框同样卡这个数)
COLOR_WHITE = 16777215  # 官方默认弹幕色(白色)
FONTSIZE_STANDARD = 25  # 官方字号档位里的「标准」
MODE_SCROLL = 1  # 滚动弹幕

LIVE_BASE = "https://api.live.bilibili.com"
API_BASE = "https://api.bilibili.com"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) bilidm-overlay"


class SendError(Exception):
    """发送失败;message 是可以直接显示给用户的中文原因。"""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class SendTarget:
    """一条弹幕要发到哪儿、用谁的登录态。"""

    platform: str
    rid: str
    cookie: str


@dataclass(frozen=True, slots=True)
class Identity:
    """自己的 B 站身份(本地回显昵称/头像、消重都靠它)。"""

    uid: str
    name: str
    avatar: str


# --- 纯逻辑 ---


def split_room(room: str) -> tuple[str, str, str]:
    """`platform:rid[:cookie]` → (platform, rid, cookie)。

    cookie 自身含冒号(SESSDATA 的 `%2C` 是编码过的,但自定义段可能有),所以只切两刀。
    """
    parts = room.split(":", 2)
    platform = parts[0].strip()
    rid = parts[1].strip() if len(parts) > 1 else ""
    cookie = parts[2].strip() if len(parts) > 2 else ""
    return platform, rid, cookie


def parse_csrf(cookie: str) -> str:
    """从 cookie 串里取 `bili_jct`(即 `msg/send` 的 csrf_token)。"""
    for part in cookie.split(";"):
        name, _, value = part.strip().partition("=")
        if name.strip() == "bili_jct":
            return value.strip()
    return ""


def validate_text(text: str) -> str | None:
    """空/超长返回中文原因,可发返回 None。"""
    text = text.strip()
    if not text:
        return "弹幕不能为空"
    if len(text) > MAX_LEN:
        return f"弹幕最多 {MAX_LEN} 字(现在 {len(text)} 字)"
    return None


def dmnotifier_config_path() -> str:
    """dmnotifier 的 config.yaml 路径(单点定义,测试可替换,免得依赖本机配置)。"""
    return os.path.expanduser("~/.config/dmnotifier/config.yaml")


def _dmnotifier_config() -> dict:
    """读 dmnotifier 的 config.yaml;读不到/坏掉的当成空配置(发送侧不该因此报错)。"""
    try:
        with open(dmnotifier_config_path(), encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def dmnotifier_history_cookie(platform: str, rid: str) -> str:
    """dmnotifier 的 history 里,这个房间订阅时用的 cookie。

    用户能收到弹幕就说明这条 cookie 是活的(至少 SESSDATA 活),发送优先复用它,
    省掉"再填一遍 cookie"。
    """
    for entry in _dmnotifier_config().get("history") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("platform", "")) == platform and str(entry.get("rid", "")) == rid:
            return str(entry.get("cookie", "") or "")
    return ""


def dmnotifier_history_rooms() -> list[str]:
    """dmnotifier history 里订阅过的房间(["platform:rid", ...],按出现顺序)。

    比"从弹幕里学到"早一步:刚启动、一条弹幕都还没来时,history 已经说明了这台机器
    在收哪个房间,不必让用户为了发一条弹幕专门去设置里再添一遍。
    """
    rooms: list[str] = []
    for entry in _dmnotifier_config().get("history") or []:
        if not isinstance(entry, dict):
            continue
        platform = str(entry.get("platform", "") or "").strip()
        rid = str(entry.get("rid", "") or "").strip()
        if platform and rid:
            rooms.append(f"{platform}:{rid}")
    return rooms


def resolve_target(
    cfg, room_filter: str | None = None, observed_room: str | None = None
) -> SendTarget | None:
    """挑一个可发送的房间并带回它的 cookie。

    房间来源有三处,优先级从"最确定"排到"最兜底":

    1. `room_filter` —— per-room 模式的窗口就是绑死在这个房间上的,发错房间比发不出去
       更糟;window 传也照发(它可能是手动 --room 起的,不在 cfg.rooms 里)。
    2. `cfg.rooms` —— 用户在设置/命令行里明确配过的;合并模式下优先第一个 B 站房间,
       发送接口只有 B 站有,挑别的平台等于没得发。
    3. `observed_room` —— **从正在流动的弹幕里学到的房间**。这一条是必需的:房间是
       dmnotifier 订阅的,overlay 完全可以在没有任何 `--room`/配置的情况下收弹幕
       (dmnotifier history 里就有),此时"能看不能发"毫无道理 —— 既然弹幕带着
       platform/rid 过来了,那就说明它知道该发到哪。
    """
    chains = [split_room(r) for r in (getattr(cfg, "rooms", None) or []) if r]
    chains = [chains_i for chains_i in chains if chains_i[0] and chains_i[1]]
    chosen: tuple[str, str, str] | None = None
    if room_filter:
        for chain in chains:
            if f"{chain[0]}:{chain[1]}" == room_filter:
                chosen = chain
                break
        else:
            platform, rid, _ = split_room(room_filter)
            if platform and rid:
                chosen = (platform, rid, "")
    if chosen is None:
        for chain in chains:
            if chain[0] == "bilibili":
                chosen = chain
                break
    if chosen is None and chains:
        chosen = chains[0]
    if chosen is None and observed_room:
        platform, rid, _ = split_room(observed_room)
        if platform and rid:
            chosen = (platform, rid, "")
    if chosen is None:
        # 最后兜底:dmnotifier history —— 这台机器在收哪些房间,它自己最清楚。
        # 刚启动还没收到弹幕时,这条让"能看就能发"立刻成立。
        history_chains = [split_room(r) for r in dmnotifier_history_rooms()]
        for chain in history_chains:
            if chain[0] == "bilibili" and chain[1]:
                chosen = chain
                break
        if chosen is None and history_chains:
            chosen = history_chains[0]
    if chosen is None:
        return None
    platform, rid, cookie = chosen
    cookie = (
        cookie
        or str(getattr(cfg, "send_cookie", "") or "")
        or dmnotifier_history_cookie(platform, rid)
    )
    return SendTarget(platform=platform, rid=rid, cookie=cookie)


def pick_observed_room(current: str | None, candidate: str | None) -> str | None:
    """从流动的弹幕里挑一个"发送目标"房间(纯逻辑)。

    合并模式可能同时收多个房间的弹幕,不能让目标跟着最后一条弹幕来回跳:

    - 已经定下 B 站房间就不再改(发送接口只有 B 站有);
    - 当前还是别的平台、来了一条 B 站的 → 换成它;
    - 其余情况保留先到的那个。
    """
    if not candidate:
        return current
    if not current:
        return candidate
    if current.startswith("bilibili:"):
        return current
    if candidate.startswith("bilibili:"):
        return candidate
    return current


# 错误码 → 中文原因。B 站的 message 常常是空的或只写「请求错误」,自己给一句能照着做的。
_FRIENDLY = {
    -101: "账号未登录:cookie 里缺少或过期了 SESSDATA",
    -111: "csrf 校验失败:cookie 里缺少 bili_jct",
    -400: "请求被拒绝(B 站认为参数不对)",
    -403: "没有发弹幕的权限(可能被禁言或等级不足)",
    -412: "请求被拦截(发得太快或触发了风控)",
    -500: "B 站服务异常,稍后再试",
    10030: "弹幕内容不合规",
    1003212: "弹幕发送太频繁,稍等一下",
}


def message_for(code: int, server_message: str = "") -> str:
    """把错误码翻成一句能照着做的中文(服务端原话附在后面兜底)。"""
    friendly = _FRIENDLY.get(code, "")
    if friendly and server_message:
        return f"{friendly}({server_message})"
    if friendly:
        return friendly
    if server_message:
        return server_message
    return f"发送失败(错误码 {code})"


class BilibiliSender:
    """发弹幕 + 取自己的身份。失败一律抛 `SendError`(带中文原因)。"""

    def __init__(
        self,
        live_base: str = LIVE_BASE,
        api_base: str = API_BASE,
        timeout: float = 5.0,
    ) -> None:
        self._live = live_base.rstrip("/")
        self._api = api_base.rstrip("/")
        self._timeout = timeout
        self._room_ids: dict[str, str] = {}

    # --- 发送 ---
    def send(self, target: SendTarget, text: str) -> None:
        text = text.strip()
        problem = validate_text(text)
        if problem:
            raise SendError(0, problem)
        if target.platform != "bilibili":
            raise SendError(0, f"暂只支持向 B 站直播间发送弹幕(当前房间:{target.platform})")
        csrf = parse_csrf(target.cookie)
        if not csrf:
            # 提前拦:否则 B 站只会回一个 -111,用户不知道是 cookie 少了一段
            raise SendError(-111, message_for(-111))
        form = {
            "color": str(COLOR_WHITE),
            "fontsize": str(FONTSIZE_STANDARD),
            "mode": str(MODE_SCROLL),
            "msg": text,
            "rnd": str(int(time.time())),
            "roomid": self.real_room_id(target.rid, target.cookie),
            "csrf": csrf,
            "csrf_token": csrf,
        }
        payload = self._request(f"{self._live}/msg/send", form=form, cookie=target.cookie)
        code = _as_int(payload.get("code", 0))
        if code != 0:
            server_message = str(payload.get("message") or payload.get("msg") or "")
            raise SendError(code, message_for(code, server_message))

    def real_room_id(self, rid: str, cookie: str = "") -> str:
        """短号 → 真实房间号;换不到就原样用(让 B 站自己去判定)。"""
        if rid in self._room_ids:
            return self._room_ids[rid]
        url = f"{self._live}/room/v1/Room/get_info?room_id={urllib.parse.quote(rid)}"
        payload = self._try_get(url, cookie)
        room_id = str(((payload or {}).get("data") or {}).get("room_id") or "")
        resolved = room_id or rid
        self._room_ids[rid] = resolved
        return resolved

    def fetch_identity(self, cookie: str) -> Identity | None:
        """nav 接口取自己的 uid/昵称/头像;取不到返回 None(回显就交给 websocket)。"""
        payload = self._try_get(f"{self._api}/x/web-interface/nav", cookie)
        data = (payload or {}).get("data") or {}
        if not data.get("isLogin") or not data.get("mid"):
            return None
        return Identity(
            uid=str(data["mid"]),
            name=str(data.get("uname", "") or ""),
            avatar=str(data.get("face", "") or ""),
        )

    # --- HTTP ---
    def _request(self, url: str, form: dict | None = None, cookie: str = "") -> dict:
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("Referer", "https://live.bilibili.com/")
        if data is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return _decode(resp.read())
        except urllib.error.HTTPError as exc:
            # 风控/参数错误有时走非 200,body 仍是 JSON:优先用它,别把原因丢了
            try:
                return _decode(exc.read())
            except ValueError:
                raise SendError(exc.code, message_for(exc.code, str(exc.reason))) from exc
        except urllib.error.URLError as exc:
            raise SendError(0, f"无法连接 B 站:{exc.reason}") from exc
        except ValueError as exc:
            raise SendError(0, "B 站返回了无法解析的响应") from exc

    def _try_get(self, url: str, cookie: str = "") -> dict | None:
        try:
            return self._request(url, cookie=cookie)
        except SendError as exc:
            logger.debug("辅助请求失败(忽略):%s %s", url, exc)
            return None


def _decode(raw: bytes) -> dict:
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    if not isinstance(payload, dict):
        # 调用方(_request)只捕获 ValueError:保持这一条约定,不对类型分层
        raise ValueError(f"response is not a JSON object: {payload!r}")  # noqa: TRY004
    return payload


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
