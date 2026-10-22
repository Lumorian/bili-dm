"""滚动墙的纯逻辑:有界行数、计数淘汰、可上下滚动的视口(无 Qt 依赖,可无头测试)。

两条轴分开:
- **数据轴**(`Wall`):按条数上限淘汰最旧的,弹幕没有时间 TTL;
- **视口轴**(`Viewport`):屏幕能放下多少、当前往上翻了多少像素。

视口是 **像素级** 的,不是整行级的:上滚半行就该露出半行。早期实现只挑"放得下的整行",
上滚一点点会突然跳一行,滚动条和滚轮都没法做得跟手。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
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


@dataclass(frozen=True, slots=True)
class Viewport:
    """一帧该画什么:哪些行、各自的 y(相对 widget 顶),以及滚动状态的回执。

    `offset` 是**已经 clamp 过**的实际偏移,调用方要把它写回去 —— 否则用户滚到顶之后
    内容还在变(新弹幕到达/旧弹幕淘汰)时,内部状态会和画面对不上。
    """

    entries: tuple[tuple[Row, float], ...]
    offset: float
    max_offset: float
    content_height: float
    avail_height: float

    @property
    def following(self) -> bool:
        """是否贴着底部(跟随最新)。用户滚回底部即自动恢复。"""
        return self.offset <= 0.0

    @property
    def scrollable(self) -> bool:
        return self.max_offset > 0.0

    def rows(self) -> list[Row]:
        return [row for row, _y in self.entries]


def content_height(rows: Sequence[Row], measure: Callable[[Row], float]) -> float:
    """全部行的总高(含行距;measure 由调用方提供,含间距)。"""
    return float(sum(measure(row) for row in rows))


def clamp_offset(offset: float, max_offset: float) -> float:
    """把偏移收进 [0, max_offset];负数(用户想往下滚过头)一律回到 0 = 跟随最新。"""
    if max_offset <= 0.0 or offset <= 0.0:
        return 0.0
    return min(float(offset), max_offset)


def viewport(
    rows: Sequence[Row],
    avail_height: float,
    measure: Callable[[Row], float],
    offset: float = 0.0,
    pad_top: float = 0.0,
) -> Viewport:
    """算出这一帧要画的行与 y。

    offset=0 时贴底(最新一条一定在),offset=max_offset 时停在最旧一行;
    中间任意像素都能停 —— 边缘那行会被裁一半,和真正的滚动容器一致。
    """
    if not rows:
        return Viewport((), 0.0, 0.0, 0.0, avail_height)
    heights = [float(measure(row)) for row in rows]
    total = sum(heights)
    if avail_height <= 0:
        # 窗口还没量出高度(0 或负数):只画最新一行,别把整屏算成"全都能显示"
        return Viewport(((rows[-1], pad_top),), 0.0, 0.0, total, avail_height)
    max_offset = max(0.0, total - avail_height)
    eff = clamp_offset(offset, max_offset)
    # 内容坐标里的视口顶:内容比屏幕短时停在 0(顶对齐,和旧行为一致)
    top = total - avail_height - eff if max_offset > 0 else 0.0
    entries: list[tuple[Row, float]] = []
    cum = 0.0
    for row, height in zip(rows, heights):
        if height <= 0.0:
            continue
        bottom = cum + height
        if bottom > top and cum < top + avail_height:
            entries.append((row, pad_top + cum - top))
        cum = bottom
        if cum >= top + avail_height:
            break
    return Viewport(tuple(entries), eff, max_offset, total, avail_height)


def visible_window(
    rows: list[Row], avail_height: float, measure: Callable[[Row], float]
) -> list[Row]:
    """贴底时可见的行(旧接口,等价于 offset=0 的 viewport)。

    保留它是因为"自动滚底"这个语义本身值得有一个名字;滚动路径请直接用 viewport。
    """
    return viewport(rows, avail_height, measure).rows()


def added_height(
    previous: Sequence[Row], current: Sequence[Row], measure: Callable[[Row], float]
) -> float:
    """这一轮新追加到末尾的行,总共多高。

    用户在往上翻时必须把它加进 offset:否则新弹幕一到,视线看到的还是"距底部 N 像素",
    而底部变长了,画面就会自己往上漂 —— 手一停,内容就在动。
    """
    seen = {id(row) for row in previous}
    return float(sum(measure(row) for row in current if id(row) not in seen))


def scroll_offset_by(
    offset: float,
    delta: float,
    rows: Sequence[Row],
    avail_height: float,
    measure: Callable[[Row], float],
) -> float:
    """滚轮/按键的位移应用到 offset(正 delta = 往上看更旧的内容)。"""
    max_offset = max(0.0, content_height(rows, measure) - max(0.0, avail_height))
    return clamp_offset(offset + delta, max_offset)
