"""可上下滚动查看历史弹幕:widget 侧(滚轮/滚动条/回到最新/跟随底部)。

视口的纯数学在 test_lifecycle.py;这里验的是"手真的动了"之后画面与状态对不对。
"""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent

from bilidm_overlay.danmaku.lifecycle import Wall
from bilidm_overlay.danmaku.model import Danmaku
from bilidm_overlay.danmaku.wall import PANEL_PAD_Y, WallWidget

_APP = None


@pytest.fixture(autouse=True)
def app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


def _wall(n=40, rows=200):
    wall = Wall(max_rows=rows)
    for i in range(n):
        wall.add(Danmaku(type="chat", platform="bilibili", name=f"用户{i}", content=f"第 {i} 条"))
    return wall


def _widget(wall, w=340, h=260, theme="dark"):
    widget = WallWidget()
    widget.resize(w, h)
    widget.set_font("Sans Serif", 12)
    widget.set_theme(theme)
    widget.update_wall(wall)
    widget.grab()  # 触发一次 paintEvent:建立视口回执(_last_vp)
    return widget


def _wheel(widget, dy, x=170, y=130):
    ev = QWheelEvent(
        QPointF(x, y),
        QPointF(x, y),
        QPoint(0, 0),
        QPoint(0, dy),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    widget.wheelEvent(ev)
    return ev


def _mouse(kind, widget, x, y, buttons=Qt.MouseButton.LeftButton):
    return QMouseEvent(
        kind,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.LeftButton,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def _visible_texts(widget):
    vp = widget._last_vp
    return [row.msg.content for row in vp.rows()]


# --- 默认行为不变 ---


def test_new_messages_keep_pinning_to_bottom():
    widget = _widget(_wall(40))
    assert widget.is_following() is True
    assert widget.scroll_offset() == 0.0
    assert "第 39 条" in _visible_texts(widget), "默认贴底:最新一条必须可见"


def test_content_shorter_than_panel_has_no_scrollbar():
    widget = _widget(_wall(3))
    assert widget.max_scroll() == 0.0
    assert widget._scrollbar_handle(widget._last_vp) is None


# --- 滚轮 ---


def test_wheel_up_scrolls_toward_history():
    widget = _widget(_wall(40))
    before = widget.scroll_offset()
    _wheel(widget, 120)
    assert widget.scroll_offset() > before, "滚轮往上应看更旧的内容"
    assert widget.is_following() is False
    widget.grab()
    assert "第 39 条" not in _visible_texts(widget), "翻上去之后最新一条应移出视口"


def test_wheel_down_returns_to_screen_bottom():
    widget = _widget(_wall(40))
    _wheel(widget, 120)
    _wheel(widget, 120)
    assert widget.scroll_offset() > 0
    for _ in range(20):
        _wheel(widget, -120)
    assert widget.scroll_offset() == 0.0, "往下滚到底就恢复跟随最新"
    assert widget.is_following() is True


def test_wheel_scroll_step_is_three_lines():
    """一次滚轮 = 3 行(官方聊天列表的手感),不是 1 行也不是一整屏。"""
    widget = _widget(_wall(40))
    step = widget._line_height() * 3
    _wheel(widget, 120)
    assert widget.scroll_offset() == pytest.approx(step)


def test_wheel_never_scrolls_above_oldest_row():
    widget = _widget(_wall(40))
    for _ in range(60):
        _wheel(widget, 120)
    assert widget.scroll_offset() == pytest.approx(widget.max_scroll())
    widget.grab()
    assert "第 0 条" in _visible_texts(widget), "翻到顶应能看到最旧一条"


def test_wheel_with_no_delta_is_ignored():
    widget = _widget(_wall(40))
    ev = _wheel(widget, 0)
    assert ev.isAccepted() is False


# --- 跟随/离底 ---


def test_scrolling_up_is_not_knocked_back_by_new_message():
    """回归:往上翻时来新弹幕,内容不能自己往上漂(offset 要跟着底部一起长)。"""
    widget = _widget(_wall(40))
    _wheel(widget, 120)
    widget.grab()
    first_row = _visible_texts(widget)[0]

    wall = widget._wall
    wall.add(Danmaku(type="chat", name="新人", content="刚来"))
    widget.update_wall(wall)
    widget.grab()
    assert widget.is_following() is False, "来了新弹幕也该继续停在原处"
    assert _visible_texts(widget)[0] == first_row, "视野首行不该因为新弹幕而变化"


def test_scroll_to_bottom_resumes_following():
    widget = _widget(_wall(40))
    _wheel(widget, 120)
    widget.scroll_to_bottom()
    assert widget.scroll_offset() == 0.0
    assert widget.is_following() is True


def test_scroll_to_top_shows_oldest():
    widget = _widget(_wall(40))
    widget.scroll_to_top()
    assert widget.scroll_offset() == pytest.approx(widget.max_scroll())
    widget.grab()
    assert "第 0 条" in _visible_texts(widget)


def test_replacing_wall_resets_scroll():
    """设置里改了行数上限 → 墙被换掉:旧偏移没有意义,回到跟随最新。"""
    widget = _widget(_wall(40))
    _wheel(widget, 120)
    assert widget.scroll_offset() > 0
    widget.update_wall(_wall(10))
    assert widget.scroll_offset() == 0.0


# --- 滚动条 ---


def test_scrollbar_handle_tracks_offset():
    widget = _widget(_wall(40))
    widget.grab()
    vp = widget._last_vp
    at_bottom = widget._scrollbar_handle(vp)
    assert at_bottom is not None
    widget.scroll_to_top()
    widget.grab()
    vp = widget._last_vp
    at_top = widget._scrollbar_handle(vp)
    assert at_top is not None
    assert at_top.y() < at_bottom.y(), "翻到顶时滑块应在上方"
    assert at_top.x() == pytest.approx(at_bottom.x()), "滑块横向不随滚动移动"


def test_dragging_scrollbar_changes_offset():
    widget = _widget(_wall(40))
    widget.grab()
    vp = widget._last_vp
    track = widget._scrollbar_track()
    x = track.center().x()
    widget.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, widget, x, track.center().y()))
    assert widget._scrollbar_drag is not None
    assert widget.scroll_offset() > 0, "点轨道中间应跳到中间位置"
    widget.mouseMoveEvent(
        _mouse(QEvent.Type.MouseMove, widget, x, track.top() + 4, Qt.MouseButton.LeftButton)
    )
    assert widget.scroll_offset() == pytest.approx(vp.max_offset), "拖到顶 = 看最旧"
    widget.mouseReleaseEvent(
        _mouse(QEvent.Type.MouseButtonRelease, widget, x, track.top() + 4, Qt.MouseButton.NoButton)
    )
    assert widget._scrollbar_drag is None


