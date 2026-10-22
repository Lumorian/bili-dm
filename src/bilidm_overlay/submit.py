"""把「点发送」接到网络请求上:后台线程执行 + 结果回主线程 + 本地节流。

`sender.BilibiliSender` 是同步 urllib,直接在主线程里调会掐断 30ms 的重绘节奏
(一次 5s 超时就等于 166 帧卡住)。这里用 QThreadPool 把请求丢到工作线程,结果经
信号回到主线程 —— 界面只在主线程改。

节流放在这一层而不是 sender 里:它是"这台机器上这个进程"的策略(连点保护),与
"接口是否接受"无关,而且没有网络也能测。自己的身份(nav 接口)按 cookie 缓存一次,
省掉每条弹幕都多打一次请求。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from .config import Config
from .sender import BilibiliSender, Identity, SendError, SendTarget, resolve_target

logger = logging.getLogger(__name__)

MIN_INTERVAL_S = 1.5  # B 站大约 1 条/2s;本地先挡住连点,别等风控回 -412


def throttle_remaining(last_at: float | None, now: float, interval: float = MIN_INTERVAL_S) -> float:
    """还要等几秒才能再发(0 表示现在就可以);纯函数,便于测试。"""
    if last_at is None:
        return 0.0
    remaining = interval - (now - last_at)
    return remaining if remaining > 0 else 0.0


class _WorkerSignals(QObject):
    done = pyqtSignal(str, object, object)  # (text, Identity | None, SendTarget)
    failed = pyqtSignal(str, str)  # (text, message);text 为空表示没提交出去(节流/忙)


class _SendWorker(QRunnable):
    """在线程池里跑一次发送;结果一律经信号送回主线程。"""

    def __init__(
        self,
        sender: BilibiliSender,
        target: SendTarget,
        text: str,
        signals: _WorkerSignals,
        identity_cache: dict[str, Identity | None],
    ) -> None:
        super().__init__()
        self._sender = sender
        self._target = target
        self._text = text
        self._signals = signals
        self._identity_cache = identity_cache

    def run(self) -> None:
        try:
            self._sender.send(self._target, self._text)
        except SendError as exc:
            self._signals.failed.emit(self._text, exc.message)
            return
        except Exception as exc:  # 工作线程里的任何异常都必须回到界面,不能让它静默消失
            logger.exception("发送弹幕时出现未预期错误")
            self._signals.failed.emit(self._text, f"发送失败:{exc}")
            return
        identity = self._identity()
        self._signals.done.emit(self._text, identity, self._target)

    def _identity(self) -> Identity | None:
        """自己的身份(只为本地回显的昵称/头像);取过一次就缓存。"""
        key = self._target.cookie
        if key in self._identity_cache:
            return self._identity_cache[key]
        try:
            identity = self._sender.fetch_identity(key)
        except SendError as exc:  # fetch_identity 内部已吞掉,这里只是兜底
            logger.debug("取不到自己的身份(忽略):%s", exc)
            identity = None
        self._identity_cache[key] = identity
        return identity


class DanmakuSubmitter(QObject):
    """发送栏背后的推进器:节流 → 后台发送 → 成功/失败信号。"""

    submitted_ok = pyqtSignal(str, object, object)  # (text, Identity | None, SendTarget)
    failed = pyqtSignal(str, str)  # (text, message);text 为空表示没提交出去

    def __init__(
        self,
        sender: BilibiliSender | None = None,
        clock: Callable[[], float] = time.monotonic,
        pool: QThreadPool | None = None,
    ) -> None:
        super().__init__()
        self._sender = sender or BilibiliSender()
        self._clock = clock
        self._pool = pool or QThreadPool.globalInstance()
        self._last_at: float | None = None
        self._busy = False
        self._identity_cache: dict[str, Identity | None] = {}

    def is_busy(self) -> bool:
        return self._busy

    def remaining(self) -> float:
        return throttle_remaining(self._last_at, self._clock())

    def submit(self, target: SendTarget, text: str) -> bool:
        """发起一次发送;被节流/正在发送时返回 False(原因已经经 failed 说出)。"""
        if self._busy:
            self.failed.emit("", "上一条还在发送中,稍等一下")
            return False
        wait = self.remaining()
        if wait > 0:
            self.failed.emit("", f"发送太频繁,{wait:.1f} 秒后再试")
            return False
        self._busy = True
        self._last_at = self._clock()
        signals = _WorkerSignals(self)
        signals.done.connect(self._on_done)
        signals.failed.connect(self._on_failed)
        self._pool.start(
            _SendWorker(self._sender, target, text, signals, self._identity_cache)
        )
        return True

    def _on_done(self, text: str, identity: object, target: object) -> None:
        self._busy = False
        self.submitted_ok.emit(text, identity, target)

    def _on_failed(self, text: str, message: str) -> None:
        self._busy = False
        self.failed.emit(text, message)


def target_for(
    cfg: Config, room_filter: str | None = None, observed_room: str | None = None
) -> SendTarget | None:
    """当前窗口该发到哪个房间(sender.resolve_target 的配置侧包装)。"""
    return resolve_target(cfg, room_filter, observed_room)


__all__ = [
    "MIN_INTERVAL_S",
    "DanmakuSubmitter",
    "Identity",
    "SendError",
    "SendTarget",
    "target_for",
    "throttle_remaining",
]
