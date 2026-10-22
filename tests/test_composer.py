"""发送栏(Composer)与悬浮窗接线:锁定态、字数、回执、本地回显与去重。

不碰网络:submitter 的 sender 换成假的,或直接把信号打出来验证窗口那一侧的处理。
"""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)

import pytest

from bilidm_overlay.danmaku.model import Danmaku


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _cfg(**kw):
    defaults = {
        "socket": "/tmp/none.sock",
        "mode": "merged",
        "rooms": ["bilibili:689422"],
        "width": 420,
        "height": 400,
        "max_rows": 30,
        "font_family": "monospace",
        "font_size": 13,
        "theme": "dark",
        "opacity": 0.85,
        "position": [24, 100],
        "click_through": False,
        "hide_when_idle_seconds": 0,
        "no_tray": True,
        "send_enabled": True,
        "send_cookie": "",
    }
    defaults.update(kw)
    return type("Cfg", (), defaults)


def _window(app, monkeypatch, **kw):
    from bilidm_overlay import window as window_module

    monkeypatch.setattr(window_module, "save", lambda cfg: None)
    win = window_module.DanmakuWindow(_cfg(**kw))
    win.resize(420, 400)
    app.processEvents()
    return win


# --- Composer 自身 ---


def test_composer_sits_below_wall_inside_card(app, monkeypatch):
    """输入条在卡片底部(弹幕墙之下),与 bar/wall 同属一个容器、间距 0。"""
    win = _window(app, monkeypatch)
    container = win._composer.parent()
    layout = container.layout()
    assert container is win._wall_widget.parent()
    assert layout.indexOf(win._composer) > layout.indexOf(win._wall_widget), "输入条应在弹幕墙下方"
    assert layout.spacing() == 0


def test_composer_disabled_when_locked(app, monkeypatch):
    """锁定(点击穿透)态下输入框只读并提示原因:此时窗口不接键盘焦点。"""
    win = _window(app, monkeypatch, click_through=True)
    composer = win._composer
    assert win._passthrough is True
    assert composer.is_locked() is True
    assert composer.input_edit().isReadOnly() is True
    assert composer.input_edit().placeholderText() == "解锁后可发送弹幕"
    # 解锁后即可输入
    win.set_passthrough(False)
    assert composer.is_locked() is False
    assert composer.input_edit().isReadOnly() is False
    assert "发送" in composer.input_edit().placeholderText()


def test_composer_enforces_official_20_char_limit(app, monkeypatch):
    win = _window(app, monkeypatch)
    composer = win._composer
    composer.input_edit().setText("啊" * 30)
    assert len(composer.text()) == 20, "普通用户弹幕上限 20 字"


def test_composer_shows_live_count(app, monkeypatch):
    win = _window(app, monkeypatch)
    composer = win._composer
    composer.input_edit().setText("abc")
    assert "3/20" in composer._count.text()


def test_composer_enter_submits(app, monkeypatch):
    win = _window(app, monkeypatch)
    got = []
    win._composer.submitted.connect(got.append)
    win._composer.input_edit().setText("hello")
    win._composer.input_edit().returnPressed.emit()
    assert got == ["hello"]


def test_composer_send_button_enabled_only_with_text(app, monkeypatch):
    win = _window(app, monkeypatch)
    button = win._composer.send_button()
    assert button.isEnabled() is False, "空输入不应可点发送"
    win._composer.input_edit().setText("hi")
    assert button.isEnabled() is True


def test_send_bar_hidden_when_disabled_in_config(app, monkeypatch):
    win = _window(app, monkeypatch, send_enabled=False)
    assert win._composer.isVisibleTo(win) is False


# --- 窗口侧的发送流程 ---


def _fake_target():
    from bilidm_overlay.sender import SendTarget

    return SendTarget("bilibili", "689422", "SESSDATA=s; bili_jct=csrf")


def test_submit_without_csrf_is_explained_locally(app, monkeypatch):
    """缺 bili_jct 时不要打网络:本地就说清原因(否则只会收到一个 -111)。"""
    from bilidm_overlay.sender import SendTarget, parse_csrf

    win = _window(app, monkeypatch)
    monkeypatch.setattr(
        "bilidm_overlay.window.target_for",
        lambda cfg, room_filter=None, observed_room=None: SendTarget("bilibili", "689422", "SESSDATA=only"),
    )
    submitted = []
    monkeypatch.setattr(
        win._submitter, "submit", lambda target, text: submitted.append((target, text)) or True
    )
    win._on_submit("hello")
    assert submitted == [], "缺 csrf 不得发起请求"
    assert "bili_jct" in win._composer.hint_text()
    assert parse_csrf("SESSDATA=only") == ""


