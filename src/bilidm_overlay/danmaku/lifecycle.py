"""滚动墙的纯逻辑:有界行数、计数淘汰(无时间 TTL,弹幕保留到被新行顶替;无 Qt 依赖,可无头测试)。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .model import Danmaku


@dataclass(slots=True)
class Row:
    msg: Danmaku


class Wall:
    def __init__(self, max_rows: int = 30) -> None:
        self._max_rows = max_rows
        self._rows: list[Row] = []

    def add(self, msg: Danmaku) -> None:
        self._rows.append(Row(msg=msg))
        if len(self._rows) > self._max_rows:
            del self._rows[: len(self._rows) - self._max_rows]

    def snapshot(self) -> list[Row]:
        return list(self._rows)

    def clear(self) -> None:
        self._rows.clear()


def visible_window(
    rows: list[Row], avail_height: float, measure: Callable[[Row], float]
) -> list[Row]:
    """返回面板可容纳的最新行(自动滚底:从末尾回溯,最新一条始终可见)。

    纯逻辑,行高由调用方提供的 measure(row) 量取(含行距;widget 用字体度量)。
    avail_height 非正时退化为只返回最新一行;最新一行放不下时同样退化为仅返回它。
    """
    if not rows:
        return []
    if avail_height <= 0:
        return rows[-1:]
    budget = avail_height
    picked: list[Row] = []
    for row in reversed(rows):
        h = measure(row)
        if h <= 0 or h > budget:
            break
        budget -= h
        picked.append(row)
    return picked[::-1] if picked else rows[-1:]
