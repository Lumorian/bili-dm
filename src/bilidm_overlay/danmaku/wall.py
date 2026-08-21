"""滚动墙渲染:单 widget 自绘,行按年龄淡出。"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QTextLayout
from PyQt6.QtWidgets import QWidget

from .lifecycle import Row, Wall
from .style import style_for


class WallWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._font = QFont()
        self._wall: Wall | None = None
        self._now = 0.0
        self._show_tag = False

    def set_font(self, family: str, size: int) -> None:
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

    def paintEvent(self, event) -> None:
        del event
        if self._wall is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        rows = self._wall.snapshot()
        y = 6.0
        for row in rows:
            alpha = self._wall.alpha_of(row, self._now)
            if alpha <= 0.0:
                continue
            spec = style_for(row.msg)
            y = self._paint_row(painter, row, spec, y, alpha) + 4.0
        painter.end()

    def _paint_row(self, painter: QPainter, row: Row, spec, y: float, alpha: float) -> float:
        size = 13 * spec.size_scale
        font = QFont(self._font)
        font.setPixelSize(int(size))
        painter.setFont(font)
        fm = painter.fontMetrics()
        tag = ""
        if self._show_tag and row.msg.platform and row.msg.rid:
            tag = f"{row.msg.platform}/{row.msg.rid} "
        name = f"{spec.prefix}{row.msg.name} "
        text = f"{tag}{name}{row.msg.content}"
        color = QColor(spec.name_color)
        color.setAlphaF(alpha)
        painter.setPen(color)
        if fm.horizontalAdvance(text) > self.width() - 12:
            text = fm.elidedText(text, Qt.TextElideMode.ElideRight, self.width() - 12)
        painter.drawText(QRectF(6, y, self.width() - 12, fm.height()), Qt.AlignmentFlag.AlignVCenter, text)
        return y + fm.height()
