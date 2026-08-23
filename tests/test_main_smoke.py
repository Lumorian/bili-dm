import asyncio
import os

# These tests construct real top-level QWidgets (DanmakuWindow) and assert
# offscreen behavior. An inherited QT_QPA_PLATFORM=wayland (this repo is developed
# on a niri session) used to win over setdefault, so the suite silently ran against
# the live compositor and crashed in LayerShellQt when one layer-shell window was
# disposed and another shown. Same fix kotonoha's own suite applies to this
# situation: force offscreen unconditionally and drop Wayland from the session so
# layer-shell bridge probes see a bare environment.
#
# Set at module import, before QApplication is constructed (the fixture below),
# which is when Qt actually reads QT_QPA_PLATFORM.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)

import pytest

from bilidm_overlay.danmaku.model import Danmaku
from bilidm_overlay.window import DanmakuWindow


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _cfg(**kw):
    defaults = {
        "socket": "/tmp/none.sock", "mode": "merged", "rooms": ["bilibili:689422"],
        "width": 420, "max_rows": 30, "ttl_seconds": 60.0, "font_family": "monospace",
        "font_size": 13, "opacity": 0.85, "position": [24, 100], "click_through": True,
        "hide_when_idle_seconds": 0, "no_tray": True,
    }
    defaults.update(kw)
    return type("Cfg", (), defaults)


def test_window_accepts_danmaku(app):
    win = DanmakuWindow(_cfg())
    win.feed(Danmaku(type="chat", platform="bilibili", rid="689422", name="A", content="hi"))
    assert win.row_count() == 1
    win.set_passthrough(True)
    win.set_status("dmnotifier 离线")
    assert win.status_text() == "dmnotifier 离线"
    win.hide_window()


# --- 右上角控制栏(kotonoha 式圆形按钮:🔒 锁 / ⚙ 设置) ---


def test_control_bar_right_aligned_with_lock_left_of_settings(app):
    """按钮右对齐(stretch 在前),锁在最左、设置在最右,与 kotonoha 截图一致。"""
    win = DanmakuWindow(_cfg(click_through=False))
    layout = win._control_bar.layout()
    assert layout.itemAt(0).spacerItem() is not None, "按钮组应右对齐:首个项目是 stretch"
    widgets = [
        layout.itemAt(i).widget()
        for i in range(layout.count())
        if layout.itemAt(i).widget() is not None
    ]
    assert widgets == [win._lock_btn, win._settings_btn]
    # 圆形固定尺寸 22×22(kotonoha CONTROL_BUTTON_STYLE 同款),并已设置图标
    for b in widgets:
        assert (b.minimumSize().width(), b.maximumSize().height()) == (22, 22)
        assert not b.icon().isNull()


def test_lock_button_toggles_passthrough_keeps_controls(app):
    """点击锁按钮翻转点击穿透;锁/设置按钮始终可见(锁定态仅按钮带可点击,
    解锁/设置不依赖托盘)。"""
    win = DanmakuWindow(_cfg(click_through=False))
    assert win._passthrough is False
    assert win._lock_btn.toolTip() == "已解锁"

    win._lock_btn.click()
    assert win._passthrough is True
    assert win._control_bar.isVisibleTo(win) is True, "锁定后按钮必须保持可见,否则无法解锁"
    assert win._lock_btn.toolTip() == "已锁定"

    win._lock_btn.click()
    assert win._passthrough is False
    assert win._control_bar.isVisibleTo(win) is True
    assert win._lock_btn.toolTip() == "已解锁"


def test_control_bar_stays_visible_when_click_through_default(app):
    """默认 click_through=True(穿透):控制栏仍可见——按钮带是可点击的解锁入口。"""
    win = DanmakuWindow(_cfg())
    assert win._passthrough is True
    assert win._control_bar.isVisibleTo(win) is True


def test_control_bar_band_merges_with_card(app):
    """按钮带与卡片同属一个容器(bar 紧贴卡片顶边,间距 0),底色统一由容器绘制。"""
    win = DanmakuWindow(_cfg(click_through=False))
    container = win._control_bar.parent()
    assert container is not win and container is win._wall_widget.parent(), (
        "bar 与卡片应包裹进同一容器,而非各自贴着窗口"
    )
    assert container.layout().indexOf(win._control_bar) < container.layout().indexOf(
        win._wall_widget
    ), "bar 必须在卡片上方"
    # 容器内 bar↔wall 间距为 0:暗色带与卡片连成一块
    assert container.layout().spacing() == 0

    # 卡片底色/圆角由容器 QSS 统一绘制,bar 与 wall 不再各自画背景
    qss = win._container.styleSheet()
    assert "rgba(16, 16, 20," in qss, "容器统一画卡片底色(PANEL_BG)"
    assert "border-radius: 12px" in qss, "容器画圆角(与 niri layer-rule 同步 12px)"
    assert win._control_bar.autoFillBackground() is False
    assert win._wall_widget.autoFillBackground() is False


