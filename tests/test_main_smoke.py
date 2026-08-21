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
