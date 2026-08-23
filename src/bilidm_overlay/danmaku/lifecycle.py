"""滚动墙的纯逻辑:有界行数、TTL 淘汰、淡出曲线(无 Qt 依赖,可无头测试)。"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Danmaku


@dataclass(slots=True)
class Row:
    msg: Danmaku
    born: float  # 单调时钟秒


class Wall:
    def __init__(self, max_rows: int = 30, ttl: float = 60.0) -> None:
        self._max_rows = max_rows
        self._ttl = ttl
        self._rows: list[Row] = []

    def add(self, msg: Danmaku, now: float) -> None:
        self.prune(now)
        self._rows.append(Row(msg=msg, born=now))
        if len(self._rows) > self._max_rows:
            del self._rows[: len(self._rows) - self._max_rows]

    def prune(self, now: float) -> None:
        self._rows = [r for r in self._rows if now - r.born <= self._ttl]

    def snapshot(self) -> list[Row]:
        return list(self._rows)

    def clear(self) -> None:
        self._rows.clear()

    def alpha_of(self, row: Row, now: float) -> float:
        """TTL 前一半 1.0,后一半线性淡出到 0,过期 0。"""
        age = max(0.0, now - row.born)
        if age >= self._ttl:
            return 0.0
        half = self._ttl / 2
        if age <= half:
            return 1.0
        return 1.0 - (age - half) / half


def visible_window(rows: list[Row], avail_height: float, line_height: float) -> list[Row]:
    """返回面板可容纳的最新行(自动滚底:从末尾回溯,最新一条始终可见)。

    纯逻辑,行高由调用方(widget 字体度量)提供。avail_height 或 line_height
    非正时退化为只返回最新一行。
    """
    if not rows:
        return []
    n = max(1, int(avail_height // line_height)) if avail_height > 0 and line_height > 0 else 1
    return rows[-n:]