def test_control_band_height_is_fixed(app):
    """按钮带垂直方向固定为内容高:否则在容器里会被卡片对半分,
    按钮会漂浮在卡片中部(实测再现的 196px 带子问题)。"""
    from PyQt6.QtWidgets import QSizePolicy

    win = DanmakuWindow(_cfg(click_through=False))
    assert win._control_bar.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed, (
        "带子必须固定高度,不能随 VBox 拉伸"
    )
    win.resize(420, 400)
    win.show()
    app.processEvents()
    assert win._control_bar.height() < 40, f"带子实际高度 {win._control_bar.height()}px,应为 28px"


def test_passthrough_toggle_never_recreates_surface(app, monkeypatch):
    """切换穿透必须经输入区域,不得重建 wl_surface:recreate_surface=True →
    setWindowFlags 销毁原生表面,新表面未过 make_overlay 而丢失 layer-shell
    角色,窗口从屏幕上消失(实测:解锁→锁定后窗口不见)。"""
    win = DanmakuWindow(_cfg(click_through=False))
    policies = []
    original = win._host.apply_window_policy

    def _record(policy):
        policies.append(policy)
        return original(policy)

    monkeypatch.setattr(win._host, "apply_window_policy", _record)
    win.set_passthrough(True)
    win.set_passthrough(False)
    assert policies, "穿透切换应走平台输入区域路径"
    assert all(not p.recreate_surface for p in policies), "任何穿透切换都不得重建表面"


def test_unlocked_input_region_covers_whole_window(app, monkeypatch):
    """解锁时输入区域=整个窗口矩形(拖动任意位置/右下角缩放都要可点)。"""
    win = DanmakuWindow(_cfg(click_through=False))
    regions = []
    original = win._platform.set_input_region

    def _record(region):
        regions.append(region)
        return original(region)

    monkeypatch.setattr(win._platform, "set_input_region", _record)
    win.resize(420, 400)
    app.processEvents()
    win.set_passthrough(True)
    assert regions and regions[-1] is not None, "锁定后应传入按钮带矩形"
    win.set_passthrough(False)
    assert regions and regions[-1] is not None, "解锁后应传入窗口矩形"
    assert (regions[-1].width, regions[-1].height) == (420, 400)


def test_locked_input_region_keeps_control_band_clickable(app, monkeypatch):
    """锁定态输入区域=按钮带矩形(而非全穿透):锁/设置按钮保持可点。"""
    win = DanmakuWindow(_cfg(click_through=False))
    regions = []
    original = win._platform.set_input_region

    def _record(region):
        regions.append(region)
        return original(region)

    monkeypatch.setattr(win._platform, "set_input_region", _record)
    win.resize(420, 400)
    app.processEvents()
    win.set_passthrough(True)
    rect = regions[-1]
    assert rect is not None, "锁定不得全穿透:按钮带必须保留可点击"
    assert (
        rect.width == win._control_bar.width() and rect.height == win._control_bar.height()
    ), "锁定态输入区域应覆盖整个按钮带(含锁/设置按钮)"


def test_per_room_filter_drops_other_rooms(app):
    win = DanmakuWindow(_cfg(), room_filter="bilibili:1")
    win.feed(Danmaku(type="chat", platform="bilibili", rid="2", name="A", content="other"))
    win.feed(Danmaku(type="chat", platform="bilibili", rid="1", name="B", content="mine"))
    assert win.row_count() == 1


def test_demo_generator_yields_messages(app):
    from bilidm_overlay import main

    async def _collect() -> None:
        sink: list[Danmaku] = []
        try:
            await asyncio.wait_for(main._demo_gen(sink), timeout=0.05)
        except TimeoutError:
            pass  # demo gen 0.4s/条,0.05s 内只来得及产第一条
        assert len(sink) >= 1
        assert sink[0].type in {"chat", "gift", "superchat", "subscribe"}

    asyncio.run(_collect())


def test_second_instance_exits_when_socket_taken(tmp_path, monkeypatch, caplog):
    """第二份实例启动失败:显式退出(exit 1)、报错明确,且不得删掉第一份实例的活 socket。"""
    import sys

    import qasync
    from PyQt6.QtWidgets import QApplication

    from bilidm_overlay import main
    from bilidm_overlay.client import DanmakuServer
    from bilidm_overlay.config import Config

    sock = str(tmp_path / "inuse.sock")

    async def _bind_first() -> DanmakuServer:
        srv = DanmakuServer(sock, lambda d: None)
        await srv.start()
        return srv

    first = None
    try:
        first = asyncio.run(_bind_first())

        # entry_point 会二次构造 QApplication(套件里已存在)并注册真实信号 handler
        # (会污染 pytest 进程) —— 均在测试内打桩。
        monkeypatch.setattr(main, "QApplication", lambda argv: QApplication.instance() or QApplication(argv))
        monkeypatch.setattr(main, "load", lambda p: Config(socket=sock))
        monkeypatch.setattr(
            qasync.QEventLoop, "add_signal_handler", lambda self, sig, cb: None
        )
        monkeypatch.setattr(sys, "argv", ["bilidm-overlay", "--socket", sock, "--no-tray"])

        with pytest.raises(SystemExit) as exc:
            main.entry_point()
        assert exc.value.code == 1, "启动失败必须以非零退出"
        assert "另一个 overlay 实例" in caplog.text
        assert os.path.exists(sock), "第一份实例的 socket 必须幸存"
    finally:
        if first is not None:
            asyncio.run(first.stop())
        if os.path.exists(sock):
            os.unlink(sock)
