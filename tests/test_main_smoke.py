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
