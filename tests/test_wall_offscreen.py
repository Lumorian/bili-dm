import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QPaintEvent, QPainter
from PyQt6.QtWidgets import QApplication

from bilidm_overlay.danmaku.lifecycle import Wall
from bilidm_overlay.danmaku.model import Danmaku
from bilidm_overlay.danmaku.wall import WallWidget


def test_paints_rows_without_error():
    app = QApplication.instance() or QApplication([])
    widget = WallWidget()
    widget.resize(400, 300)
    wall = Wall(max_rows=5, ttl=60)
    wall.add(Danmaku(type="chat", platform="bilibili", name="A", content="你好"), now=0.0)
    wall.add(Danmaku(type="gift", name="B", item="辣条", num=20), now=1.0)
    wall.add(Danmaku(type="superchat", name="C", content="加油!", price=30), now=1.5)
    widget.update_wall(wall, now=2.0)
    painter = QPainter(widget)
    widget.paintEvent(QPaintEvent(widget.rect()))
    painter.end()
    assert widget.row_count() == 3  # 三行均已入墙,绘制过程无异常


def test_clear_rows():
    app = QApplication.instance() or QApplication([])
    widget = WallWidget()
    widget.update_wall(Wall(), now=0.0)
    widget.update_wall(wall := Wall(), now=0.0)
    wall.add(Danmaku(name="A"), now=0.0)
    widget.update_wall(wall, now=0.0)
    wall.clear()
    widget.update_wall(wall, now=0.0)
    assert widget.row_count() == 0