def test_submit_without_room_is_explained_locally(app, monkeypatch):
    """连一条弹幕都还没收到时,确实无从知道发到哪 —— 这时才该提示去设置房间。"""
    win = _window(app, monkeypatch)
    monkeypatch.setattr(
        "bilidm_overlay.window.target_for", lambda cfg, room_filter=None, observed_room=None: None
    )
    win._on_submit("hello")
    assert "房间" in win._composer.hint_text() and "弹幕" in win._composer.hint_text()


def test_submit_registers_echo_before_network(app, monkeypatch):
    """回推可能比 HTTP 响应先到:期望必须在提交那一刻就登记。"""
    win = _window(app, monkeypatch)
    monkeypatch.setattr("bilidm_overlay.window.target_for", lambda cfg, room_filter=None, observed_room=None: _fake_target())
    seen = {}

    def _submit(target, text):
        seen["pending_at_submit"] = win._echo.pending_count()
        return True

    monkeypatch.setattr(win._submitter, "submit", _submit)
    win._on_submit("hello")
    assert seen["pending_at_submit"] == 1
    assert win._composer.is_busy() is True, "发送中要挡住连点"


def test_throttled_submit_withdraws_echo(app, monkeypatch):
    """被节流时撤掉期望:否则后来一条内容相同的正常弹幕会被误吞。"""
    win = _window(app, monkeypatch)
    monkeypatch.setattr("bilidm_overlay.window.target_for", lambda cfg, room_filter=None, observed_room=None: _fake_target())
    monkeypatch.setattr(win._submitter, "submit", lambda target, text: False)
    win._on_submit("hello")
    assert win._echo.pending_count() == 0
    assert win._composer.is_busy() is False


def test_sent_message_echoes_locally_with_identity(app, monkeypatch):
    """发送成功立刻本地回显(官方弹幕姬同样即时上屏),并回填自己的 uid。"""
    from bilidm_overlay.submit import Identity

    win = _window(app, monkeypatch)
    win._on_sent("hello", Identity(uid="42", name="我", avatar=""), _fake_target())
    rows = win._wall.snapshot()
    assert len(rows) == 1
    assert (rows[0].msg.content, rows[0].msg.name, rows[0].msg.uid) == ("hello", "我", "42")
    assert win._composer.text() == "", "发送成功后清空输入框"
    assert "已发送" in win._composer.hint_text()


def test_websocket_push_of_own_message_is_not_duplicated(app, monkeypatch):
    """自己那条被 ws 推回来时不再插第二行(否则每条都显示两遍)。"""
    from bilidm_overlay.submit import Identity

    win = _window(app, monkeypatch)
    win._echo.expect("hello")
    win._on_sent("hello", Identity(uid="42", name="我", avatar=""), _fake_target())
    assert win.row_count() == 1
    win.feed(Danmaku(type="chat", platform="bilibili", rid="689422", name="我",
                     content="hello", uid="42"))
    assert win.row_count() == 1, "自己的回推不应再插一行"


def test_repeated_text_after_window_expires_still_shows(app, monkeypatch):
    from bilidm_overlay.submit import Identity

    win = _window(app, monkeypatch)
    win._echo = type(win._echo)(window=0.0)  # 期望立刻过期:模拟回推压根没来
    win._on_sent("666", Identity(uid="42", name="我", avatar=""), _fake_target())
    win.feed(Danmaku(type="chat", name="别人", content="666", uid="99"))
    assert win.row_count() == 2, "别人刷同一句话必须照常显示"


def test_send_failure_is_shown_and_keeps_text(app, monkeypatch):
    win = _window(app, monkeypatch)
    win._composer.input_edit().setText("hello")
    win._composer.set_busy(True)
    win._on_send_failed("hello", "弹幕发送太频繁,稍等一下(1003212)")
    assert "太频繁" in win._composer.hint_text()
    assert win._composer.is_busy() is False
    assert win._composer.text() == "hello", "失败不要把用户打的字清掉"
    assert win._composer.send_button().isEnabled() is True


