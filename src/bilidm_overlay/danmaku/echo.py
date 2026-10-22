"""自己发的弹幕的本地回显去重(纯逻辑,无 Qt/网络依赖)。

官方弹幕姬点「发送」后,自己那条立刻出现在列表里。本项目照做:发送成功就先本地插一行,
等 WebSocket 把同一条弹幕推回来时**不再插第二行**。

难点是"哪一条回推对应我刚才那一行",而且回推可能比 HTTP 响应**先到**(服务端广播比
写回响应快)。所以登记必须发生在"按下发送"那一刻,而不是"确认成功"那一刻:

- 登记时只有正文(和自己的 uid 还不知道),条目按正文匹配,拿到身份后再把 uid 补上;
- 三条一起成立才算同一条:正文一致、(已知时)uid 是自己、且在时间窗内;
- 时间窗是必需的:同一个人重复刷同一句话很常见,不能被永久吞掉;
- 期望会自己过期:回推可能压根不来(不在房间里/ws 断线),留着会误吞后来的正常弹幕。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .model import Danmaku

WINDOW_S = 8.0  # 回推通常 <1s;8s 足够宽,又不至于把重复刷屏吞掉太久
MAX_PENDING = 8  # 连发时最多记这么多条,防止长时间堆积


@dataclass(slots=True)
class _Pending:
    text: str
    at: float
    uid: str = ""  # 空串 = 自己的 uid 还没取到,先按正文匹配


class EchoTracker:
    """把自己发出的弹幕记为"待回推",回推到达时抵扣一次。"""

    def __init__(self, window: float = WINDOW_S, clock=time.monotonic) -> None:
        self._window = window
        self._clock = clock
        self._pending: list[_Pending] = []

    def expect(self, text: str, uid: str = "") -> None:
        """登记一条即将发送的弹幕(正文为空则不登记:没有正文就无从匹配)。"""
        text = (text or "").strip()
        if not text:
            return
        self._prune()
        self._pending.append(_Pending(text=text, at=self._clock(), uid=str(uid or "")))
        if len(self._pending) > MAX_PENDING:
            del self._pending[: len(self._pending) - MAX_PENDING]

    def bind_uid(self, uid: str) -> None:
        """取到自己的 uid 后回填:之后同一条回推必须 uid 也对上才算自己发的。"""
        if not uid:
            return
        for p in self._pending:
            if not p.uid:
                p.uid = str(uid)

    def consume(self, d: Danmaku) -> bool:
        """这条回推是不是自己刚发的那条?是则抵扣并返回 True(调用方跳过插入)。"""
        self._prune()
        if not d.content:
            return False
        for i, p in enumerate(self._pending):
            if p.text != d.content.strip():
                continue
            # uid 已知就必须对上:别人恰好说了同一句话时别把他吞掉
            if p.uid and d.uid and p.uid != str(d.uid):
                continue
            del self._pending[i]
            return True
        return False

    def cancel(self, text: str) -> None:
        """发送失败:撤掉这条期望,免得它把后来一条内容相同的正常弹幕误吞。"""
        text = (text or "").strip()
        for i, p in enumerate(self._pending):
            if p.text == text:
                del self._pending[i]
                return

    def pending_count(self) -> int:
        self._prune()
        return len(self._pending)

    def _prune(self) -> None:
        cutoff = self._clock() - self._window
        self._pending = [p for p in self._pending if p.at >= cutoff]
