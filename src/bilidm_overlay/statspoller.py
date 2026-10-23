"""后台轮询直播间在线人数:QThreadPool + QTimer,结果回主线程。

B 站接口是同步 urllib(见 roomstats.py),不能放在 30ms 的重绘线程里;这里照抄
submit.py 的模式:工作线程拉数据,信号回主线程,窗口只在主线程改。

Poller 只负责"哪些房间、最近一次结果是什么",显示口径(合并/单房间/离线)
留给 window —— 同一份数据要喂给所有窗口,per-room 模式各自筛自己的房间。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

from .roomstats import BilibiliRoomStatsClient, RoomStats, RoomStatsError

logger = logging.getLogger(__name__)

MIN_INTERVAL_S = 5  # 再快就成刷接口了;默认 30s 与官方页面刷新节奏接近


class _PollSignals(QObject):
    done = pyqtSignal(object)  # dict[str, RoomStats]
    failed = pyqtSignal(str)


class _PollWorker(QRunnable):
    def __init__(
        self,
        client: BilibiliRoomStatsClient,
        rids: list[str],
        signals: _PollSignals,
    ) -> None:
        super().__init__()
        self._client = client
        self._rids = rids
        self._signals = signals

    def run(self) -> None:
        try:
            stats = self._client.fetch(self._rids)
        except RoomStatsError as exc:
            self._signals.failed.emit(exc.message)
            return
        except Exception as exc:  # 工作线程异常不能静默消失
            logger.exception("拉取直播间在线人数时出现未预期错误")
            self._signals.failed.emit(str(exc))
            return
        self._signals.done.emit(stats)


class RoomStatsPoller(QObject):
    """定时拉取一批 B 站房间的在线人数;updated 携带"当前全部已知房间"的快照。"""

    updated = pyqtSignal(object)  # dict[str, RoomStats]

    def __init__(
        self,
        client: BilibiliRoomStatsClient | None = None,
        interval_seconds: int = 30,
        pool: QThreadPool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client or BilibiliRoomStatsClient()
        self._pool = pool or QThreadPool.globalInstance()
        self._rooms: set[str] = set()
        self._stats: dict[str, RoomStats] = {}
        self._busy = False
        self._enabled = False  # start() 之后才允许发请求
        self._polled_rooms: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setInterval(max(MIN_INTERVAL_S, int(interval_seconds)) * 1000)
        self._timer.timeout.connect(self.poll)
        # 工作线程与主线程之间的唯一信号枢纽:一次轮询结束后复用,避免每 30s
        # 新建一堆 QObject(长跑几小时会白白攒下几百个)。
        self._signals = _PollSignals(self)
        self._signals.done.connect(self._on_done)
        self._signals.failed.connect(self._on_failed)

    # --- 房间集合 ---
    def set_rooms(self, rooms: Iterable[str]) -> None:
        """整体替换监视列表;元素是 'platform:rid[:cookie]'(只收 B 站)。"""
        new = {key for room in rooms if (key := _room_key(room))}
        if new == self._rooms:
            return
        self._rooms = new
        # 被移除的房间不要留在快照里,否则合并模式会把旧在线数继续加进去
        self._stats = {k: v for k, v in self._stats.items() if k in new}
        self.poll()

    def watch(self, platform: str, rid: str) -> None:
        """从流动的弹幕里发现的房间:只增不减,避免刚来一条就触发整表替换。"""
        key = _room_key(f"{platform}:{rid}")
        if key is None or key in self._rooms:
            return
        self._rooms.add(key)
        self.poll()

    def rooms(self) -> list[str]:
        return sorted(self._rooms)

    def stats(self) -> dict[str, RoomStats]:
        return dict(self._stats)

    # --- 生命周期 ---
    def start(self) -> None:
        self._enabled = True
        self._timer.start()
        self.poll()

    def stop(self) -> None:
        self._enabled = False
        self._timer.stop()

    def poll(self) -> None:
        if not self._enabled or self._busy or not self._rooms:
            return
        self._busy = True
        self._polled_rooms = set(self._rooms)
        rids = [key.split(":", 1)[1] for key in sorted(self._polled_rooms)]
        self._pool.start(_PollWorker(self._client, rids, self._signals))

    # --- 工作线程回调(主线程) ---
    def _on_done(self, stats: object) -> None:
        self._busy = False
        if isinstance(stats, dict):
            self._stats.update({str(k): v for k, v in stats.items() if str(k) in self._rooms})
        self._stats = {k: v for k, v in self._stats.items() if k in self._rooms}
        self.updated.emit(dict(self._stats))
        self._poll_again_if_rooms_changed()

    def _on_failed(self, message: str) -> None:
        self._busy = False
        # 失败保留上一次快照:网络抖一下就把在线数抹掉,比显示旧值更难看
        logger.debug("直播间在线人数刷新失败: %s", message)
        self.updated.emit(dict(self._stats))
        self._poll_again_if_rooms_changed()

    def _poll_again_if_rooms_changed(self) -> None:
        if self._rooms != self._polled_rooms:
            QTimer.singleShot(0, self.poll)


def _room_key(room: str) -> str | None:
    parts = str(room or "").split(":", 2)
    if len(parts) < 2 or parts[0] != "bilibili" or not parts[1].strip():
        return None
    return f"bilibili:{parts[1].strip()}"