def test_unlock_enables_keyboard_interactivity(app, monkeypatch):
    """层壳表面默认 KeyboardInteractivityNone:不解锁就永远打不进字。"""
    calls = []
    win = _window(app, monkeypatch, click_through=True)
    monkeypatch.setattr(
        "bilidm_overlay.window.apply_keyboard_interactivity",
        lambda platform, host, enabled: calls.append(enabled) or True,
    )
    win.set_passthrough(False)
    assert calls[-1] is True, "解锁后必须把键盘交互打开,否则输入框收不到按键"
    win.set_passthrough(True)
    assert calls[-1] is False, "锁定(穿透)时别抢键盘焦点"


def test_send_bar_height_is_bounded(app, monkeypatch):
    """输入条固定高度:不能把弹幕墙挤成一条缝。"""
    win = _window(app, monkeypatch)
    win.show()
    app.processEvents()
    assert win._composer.height() < 60, f"输入条高度 {win._composer.height()}px 过高"
    assert win._wall_widget.height() > win._composer.height() * 4


def test_composer_theme_and_font_follow_settings(app, monkeypatch):
    """设置里改主题/字号后,输入条跟着变(否则深色卡片里躺一条浅色输入框)。"""
    win = _window(app, monkeypatch)
    win._composer.set_theme("light")
    assert "#F6F7F8" in win._composer.styleSheet() or "#61666D" in win._composer.styleSheet()
    win._composer.set_font("monospace", 18)
    assert win._composer.input_edit().font().pointSize() == 18


def test_settings_dialog_exposes_send_fields(app):
    from bilidm_overlay.config import Config
    from bilidm_overlay.settings import SettingsDialog

    cfg = Config()
    cfg.send_enabled = False
    cfg.send_cookie = "SESSDATA=s; bili_jct=c"
    dialog = SettingsDialog(None, cfg)
    assert dialog.send_values() == (False, "SESSDATA=s; bili_jct=c")
    # cookie 缺 bili_jct 时当场提醒(否则点发送只会在网络那里撞 -111)
    dialog._send_cookie.setText("SESSDATA=only")
    assert "bili_jct" in dialog._send_note.text()
    dialog._send_cookie.setText("")
    assert "dmnotifier" in dialog._send_note.text()
    dialog.close()


def test_demo_mode_hides_send_bar():
    """演示流是假消息,发送栏留着只会给一个必然失败的入口。"""
    import argparse

    from bilidm_overlay.config import Config, merge_cli

    cfg = merge_cli(Config(), argparse.Namespace(no_send=True))
    assert cfg.send_enabled is False


# --- 房间来自"正在收的弹幕"(没有 --room / 配置也能发) ---


def test_observed_room_lets_you_send_without_any_config(app, monkeypatch):
    """回归:用户没配任何房间却在收弹幕(dmnotifier history 订阅的),原先会被拦下
    "没有可发送的房间" —— 能看不能发毫无道理。弹幕自带 platform/rid,就该照着发。"""
    from bilidm_overlay.sender import resolve_target

    win = _window(app, monkeypatch, rooms=[], send_cookie="SESSDATA=s; bili_jct=c")
    win.feed(Danmaku(type="chat", platform="bilibili", rid="1813444381", name="A", content="hi"))
    assert win._observed_room == "bilibili:1813444381"

    seen = {}
    monkeypatch.setattr(
        "bilidm_overlay.window.target_for",
        lambda cfg, room_filter=None, observed_room=None: seen.update(observed=observed_room)
        or resolve_target(cfg, room_filter, observed_room),
    )
    monkeypatch.setattr(win._submitter, "submit", lambda target, text: seen.update(target=target) or True)
    win._on_submit("hello")
    assert seen["observed"] == "bilibili:1813444381"
    assert seen["target"].rid == "1813444381", "应发到正在收弹幕的那个房间"


