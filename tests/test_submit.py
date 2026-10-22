"""发送推进器(节流/忙态/后台线程结果回主线程)与键盘交互桥的接线。

sender 换成假的:这里测的是"什么时候允许发、结果怎么回到界面",不是 HTTP 形态
(那条路径在 test_sender.py 里用真 server 走过)。
"""

import os
import threading

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)

import pytest

from bilidm_overlay.sender import Identity, SendError, SendTarget
from bilidm_overlay.submit import DanmakuSubmitter, throttle_remaining

TARGET = SendTarget("bilibili", "689422", "SESSDATA=s; bili_jct=c")


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


ME = Identity("42", "我", "")


class _FakeSender:
    def __init__(self, error: SendError | None = None, identity: Identity | None = ME):
        self.sent: list[tuple[SendTarget, str]] = []
        self._error = error
        self._identity = identity
        self.identity_calls = 0

    def send(self, target, text):
        if self._error is not None:
            raise self._error
        self.sent.append((target, text))

    def fetch_identity(self, cookie):
        self.identity_calls += 1
        return self._identity


def _wait_until(app, predicate, timeout=5.0):
    """转 Qt 事件循环直到条件成立(工作线程的结果靠信号回主线程)。"""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        threading.Event().wait(0.01)
    return False


# --- 纯逻辑 ---


def test_throttle_remaining_counts_down():
    assert throttle_remaining(None, 100.0) == 0.0, "没发过就没限制"
    assert throttle_remaining(100.0, 100.5, interval=1.5) == pytest.approx(1.0)
    assert throttle_remaining(100.0, 102.0, interval=1.5) == 0.0


# --- 推进器 ---


def test_submit_runs_in_background_and_reports_success(app):
    sender = _FakeSender()
    submitter = DanmakuSubmitter(sender=sender)
    results = []
    submitter.submitted_ok.connect(lambda text, ident, target: results.append((text, ident, target)))
    assert submitter.submit(TARGET, "hello") is True
    assert submitter.is_busy() is True
    assert _wait_until(app, lambda: bool(results))
    assert sender.sent == [(TARGET, "hello")]
    assert results[0][0] == "hello" and results[0][1].uid == "42"
    assert submitter.is_busy() is False


def test_submit_is_serialised_by_throttle(app):
    submitter = DanmakuSubmitter(sender=_FakeSender(), clock=lambda: 100.0)
    errors = []
    submitter.failed.connect(lambda text, msg: errors.append(msg))
    assert submitter.submit(TARGET, "one") is True
    # 同一条还在发:先拒掉(忙)
    assert submitter.submit(TARGET, "two") is False
    assert "还在发送" in errors[-1]
    assert _wait_until(app, lambda: not submitter.is_busy())
    # 忙完了但还没过节流窗:拒掉并说明还要等多久
    assert submitter.submit(TARGET, "three") is False
    assert "太频繁" in errors[-1]
    assert submitter.remaining() == pytest.approx(1.5)


def test_submit_reports_send_error_with_text(app):
    sender = _FakeSender(error=SendError(-412, "请求被拦截"))
    submitter = DanmakuSubmitter(sender=sender)
    failures = []
    submitter.failed.connect(lambda text, msg: failures.append((text, msg)))
    assert submitter.submit(TARGET, "hello") is True
    assert _wait_until(app, lambda: bool(failures))
    assert failures[0][0] == "hello", "失败要带回原文,界面据此撤掉回显期望"
    assert "拦截" in failures[0][1]
    assert submitter.is_busy() is False


def test_submit_survives_unexpected_exception(app):
    class _Boom:
        def send(self, target, text):
            raise RuntimeError("boom")

        def fetch_identity(self, cookie):
            return None

    submitter = DanmakuSubmitter(sender=_Boom())
    failures = []
    submitter.failed.connect(lambda text, msg: failures.append(msg))
    assert submitter.submit(TARGET, "hello") is True
    assert _wait_until(app, lambda: bool(failures))
    assert "boom" in failures[0], "工作线程里的异常必须回到界面,不能静默消失"
    assert submitter.is_busy() is False


