"""滚动墙渲染:单 widget 自绘,行按年龄淡出。"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PyQt6.QtWidgets import QWidget

from .avatars import AVATAR_SIDE, AvatarCache
from .lifecycle import Row, Wall, visible_window
from .style import style_for

AVATAR_GAP = 6          # 头像与文字间距
TEXT_X = 6 + AVATAR_SIDE + AVATAR_GAP


class WallWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._font = QFont()
        self._size = 13  # set_font() 未调用前的默认像素字号(与历史硬编码一致)
        self._wall: Wall | None = None
        self._now = 0.0
        self._show_tag = False
        self._avatars: AvatarCache | None = None

    def set_avatars(self, cache: AvatarCache | None) -> None:
        """挂载头像缓存:pixmap() 未命中会触发异步下载,loaded 后窗口触发 update。"""
        self._avatars = cache
        self.update()

    def set_font(self, family: str, size: int) -> None:
        self._size = size
        self._font = QFont(family, size)
        self.update()

    def set_show_tag(self, show: bool) -> None:
        """合并模式多房间时,每行前缀显示 platform/rid 标签。"""
        self._show_tag = show
        self.update()

    def set_panel_opacity(self, opacity: float) -> None:
        self.setAutoFillBackground(True)
        pal = self.palette()
        bg = QColor(16, 16, 20)
        bg.setAlphaF(opacity)
        pal.setColor(self.backgroundRole(), bg)
        self.setPalette(pal)

    def update_wall(self, wall: Wall, now: float) -> None:
        self._wall = wall
        self._now = now
        self.update()

    def row_count(self) -> int:
        return len(self._wall.snapshot()) if self._wall else 0

    def _line_height(self) -> int:
        """一行高度(含 4px 行距,且不小于头像边长)。"""
        font = QFont(self._font)
        font.setPixelSize(self._size)
        return max(QFontMetrics(font).height(), AVATAR_SIDE) + 4

    def paintEvent(self, event) -> None:
        del event
        if self._wall is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        # 自适应行数 + 自动滚底:只绘制面板能容纳的最新行
        rows = visible_window(self._wall.snapshot(), avail_height=float(self.height() - 12), line_height=float(self._line_height()))
        y = 6.0
        for row in rows:
            alpha = self._wall.alpha_of(row, self._now)
            if alpha <= 0.0:
                continue
            spec = style_for(row.msg)
            y = self._paint_row(painter, row, spec, y, alpha) + 4.0
        painter.end()

    def _paint_row(self, painter: QPainter, row: Row, spec, y: float, alpha: float) -> float:
        font = QFont(self._font)
        font.setPixelSize(int(self._size * spec.size_scale))
        painter.setFont(font)
        fm = painter.fontMetrics()
        self._draw_avatar(painter, row.msg, y, alpha)
        tag = ""
        if self._show_tag and row.msg.platform and row.msg.rid:
            tag = f"{row.msg.platform}/{row.msg.rid} "
        name = f"{spec.prefix}{row.msg.name} "
        text = f"{tag}{name}{row.msg.content}"
        color = QColor(spec.name_color)
        color.setAlphaF(alpha)
        painter.setPen(color)
        text_width = self.width() - TEXT_X - 6
        if fm.horizontalAdvance(text) > text_width:
            text = fm.elidedText(text, Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(
            QRectF(TEXT_X, y, text_width, fm.height()),
            Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        return y + max(fm.height(), AVATAR_SIDE)

    def _draw_avatar(self, painter: QPainter, msg, y: float, alpha: float) -> None:
        rect = QRectF(6.0, y, AVATAR_SIDE, AVATAR_SIDE)
        pix = self._avatars.pixmap(msg.avatar) if self._avatars is not None else None
        if pix is not None:
            scaled = pix.scaled(AVATAR_SIDE, AVATAR_SIDE, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            path = QPainterPath()
            path.addEllipse(rect)
            painter.save()
            painter.setClipPath(path)
            painter.drawPixmap(rect.toRect(), scaled)
            painter.restore()
            return
        # 占位:灰圆 + 名字首字
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(72, 72, 80, int(200 * alpha)))
        painter.drawEllipse(rect)
        first = (msg.name or "").strip()[:1]
        if first:
            font = QFont(self._font)
            font.setPixelSize(int(self._size * 0.65))
            painter.setFont(font)
            painter.setPen(QColor(220, 220, 225, int(255 * alpha)))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, first)