def test_observed_room_prefers_bilibili_in_merged_mode(app, monkeypatch):
    """合并模式同时收多个房间时,发送目标要稳定在 B 站房间上(发送接口只有 B 站有)。"""
    win = _window(app, monkeypatch, rooms=[])
    win.feed(Danmaku(type="chat", platform="douyu", rid="9999", name="A", content="a"))
    win.feed(Danmaku(type="chat", platform="bilibili", rid="689422", name="B", content="b"))
    win.feed(Danmaku(type="chat", platform="douyu", rid="9999", name="C", content="c"))
    assert win._observed_room == "bilibili:689422", "定下 B 站房间后不该被别的平台顶掉"


def test_config_room_still_wins_over_observed(app, monkeypatch):
    """配置过的房间优先于"恰好收到的第一个房间":用户明确配的就是他想要的那个。"""
    from bilidm_overlay.sender import resolve_target

    win = _window(app, monkeypatch, rooms=["bilibili:689422"])
    win.feed(Danmaku(type="chat", platform="bilibili", rid="123456", name="A", content="hi"))
    target = resolve_target(win._cfg, None, win._observed_room)
    assert target.rid == "689422"


def test_send_without_cookie_explains_that_reading_needs_no_login(app, monkeypatch):
    """收弹幕不需要登录(匿名也能看),发才需要 —— 提示必须点明,否则像 bug。"""
    from bilidm_overlay.sender import SendTarget

    win = _window(app, monkeypatch, rooms=[])
    win.feed(Danmaku(type="chat", platform="bilibili", rid="689422", name="A", content="hi"))
    monkeypatch.setattr(
        "bilidm_overlay.window.target_for",
        lambda cfg, room_filter=None, observed_room=None: SendTarget("bilibili", "689422", ""),
    )
    win._on_submit("hello")
    hint = win._composer.hint_text()
    assert "bili_jct" in hint
    assert "看弹幕不用登录" in hint, "得解释清「能看不能发」的原因"


# --- 翻阅历史:键盘入口与"翻着看时别自动隐藏" ---


def test_pageup_pagedown_scroll_history(app, monkeypatch):
    """解锁后 PageUp/PageDown 一屏、Home/End 到两端。"""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent

    win = _window(app, monkeypatch)
    for i in range(60):
        win.feed(Danmaku(type="chat", name=f"u{i}", content=f"第 {i} 条"))
    win.show()
    app.processEvents()
    assert win.is_following_latest() is True

    def _key(k):
        return QKeyEvent(QKeyEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier)

    win.keyPressEvent(_key(Qt.Key.Key_PageUp))
    assert win.scroll_offset() > 0, "PageUp 应往上翻一屏"
    win.keyPressEvent(_key(Qt.Key.Key_End))
    assert win.is_following_latest() is True, "End 回到最新"
    win.keyPressEvent(_key(Qt.Key.Key_Home))
    assert abs(win.scroll_offset() - win._wall_widget.max_scroll()) < 0.5
    win.keyPressEvent(_key(Qt.Key.Key_PageDown))
    assert win.is_following_latest() is False, "PageDown 往下翻一屏"


def test_idle_hide_waits_while_user_reads_history(app, monkeypatch):
    """往上翻着看历史时不能把窗口隐藏:那等于把用户正在读的书合上。"""
    import time

    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent

    clock = {"t": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])
    win = _window(app, monkeypatch, hide_when_idle_seconds=10)
    for i in range(60):
        win.feed(Danmaku(type="chat", name=f"u{i}", content=f"第 {i} 条"))
    win.show()
    app.processEvents()
    win.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_PageUp, Qt.KeyboardModifier.NoModifier)
    )
    clock["t"] = 5000.0  # 远超空闲阈值
    win._tick()
    assert win.isVisible() is True, "翻着历史时不该被空闲隐藏"
    win.scroll_to_bottom()
    win._tick()
    assert win.isVisible() is False, "回到底部后空闲隐藏恢复正常"


def test_scroll_input_does_not_lose_drag(app, monkeypatch):
    """滚动用的按下/移动不能吞掉窗口拖拽(解锁后整块面板可拖是既有行为)。"""
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    win = _window(app, monkeypatch, click_through=False)
    for i in range(60):
        win.feed(Danmaku(type="chat", name=f"u{i}", content=f"第 {i} 条"))
    win.show()
    app.processEvents()
    wall = win._wall_widget
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(wall.width() / 2, wall.height() / 2),
        QPointF(300.0, 300.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    wall.mousePressEvent(ev)
    assert ev.isAccepted() is False, "空白处按下必须放行,交给窗口拖拽"
