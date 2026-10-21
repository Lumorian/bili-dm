"""拖动/缩放的位置记账:layer-shell 下客户端查不到窗口位置(move() 是 no-op,
win.pos() 只报请求值),位置只能自己算——算错的后果是拖动时面板不跟手甚至跳走。"""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _cfg(**kw):
    defaults = {
        "socket": "/tmp/none.sock",
        "mode": "merged",
        "rooms": [],
        "width": 400,
        "height": 300,
        "max_rows": 30,
        "font_family": "monospace",
        "font_size": 13,
        "opacity": 0.85,
        "position": [100, 200],
        "click_through": False,
        "hide_when_idle_seconds": 0,
        "no_tray": True,
    }
    defaults.update(kw)
    return type("Cfg", (), defaults)


def _event(kind, local, glob, buttons=Qt.MouseButton.LeftButton):
    return QMouseEvent(
        kind,
        QPointF(*local),
        QPointF(*glob),
        Qt.MouseButton.LeftButton,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def _window(app, monkeypatch, **kw):
    """构造窗口并把 save() 打桩:测试不能写用户的配置文件。"""
    from bilidm_overlay import window as window_module

    saved = []
    monkeypatch.setattr(window_module, "save", lambda cfg: saved.append(list(cfg.position)))
    win = window_module.DanmakuWindow(_cfg(**kw))
    win.resize(400, 300)
    app.processEvents()
    return win, saved


def _press(win, local, glob):
    win.mousePressEvent(_event(QEvent.Type.MouseButtonPress, local, glob))


def _move(win, local, glob):
    win.mouseMoveEvent(_event(QEvent.Type.MouseMove, local, glob))


def _release(win, local, glob):
    win.mouseReleaseEvent(_event(QEvent.Type.MouseButtonRelease, local, glob, Qt.MouseButton.NoButton))


def test_drag_follows_pointer_displacement(app, monkeypatch):
    """拖动=窗口跟手的一比一映射:指针从按下点移多远,窗口就移多远。"""
    win, _ = _window(app, monkeypatch)
    _press(win, (150.0, 150.0), (250.0, 350.0))
    _move(win, (150.0, 150.0), (290.0, 380.0))
    assert (win._layer_pos.x(), win._layer_pos.y()) == (140, 230), "位移应等于指针位移(+40,+30)"
    _move(win, (150.0, 150.0), (330.0, 400.0))
    assert (win._layer_pos.x(), win._layer_pos.y()) == (180, 250), "继续拖动必须从按下点累计,不是每帧相加"
    _release(win, (150.0, 150.0), (330.0, 400.0))


def test_drag_does_not_depend_on_local_pointer_moving(app, monkeypatch):
    """关键回归:面板跟手后,本地坐标几乎不动。用本地增量记账会让面板原地不动或越拖越少
    ——原来"任意位置拖不动"就是这条路径。"""
    win, _ = _window(app, monkeypatch)
    start_local = (150.0, 150.0)
    _press(win, start_local, (250.0, 350.0))
    for step in range(1, 6):
        # 本地坐标恒定(窗口跟着指针走),只有全局坐标在变
        _move(win, start_local, (250.0 + step * 20, 350.0 + step * 10))
    assert (win._layer_pos.x(), win._layer_pos.y()) == (200, 250)
    _release(win, start_local, (350.0, 400.0))


def test_drag_saves_position_when_client_positioning_works(app, monkeypatch):
    win, saved = _window(app, monkeypatch)
    if not win._platform.capabilities.client_positioning:
        pytest.skip("本平台不允许客户端定位,位置记账无意义")
    _press(win, (150.0, 150.0), (250.0, 350.0))
    _move(win, (150.0, 150.0), (270.0, 360.0))
    _release(win, (150.0, 150.0), (270.0, 360.0))
    assert saved and saved[-1] == [120, 210], "松开时应把新位置写回配置"


def test_drag_is_ignored_while_locked(app, monkeypatch):
    """锁定(穿透)态下窗口不该响应拖动:否则点击穿透区域里按一下就把面板挪走。"""
    win, saved = _window(app, monkeypatch, click_through=True)
    _press(win, (150.0, 150.0), (250.0, 350.0))
    assert win._dragging is False
    _move(win, (150.0, 150.0), (300.0, 400.0))
    assert (win._layer_pos.x(), win._layer_pos.y()) == (100, 200)
    assert saved == []


def test_press_in_resize_corner_resizes_instead_of_dragging(app, monkeypatch):
    """右下角是缩放手柄,不是拖动起点。"""
    win, _ = _window(app, monkeypatch)
    size = win.size()
    _press(win, (float(size.width() - 4), float(size.height() - 4)), (250.0, 350.0))
    assert win._resizing is True and win._dragging is False
    _move(win, (float(size.width() + 30), float(size.height() + 20)), (280.0, 370.0))
    assert win.width() > size.width() and win.height() > size.height()
    _release(win, (float(size.width()), float(size.height())), (280.0, 370.0))


def test_resize_never_shrinks_below_minimum(app, monkeypatch):
    from bilidm_overlay.window import MIN_H, MIN_W

    win, _ = _window(app, monkeypatch)
    size = win.size()
    _press(win, (float(size.width() - 4), float(size.height() - 4)), (250.0, 350.0))
    _move(win, (0.0, 0.0), (0.0, 0.0))
    assert win.width() >= MIN_W and win.height() >= MIN_H
    _release(win, (0.0, 0.0), (0.0, 0.0))


def test_startup_restores_saved_position(app, monkeypatch):
    """位置存了就得用:layer-shell 下 move() 无效,必须经平台 move_to 设锚点。"""
    from bilidm_overlay import window as window_module

    calls = []
    original = window_module.DefaultOverlayPlatformFactory

    class _SpyPlatform:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def move_to(self, position):
            calls.append((position.x, position.y))
            return self._inner.move_to(position)

    def _factory(controller):
        def build(host):
            return _SpyPlatform(original(controller)(host))

        return build

    monkeypatch.setattr(window_module, "DefaultOverlayPlatformFactory", _factory)
    monkeypatch.setattr(window_module, "save", lambda cfg: None)
    window_module.DanmakuWindow(_cfg(position=[321, 654]))
    assert calls == [(321, 654)], f"启动应只按配置恢复一次位置,实际 {calls}"


def test_startup_skips_position_restore_when_platform_cannot(app, monkeypatch):
    """平台明确"不接受客户端定位"时不必白调 move_to(它只会返回失败)。"""
    from dataclasses import replace

    from bilidm_overlay import window as window_module

    calls = []

    class _NoPositioning:
        """只覆盖能力声明与 move_to,其余全交给真正的平台适配器。"""

        def __init__(self, inner):
            object.__setattr__(self, "_inner", inner)

        def __getattr__(self, name):
            return getattr(self._inner, name)

        @property
        def capabilities(self):
            return replace(self._inner.capabilities, client_positioning=False)

        def move_to(self, position):
            calls.append(position)
            return self._inner.move_to(position)

    original = window_module.DefaultOverlayPlatformFactory
    monkeypatch.setattr(
        window_module,
        "DefaultOverlayPlatformFactory",
        lambda controller: (lambda host: _NoPositioning(original(controller)(host))),
    )
    monkeypatch.setattr(window_module, "save", lambda cfg: None)
    win = window_module.DanmakuWindow(_cfg(position=[321, 654]))
    assert win._platform.capabilities.client_positioning is False, "测试装置应生效"
    assert calls == [], "不接受客户端定位时不该调 move_to"


# --- 位置可用性:历史配置里的坏坐标不得把面板送到屏幕外 ---


def test_position_inside_a_screen_is_kept(app, monkeypatch):
    from PyQt6.QtCore import QPoint

    win, _ = _window(app, monkeypatch)
    screen = win.screen().geometry()
    inside = QPoint(screen.x() + 40, screen.y() + 60)
    assert win._usable_position(inside.x(), inside.y()) == inside


def test_offscreen_position_falls_back_and_warns(app, monkeypatch, caplog):
    """拖动曾把位置算成绝对坐标(实测配置里出现过 2293818),照搬会把窗口放到
    屏幕外——对用户就是"窗口不见了"。落在所有屏幕外时退回默认锚点。"""
    from PyQt6.QtCore import QPoint

    win, _ = _window(app, monkeypatch)
    with caplog.at_level("WARNING"):
        pos = win._usable_position(2293818, 2243365)
    assert pos == QPoint(24, 100)
    assert "不在任何屏幕内" in caplog.text


def test_startup_uses_clamped_position(app, monkeypatch):
    """恢复位置走的是收口后的值:坏坐标不该传到平台。"""
    from bilidm_overlay import window as window_module

    calls = []

    class _SpyPlatform:
        def __init__(self, inner):
            object.__setattr__(self, "_inner", inner)

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def move_to(self, position):
            calls.append((position.x, position.y))
            return self._inner.move_to(position)

    original = window_module.DefaultOverlayPlatformFactory
    monkeypatch.setattr(
        window_module,
        "DefaultOverlayPlatformFactory",
        lambda controller: (lambda host: _SpyPlatform(original(controller)(host))),
    )
    monkeypatch.setattr(window_module, "save", lambda cfg: None)
    win = window_module.DanmakuWindow(_cfg(position=[2293818, 2243365]))
    assert calls and calls[0] == (24, 100), f"坏坐标应被收口,实际 {calls}"
    assert (win._layer_pos.x(), win._layer_pos.y()) == (24, 100)