def test_press_elsewhere_is_not_swallowed():
    """墙必须放行空白处的按下:解锁后"按住内容拖窗口"是既有行为,不能被滚动吃掉。"""
    widget = _widget(_wall(40))
    widget.grab()
    ev = _mouse(QEvent.Type.MouseButtonPress, widget, 60, 100)
    widget.mousePressEvent(ev)
    assert ev.isAccepted() is False
    assert widget._scrollbar_drag is None


# --- 回到最新 ---


def test_jump_hint_click_returns_to_latest():
    widget = _widget(_wall(40))
    _wheel(widget, 120)
    widget.grab()
    rect = widget._jump_hint_rect()
    ev = _mouse(QEvent.Type.MouseButtonPress, widget, rect.center().x(), rect.center().y())
    widget.mousePressEvent(ev)
    assert ev.isAccepted() is True
    assert widget.is_following() is True


def test_jump_hint_hidden_while_following():
    widget = _widget(_wall(40))
    widget.grab()
    assert widget._last_vp.following is True
    # 贴底时点那个位置不该被当成"回到最新"
    rect = widget._jump_hint_rect()
    ev = _mouse(QEvent.Type.MouseButtonPress, widget, rect.center().x(), rect.center().y())
    widget.mousePressEvent(ev)
    assert ev.isAccepted() is False


def test_jump_hint_counts_new_messages_below():
    widget = _widget(_wall(40))
    _wheel(widget, 120)
    widget.grab()
    assert widget._rows_below_viewport(widget._last_vp) > 0


# --- 滚动条绘制 ---


def test_scrollbar_is_painted_only_when_scrollable():
    """有可滚内容时右侧应出现滑块像素;内容不满一屏时不该有。"""
    tall = _widget(_wall(40))
    img = tall.grab().toImage()
    track = tall._scrollbar_track()
    x = int(track.center().x())
    hits = [
        y
        for y in range(img.height())
        if img.pixelColor(x, y).alpha() > 0 and img.pixelColor(x, y).lightness() > 0
    ]
    assert hits, "可滚动时应在轨道位置画出滑块"

    short = _widget(_wall(2))
    assert short._scrollbar_handle(short._last_vp) is None


def test_scrollbar_does_not_overlap_text_column():
    """滑块贴在右侧 padding 里,不能压住正文。"""
    widget = _widget(_wall(40))
    widget.grab()
    track = widget._scrollbar_track()
    assert track.right() <= widget.width() - 1
    from bilidm_overlay.danmaku.wall import PANEL_PAD_X

    assert track.left() >= widget.width() - PANEL_PAD_X + 1, "滑块应落在右侧内边距里"


def test_panel_padding_still_applies_at_top():
    """贴底且内容超一屏时,可视区仍从 PANEL_PAD_Y 起(顶部留白没被滚动吃掉)。"""
    widget = _widget(_wall(40))
    widget.grab()
    vp = widget._last_vp
    ys = [y for _row, y in vp.entries]
    assert min(ys) <= PANEL_PAD_Y + 1
    assert max(ys) < widget.height()


# --- 真事件路径(QTest):确认事件真的能到 widget,而不是只有直调 handler 才通 ---


def test_wheel_event_dispatched_by_qt_reaches_handler():
    """走 Qt 的派发路径(QApplication.sendEvent)而不是直调 handler:
    确认 wheelEvent 确实接管了滚轮,没被基类丢掉。"""
    from PyQt6.QtWidgets import QApplication

    widget = _widget(_wall(40))
    widget.show()
    ev = QWheelEvent(
        QPointF(170.0, 130.0),
        QPointF(170.0, 130.0),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, ev)
    assert ev.isAccepted() is True, "滚轮应由本 widget 接管"
    assert widget.scroll_offset() > 0, "真滚轮事件应滚动历史"


def test_qt_click_on_jump_hint_reaches_widget():
    from PyQt6.QtCore import QPoint
    from PyQt6.QtTest import QTest

    widget = _widget(_wall(40))
    widget.show()
    _wheel(widget, 120)
    widget.grab()
    rect = widget._jump_hint_rect()
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(int(rect.center().x()), int(rect.center().y())))
    assert widget.is_following() is True
