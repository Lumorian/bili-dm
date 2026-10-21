"""滚动墙渲染:1:1 复刻官方直播间聊天面板(`chat-history-panel`)的行内排版。

排版参数全部取自线上 CSS / 组件代码(见
`docs/superpowers/specs/2026-10-21-chat-panel-parity-design.md`):

- 列表 `.chat-history-list{padding:5px 10px;font-size:12px}`
- 行 `.chat-item{padding:5px}`,`.danmaku-item{line-height:18px}`
- 行内顺序:粉丝勋章胶囊 → 昵称 + `" : "` → 正文
- 礼物行:昵称 + 赠送 + 礼物名 + `x20`,礼物名/数量统一 `var(--pay_yellow)`
- 上舰:昵称 + 开通了 + 舰长
- 醒目留言:整块卡片(底色渐变 + 头像 + 昵称 + 金额 + 正文)

本项目在行首额外保留 24px 圆形头像(用户要求),其余沿用官方度量。
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QGradient,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import QWidget

from . import style as sty
from .avatars import AVATAR_SIDE, AvatarCache
from .layout import Run, block_height, wrap_runs
from .lifecycle import Row, Wall, visible_window
from .medal import (
    BASE_FONT_PX,
    GUARD_ICON,
    GUARD_ICON_OFFSET,
    MEDAL_CTNR_HEIGHT,
    MEDAL_MARGIN_LEFT,
    MEDAL_MARGIN_RIGHT,
    PILL_HEIGHT,
    PILL_PAD_RIGHT,
    PILL_TEXT_SCALE,
    Medal,
    level_slot_width,
    medal_from,
)
from .theme import DARK, Theme, theme_for

# 卡片底色(RGB):控制带(window._apply_card_background)与面板共用,改色只改这一处
PANEL_BG = (16, 16, 17)
# 卡片圆角(px):与 niri layer-rule 的 geometry-corner-radius 同步(全局 window-rule 同为 12)
PANEL_RADIUS = 12

# 官方度量的常量(headless Chrome 量出的 12px 基准盒子,见 medal.py 注释)
PANEL_PAD_X = 10.0  # .chat-history-list{padding:5px 10px}
PANEL_PAD_Y = 5.0
ROW_PAD = 5.0  # .chat-item{padding:5px}
# 行框高 20px:由 .user-name{line-height:20px} 撑起(.chat-item 高 30 = 5+20+5)
LINE_HEIGHT_RATIO = 20.0 / 12.0
AVATAR_GAP = 5.0  # 行首头像与后续内容的间距
NAME_MARGIN_RIGHT = 5.0  # .gift-item .username/.gift-name{margin-right:5px}
ACTION_MARGIN_RIGHT = 4.0  # .gift-item .action{margin-right:4px}
TEXT_X = PANEL_PAD_X + AVATAR_SIDE + AVATAR_GAP  # 正文列起点(旧测试依赖)
# 大航海成员的昵称色(官方 nameColor;截图中舰队成员为青蓝)
GUARD_NAME_COLOR = "#00D1F1"
# 系统行(点赞/进房等)描述灰,官方 interact 行 #999999
SYSTEM_NAME_COLOR = "#999999"
# 醒目留言卡片默认底色(官方 SC 主题黄)与圆角
SC_CARD_START = "#F2C55C"
SC_CARD_END = "#E9A100"
SC_CARD_RADIUS = 6.0


def _luminance(color: str) -> float:
    """#RRGGBB 的相对亮度(0~1),用于给 SC 卡片挑深/浅文字色。"""
    value = color.lstrip("#")
    if len(value) != 6:
        return 0.7
    try:
        r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return 0.7
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def sc_text_color(msg, theme: Theme) -> str:
    """醒目留言卡片的文字色:亮底用主题的深色字,深底用白字。"""
    if msg.price_color:
        return msg.price_color
    background = msg.bg_color_start or SC_CARD_START
    return theme.card_text if _luminance(background) > 0.55 else "#FFFFFF"


class WallWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._font = QFont()
        self._size = 12  # 官方列表基准字号 12px
        self._theme: Theme = DARK
        self._wall: Wall | None = None
        self._show_tag = False
        self._avatars: AvatarCache | None = None
        # 排版缓存:30ms 重绘下避免每帧重建 run 与折行;key 含文本/宽度/字号/主题
        self._layout_cache: dict[tuple, tuple[list, float]] = {}
        self._font_cache: dict[tuple[int, bool], QFont] = {}
        self._metrics_cache: dict[tuple[int, bool], QFontMetricsF] = {}

    # --- 配置 ---
    def set_avatars(self, cache: AvatarCache | None) -> None:
        """挂载头像缓存:pixmap() 未命中会触发异步下载,loaded 后窗口触发 update。"""
        self._avatars = cache
        self.update()

    def set_font(self, family: str, size: int) -> None:
        self._size = size
        self._font = QFont(family, size)
        self._layout_cache.clear()
        self._font_cache.clear()
        self._metrics_cache.clear()
        self.update()

    def set_theme(self, name: str) -> None:
        self._theme = theme_for(name)
        self._layout_cache.clear()
        self.update()

    def set_show_tag(self, show: bool) -> None:
        """合并模式多房间时,每行前缀显示 platform/rid 标签。"""
        self._show_tag = show
        self._layout_cache.clear()
        self.update()

    def update_wall(self, wall: Wall) -> None:
        self._wall = wall
        self.update()

    def row_count(self) -> int:
        return len(self._wall.snapshot()) if self._wall else 0

    # --- 度量 ---
    @property
    def _scale(self) -> float:
        """相对官方 12px 基准的缩放比(改字号时徽章尺寸等比跟上)。"""
        return self._size / BASE_FONT_PX

    def _line_height(self) -> float:
        return round(self._size * LINE_HEIGHT_RATIO)

    def _font_for(self, px: float, bold: bool = False) -> QFont:
        size = max(1, round(px))
        key = (size, bold)
        font = self._font_cache.get(key)
        if font is None:
            font = QFont(self._font)
            font.setPixelSize(size)
            font.setBold(bold)
            self._font_cache[key] = font
        return font

    def _metrics(self, px: float, bold: bool = False) -> QFontMetricsF:
        key = (max(1, round(px)), bold)
        m = self._metrics_cache.get(key)
        if m is None:
            m = QFontMetricsF(self._font_for(px, bold))
            self._metrics_cache[key] = m
        return m

    def _measure(self, text: str, run: Run) -> float:
        return self._metrics(self._size * run.scale, run.bold).horizontalAdvance(text)

    # --- 行内元素 ---
    def _medal_size(self, medal: Medal) -> tuple[float, float]:
        """胶囊尺寸(px):官方几何 × 当前字号缩放;航海图标绝对定位,不计入宽度。

        名字宽度取**未缩放**的度量:`transform:scale(.8333)` 只改视觉不改布局。
        """
        scale = self._scale
        name_w = self._metrics(self._size).horizontalAdvance(medal.name)
        width = medal.pill_width(lambda _text: name_w) * scale
        return width, PILL_HEIGHT * scale

    def _medal_run(self, medal: Medal) -> Run:
        width, height = self._medal_size(medal)
        # .fans-medal-item-ctnr{margin-left:4px;margin-right:3px}:左侧留白并进盒子,
        # 右侧留白交给排版器(行尾自动丢弃,与浏览器一致)。
        return Run(
            box_kind="medal",
            box_width=width + MEDAL_MARGIN_LEFT * self._scale,
            box_height=max(height + 1.0 * self._scale, MEDAL_CTNR_HEIGHT * self._scale),
            pad_right=MEDAL_MARGIN_RIGHT * self._scale,
            data=medal,
        )

    def _runs_for(self, row: Row) -> list[Run]:
        """按消息类型组装一行(或一张 SC 卡片)的 run 序列,顺序同官方行内。"""
        msg = row.msg
        spec = sty.style_for(msg)
        theme = self._theme
        scale = self._scale
        runs: list[Run] = []

        medal = medal_from(msg.medal)
        if medal is not None:
            runs.append(self._medal_run(medal))
        if self._show_tag and msg.platform and msg.rid:
            runs.append(
                Run(text=f"{msg.platform}/{msg.rid}", color=SYSTEM_NAME_COLOR,
                    pad_right=NAME_MARGIN_RIGHT * scale)
            )

        name_color = spec.name_color or theme.name_text
        if not spec.name_color and msg.guard_level > 0:
            name_color = GUARD_NAME_COLOR

        if spec.kind == sty.KIND_GIFT:
            runs.append(Run(text=msg.name, color=name_color, pad_right=NAME_MARGIN_RIGHT * scale))
            runs.append(Run(text=sty.GIFT_ACTION, color=theme.text,
                            pad_right=ACTION_MARGIN_RIGHT * scale))
            if msg.item:
                runs.append(Run(text=msg.item, color=theme.pay_yellow,
                                pad_right=NAME_MARGIN_RIGHT * scale))
            num = sty.gift_num_text(msg)
            if num:
                runs.append(Run(text=num, color=theme.pay_yellow))
            return runs

        if spec.kind == sty.KIND_SUBSCRIBE:
            runs.append(Run(text=msg.name, color=name_color, pad_right=NAME_MARGIN_RIGHT * scale))
            runs.append(Run(text=sty.SUBSCRIBE_ACTION, color=theme.text,
                            pad_right=ACTION_MARGIN_RIGHT * scale))
            if msg.item:
                runs.append(Run(text=msg.item, color=theme.pay_yellow))
            return runs

        if spec.kind == sty.KIND_SYSTEM:
            if msg.name:
                runs.append(Run(text=msg.name, color=theme.name_text,
                                pad_right=4.0 * scale))
            text = sty.system_text(msg)
            if text:
                runs.append(Run(text=text, color=SYSTEM_NAME_COLOR))
            return runs

        # chat / superchat:昵称 + " : " + 正文
        if spec.kind == sty.KIND_SUPERCHAT:
            # SC 卡片整块是主题色底,正文用对比色(官方 .card-item-middle-top-right{color:#333}),
            # 协议若给了 price_color / 卡片深色底则自动改用浅色字。
            card_color = sc_text_color(msg, theme)
            runs.append(Run(text=msg.name, color=card_color))
            runs.append(Run(text=sty.NAME_SEPARATOR, color=card_color))
            if msg.content:
                runs.append(Run(text=msg.content, color=spec.content_color or card_color))
            return runs
        runs.append(Run(text=msg.name, color=name_color))
        runs.append(Run(text=sty.NAME_SEPARATOR, color=theme.text))
        if msg.content:
            runs.append(Run(text=msg.content, color=spec.content_color or theme.text))
        return runs

    # --- 排版 ---
    def _text_width(self) -> float:
        return max(1.0, float(self.width()) - TEXT_X - PANEL_PAD_X)

    def _prepare(self, row: Row, text_width: float) -> tuple[list, float]:
        """一行所需:折行结果与块高(不小于头像边长);按内容/宽度/字号/主题缓存。"""
        msg = row.msg
        key = (
            msg.type,
            msg.name,
            msg.content,
            msg.item or "",
            msg.num,
            msg.guard_level,
            msg.user_level,
            msg.name_color,
            msg.price,
            msg.platform,
            msg.rid,
            msg.medal.name if msg.medal else "",
            msg.medal.level if msg.medal else 0,
            msg.medal.color_start if msg.medal else "",
            msg.medal.guard_level if msg.medal else 0,
            self._show_tag,
            round(text_width, 1),
            self._size,
            self._theme.name,
        )
        cached = self._layout_cache.get(key)
        if cached is not None:
            return cached
        runs = self._runs_for(row)
        line_h = self._line_height()
        lines = wrap_runs(runs, text_width, self._measure, line_h)
        # 行高对齐官方:.chat-item{padding:5px} + line-height 18px = 28px。
        # 行首头像(24px)允许占用两侧 padding,故内容高只需保证头像能落在行内:
        # max(文本块, 头像高 - 上下 padding),单行时仍是 18px,不会把行距撑大。
        height = max(block_height(lines, line_h), float(AVATAR_SIDE) - 2 * ROW_PAD)
        if len(self._layout_cache) >= 256:
            self._layout_cache.clear()
        self._layout_cache[key] = (lines, height)
        return lines, height

    def paintEvent(self, event) -> None:
        del event
        if self._wall is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 卡片背景由容器(QSS)绘制;面板自身内容裁剪进圆角,避免内容溢出四角
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), PANEL_RADIUS, PANEL_RADIUS)
        painter.setClipPath(path)
        rows = self._wall.snapshot()
        text_width = self._text_width()
        prepped = {id(row): self._prepare(row, text_width) for row in rows}
        visible = visible_window(
            rows,
            avail_height=float(self.height() - 2 * PANEL_PAD_Y),
            measure=lambda row: prepped[id(row)][1] + 2 * ROW_PAD,
        )
        y = PANEL_PAD_Y
        for row in visible:
            lines, height = prepped[id(row)]
            if row.msg.type == sty.KIND_SUPERCHAT:
                self._paint_superchat(painter, row, lines, height, y)
            else:
                self._paint_row(painter, row, lines, height, y)
            y += height + 2 * ROW_PAD
        painter.end()

    # --- 绘制 ---
    def _paint_row(self, painter: QPainter, row: Row, lines: list, height: float, y: float) -> None:
        top = y + ROW_PAD
        # 头像与正文首行垂直居中:中线 = 行块顶 + padding + 行框高/2。
        # 单行时正好落在整行块中心(与之前一致),折行时贴住第一行——
        # 既不能再用 y-ROW_PAD(会把头像整体抬高 5px),也不能按整块居中
        # (多行时头像会飘到段落正中,离首行文字很远)。
        self._draw_avatar(painter, row.msg, top + self._line_height() / 2)
        for line in lines:
            for item in line.items:
                self._draw_item(painter, item, top + line.y)

    def _draw_item(self, painter: QPainter, item, y: float) -> None:
        run = item.run
        if run.box_kind == "medal":
            self._draw_medal(painter, TEXT_X + item.x, run.data, y)
            return
        if not item.text:
            return
        px = self._size * run.scale
        metrics = self._metrics(px, run.bold)
        painter.setFont(self._font_for(px, run.bold))
        painter.setPen(QColor(run.color or self._theme.text))
        # 基线:行框内垂直居中(官方 line-height:18px + 12px 字号的观感)
        baseline = y + (self._line_height() - metrics.height()) / 2 + metrics.ascent()
        painter.drawText(QPointF(TEXT_X + item.x, baseline), item.text)

    def _draw_medal(self, painter: QPainter, box_x: float, medal: Medal, y: float) -> None:
        """粉丝勋章胶囊:45° 渐变底 + 1px 描边 + 航海锚 + 名字 + 等级槽位。

        box_x 是 `.fans-medal-item-ctnr` 左边(含 4px margin-left),胶囊本身从
        `box_x + 4px` 开始 —— 与官方量出的盒子一致。
        """
        width, pill_h = self._medal_size(medal)
        scale = self._scale
        x = box_x + MEDAL_MARGIN_LEFT * scale
        top = y + (self._line_height() - pill_h) / 2
        rect = QRectF(x, top, width, pill_h)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(medal.color_start))
        gradient.setColorAt(1.0, QColor(medal.color_end))
        gradient.setSpread(QGradient.Spread.PadSpread)
        painter.setBrush(QBrush(gradient))
        painter.setPen(QPen(QColor(medal.color_border), 1.0))
        painter.drawRoundedRect(rect, pill_h / 2, pill_h / 2)

        px = self._size
        metrics = self._metrics(px)
        if medal.is_guard:
            # 官方:left:6px + margin-left:-12px → 20×20 图标左缘在胶囊左缘外 4px、垂直居中
            icon = GUARD_ICON * scale
            icon_left = x + GUARD_ICON_OFFSET * scale
            self._draw_anchor(
                painter,
                QRectF(icon_left, rect.center().y() - icon / 2, icon * 0.72, icon * 1.05),
            )
        # 勋章名:.fans-medal-content{transform:scale(.8333)},transform-origin 默认居中 ——
        # 布局仍占满名字原宽,视觉上两侧各内缩一点(与官方的文字间距观感一致)。
        name_w = metrics.horizontalAdvance(medal.name)
        name_x = x + medal.pad_left * scale + name_w / 2
        painter.save()
        painter.translate(name_x, rect.center().y())
        painter.scale(PILL_TEXT_SCALE, PILL_TEXT_SCALE)
        painter.setFont(self._font_for(px))
        painter.setPen(QColor(medal.color_text))
        painter.drawText(
            QPointF(-name_w / 2, (metrics.ascent() - metrics.descent()) / 2), medal.name
        )
        painter.restore()

        # 等级:.fans-medal-level{height:12px;width:8px},数字再缩到 91.7%
        level_w = level_slot_width(medal.level) * scale
        level_right = rect.right() - PILL_PAD_RIGHT * scale
        painter.save()
        painter.translate(level_right - level_w / 2, rect.center().y())
        painter.scale(PILL_TEXT_SCALE * 1.1 * 0.917, PILL_TEXT_SCALE * 1.1 * 0.917)
        painter.setFont(self._font_for(px, bold=True))
        painter.setPen(QColor(medal.color_text))
        painter.drawText(
            QRectF(-level_w, -self._line_height() / 2, level_w * 2, self._line_height()),
            Qt.AlignmentFlag.AlignCenter,
            str(medal.level),
        )
        painter.restore()

    def _draw_anchor(self, painter: QPainter, rect: QRectF) -> None:
        """大航海锚图标:自绘简化锚形(官方用 CDN 图片资源,这里不引外链)。"""
        pen = QPen(QColor(255, 255, 255, 235))
        pen.setWidthF(max(1.0, rect.height() * 0.10))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.save()
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx = rect.center().x()
        ring_r = rect.width() * 0.17
        painter.drawEllipse(QPointF(cx, rect.top() + ring_r * 1.9), ring_r, ring_r)
        stem_top = rect.top() + ring_r * 3.3
        painter.drawLine(QPointF(cx, stem_top), QPointF(cx, rect.bottom() - rect.height() * 0.12))
        arm_y = stem_top + rect.height() * 0.14
        painter.drawLine(
            QPointF(cx - rect.width() * 0.30, arm_y), QPointF(cx + rect.width() * 0.30, arm_y)
        )
        arc = QRectF(
            cx - rect.width() * 0.36,
            rect.bottom() - rect.height() * 0.42,
            rect.width() * 0.72,
            rect.height() * 0.38,
        )
        painter.drawArc(arc, 200 * 16, 140 * 16)
        painter.restore()

    def _paint_superchat(
        self, painter: QPainter, row: Row, lines: list, height: float, y: float
    ) -> None:
        """醒目留言卡片:整块渐变底 + 头像 + 昵称/正文 + 右上金额。"""
        msg = row.msg
        # 卡片占满该行(含上下 padding),不侵入下一行
        card_top = y
        card_h = height + 2 * ROW_PAD
        rect = QRectF(PANEL_PAD_X, card_top, max(1.0, self.width() - 2 * PANEL_PAD_X), card_h)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(msg.bg_color_start or SC_CARD_START))
        gradient.setColorAt(1.0, QColor(msg.bg_color_end or SC_CARD_END))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(rect, SC_CARD_RADIUS, SC_CARD_RADIUS)

        # 头像与普通行共用同一列、同一垂直基准:卡片内容区顶 = card_top + ROW_PAD,
        # 头像中线取首行行框中线。此前额外叠加 inner_top 又把 x 内缩 5px,
        # 结果 SC 行的头像比其它行低 5px、右移 5px,整列头像看上去是断开的。
        inner_top = card_top + ROW_PAD
        self._draw_avatar(painter, msg, inner_top + self._line_height() / 2)
        for line in lines:
            for item in line.items:
                self._draw_item(painter, item, inner_top + line.y)
        if msg.price:
            price_text = f"¥{msg.price:g}"
            metrics = self._metrics(self._size, bold=True)
            painter.setFont(self._font_for(self._size, bold=True))
            # .card-item-top-right{color:#333}:金额默认深色,协议给了 price_color 才覆盖
            painter.setPen(QColor(msg.price_color or self._theme.card_text))
            painter.drawText(
                QRectF(rect.right() - 8.0 - 80.0, rect.top() + 4.0, 80.0, metrics.height()),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                price_text,
            )

    def _draw_avatar(self, painter: QPainter, msg, center_y: float) -> None:
        """行首头像:横向固定左列(所有行同一 x),纵向以正文首行中线居中。

        center_y 是中线坐标 —— 用中线而不是"块顶 + 块高",这样普通行与醒目留言卡片
        天然共用同一套定位,不会再出现某一类行整体偏上/偏下 5px 的错位。
        """
        side = AVATAR_SIDE
        rect = QRectF(PANEL_PAD_X, center_y - side / 2, side, side)
        pix = self._avatars.pixmap(msg.avatar) if self._avatars is not None else None
        if pix is not None:
            scaled = pix.scaled(
                AVATAR_SIDE,
                AVATAR_SIDE,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            path = QPainterPath()
            path.addEllipse(rect)
            painter.save()
            painter.setClipPath(path)
            painter.drawPixmap(rect.toRect(), scaled)
            painter.restore()
            return
        # 占位:灰圆 + 名字首字
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(72, 72, 80, 200))
        painter.drawEllipse(rect)
        first = (getattr(msg, "name", "") or "").strip()[:1]
        if first:
            font = QFont(self._font)
            font.setPixelSize(int(self._size * 0.65))
            painter.setFont(font)
            painter.setPen(QColor(220, 220, 225))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, first)