def test_identity_is_fetched_once_per_cookie(app):
    sender = _FakeSender()
    submitter = DanmakuSubmitter(sender=sender, clock=lambda: 0.0)
    for text in ("a", "b"):
        submitter.submit(TARGET, text)
        assert _wait_until(app, lambda: not submitter.is_busy())
    assert sender.identity_calls == 1, "自己的 uid/昵称缓存一次就够,别每条弹幕都问一次"


# --- 键盘交互 ---


class _Host:
    def __init__(self, pointer=1234):
        self._pointer = pointer

    def native_window_pointer(self):
        return self._pointer


def test_keyboard_prefers_adapter_method():
    from bilidm_overlay.keyboard import apply_keyboard_interactivity

    calls = []

    class _Platform:
        def set_keyboard_interactivity(self, enabled):
            calls.append(enabled)

    assert apply_keyboard_interactivity(_Platform(), _Host(), True) is True
    assert calls == [True]


def test_keyboard_falls_back_to_bridge():
    """kotonoha 的适配器还没把该项放进协议:退到桥(controller)直调。"""
    from bilidm_overlay.keyboard import apply_keyboard_interactivity

    calls = []

    class _Bridge:
        def set_keyboard_interactivity(self, pointer, enabled):
            calls.append((pointer, enabled))

    class _Platform:
        _controller = _Bridge()

    assert apply_keyboard_interactivity(_Platform(), _Host(99), False) is True
    assert calls == [(99, False)]


def test_keyboard_noop_without_bridge_or_pointer():
    """普通顶层窗(X11/无层壳)本来就收键盘:什么都不做,也不抛。"""
    from bilidm_overlay.keyboard import apply_keyboard_interactivity

    class _Platform:
        pass

    assert apply_keyboard_interactivity(_Platform(), _Host(), True) is False
    assert apply_keyboard_interactivity(_Platform(), _Host(pointer=None), True) is False


def test_keyboard_swallows_bridge_errors():
    """打不了字是体验问题,不该把悬浮窗带崩。"""
    from bilidm_overlay.keyboard import apply_keyboard_interactivity

    class _Bridge:
        def set_keyboard_interactivity(self, pointer, enabled):
            raise RuntimeError("surface gone")

    class _Platform:
        _controller = _Bridge()

    assert apply_keyboard_interactivity(_Platform(), _Host(), True) is False


# --- worker 本体(直接在主线程跑一遍:QThreadPool 的线程不在覆盖率采样里) ---


def test_worker_emits_done_with_identity():
    from bilidm_overlay.submit import _SendWorker, _WorkerSignals

    sender = _FakeSender()
    signals = _WorkerSignals()
    got = []
    signals.done.connect(lambda text, ident, target: got.append((text, ident, target)))
    _SendWorker(sender, TARGET, "hello", signals, {}).run()
    assert sender.sent == [(TARGET, "hello")]
    assert got == [("hello", ME, TARGET)]


def test_worker_reuses_cached_identity():
    from bilidm_overlay.submit import _SendWorker, _WorkerSignals

    sender = _FakeSender()
    cache = {}
    _SendWorker(sender, TARGET, "a", _WorkerSignals(), cache).run()
    _SendWorker(sender, TARGET, "b", _WorkerSignals(), cache).run()
    assert sender.identity_calls == 1
    assert cache[TARGET.cookie] == ME


def test_worker_reports_send_error():
    from bilidm_overlay.submit import _SendWorker, _WorkerSignals

    signals = _WorkerSignals()
    failures = []
    signals.failed.connect(lambda text, msg: failures.append((text, msg)))
    _SendWorker(_FakeSender(error=SendError(-111, "csrf 校验失败")), TARGET, "hi", signals, {}).run()
    assert failures == [("hi", "csrf 校验失败")]


def test_worker_survives_identity_lookup_failure():
    """身份只是回显用的昵称/头像:取不到也要把"已发送"报回去。"""

    class _NoIdentity(_FakeSender):
        def fetch_identity(self, cookie):
            raise SendError(0, "network down")

    from bilidm_overlay.submit import _SendWorker, _WorkerSignals

    signals = _WorkerSignals()
    got = []
    signals.done.connect(lambda text, ident, target: got.append(ident))
    _SendWorker(_NoIdentity(), TARGET, "hi", signals, {}).run()
    assert got == [None]
