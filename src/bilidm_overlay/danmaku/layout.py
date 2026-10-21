"""行内流式排版:把一串 run(文本 / 原子盒子)按宽度折行(纯逻辑,无 Qt 依赖)。

官方聊天列表是浏览器里的一行行 inline 元素,自带 `overflow-wrap:anywhere` +
`word-break:break-word`,元素间靠 margin 拉开。自绘面板没有 HTML 布局,这里重做最小
可用的一套:

- 文本 run 按 token 折行:ASCII 单词整体换行(不在词内断开),CJK 与其它字符逐字可断
- 原子盒子 run(粉丝勋章胶囊、头像)不可拆分:放不下就整体换行
- 单个 token 比整行还宽时退化为逐字硬断(对应 `word-break:break-word`)
- `run.pad_right` 模拟官方 inline 元素间的 margin(不加在行尾)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Run:
    """一个行内元素:文本(color/scale/bold)或原子盒子(box_kind/尺寸)。"""

    text: str = ""
    color: str = ""
    scale: float = 1.0
    bold: bool = False
    pad_right: float = 0.0  # 对应官方的 margin-right(px,已按字号缩放过)
    box_kind: str = ""  # "" 表示纯文本;"medal" 为原子盒子
    box_width: float = 0.0
    box_height: float = 0.0
    data: object = None  # 盒子绘制所需的原始数据(勋章)


@dataclass(slots=True)
class Placed:
    """排版结果里的一项:哪个 run、哪段文本、落在 (x, y)。"""

    run: Run
    text: str
    x: float
    y: float
    width: float


@dataclass(slots=True)
class Line:
    items: list[Placed] = field(default_factory=list)
    y: float = 0.0
    height: float = 0.0
    width: float = 0.0


def _is_word_char(ch: str) -> bool:
    """ASCII 字母数字算词字符(整词不拆);CJK/标点/空格逐字可断。"""
    return ch.isascii() and ch.isalnum()


def tokenize(text: str) -> list[str]:
    """切成折行最小单位:连续 ASCII 词 / 单个其它字符。"""
    tokens: list[str] = []
    word = ""
    for ch in text:
        if _is_word_char(ch):
            word += ch
            continue
        if word:
            tokens.append(word)
            word = ""
        tokens.append(ch)
    if word:
        tokens.append(word)
    return tokens


def wrap_runs(
    runs: list[Run],
    avail_width: float,
    measure_text,
    line_height: float,
) -> list[Line]:
    """按 avail_width 折行。

    measure_text(text, run) -> 该段文本在 run 的字体下的宽度;
    line_height 为单行文本高度(行高),盒子高度取 max(盒子高, 行高)。
    """
    lines: list[Line] = []
    if avail_width <= 0:
        return lines
    cur = Line(y=0.0, height=line_height)
    x = 0.0

    def newline() -> None:
        nonlocal cur, x
        lines.append(cur)
        cur = Line(y=cur.y + cur.height, height=line_height)
        x = 0.0

    for run in runs:
        if run.box_kind:
            w = run.box_width
            if x > 0 and x + w > avail_width:
                newline()
            cur.items.append(Placed(run, "", x, cur.y, w))
            x += w
            cur.width = x
            cur.height = max(cur.height, run.box_height)
            x += run.pad_right if _has_more(runs, run) else 0.0
            continue
        tokens = tokenize(run.text)
        for index, token in enumerate(tokens):
            w = measure_text(token, run)
            if x > 0 and x + w > avail_width:
                newline()
            if w > avail_width:
                # 单词比整行还宽:逐字硬断
                for ch_ in token:
                    cw = measure_text(ch_, run)
                    if x > 0 and x + cw > avail_width:
                        newline()
                    _append(cur, run, ch_, x, cw)
                    x += cw
                cur.width = x
                continue
            _append(cur, run, token, x, w)
            x += w
            cur.width = x
            # 行尾不留 margin:只有本 run 后面还有内容才补
            if index == len(tokens) - 1 and _has_more(runs, run):
                x += run.pad_right
    lines.append(cur)
    return lines


def _append(line: Line, run: Run, text: str, x: float, width: float) -> None:
    """同 run 的相邻字符/词合并进同一项,避免产生海量 Placed。"""
    if line.items and line.items[-1].run is run:
        last = line.items[-1]
        last.text += text
        last.width += width
        return
    line.items.append(Placed(run, text, x, line.y, width))


def _has_more(runs: list[Run], run: Run) -> bool:
    """本 run 是否是最后一个(行尾 margin 不生效,与浏览器一致)。"""
    for index, candidate in enumerate(runs):
        if candidate is run:
            return index != len(runs) - 1
    return False


def block_height(lines: list[Line], line_height: float) -> float:
    """块高 = 各行高之和;空内容至少一行(与浏览器空行占位一致)。"""
    if not lines:
        return line_height
    return sum(line.height for line in lines)
