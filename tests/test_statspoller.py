"""RoomStatsPoller:用同步 fake pool 验证房间集合/合并/失败保留旧值。"""

import pytest
from PyQt6.QtWidgets import QApplication

from bilidm_overlay.roomstats import RoomStats, RoomStatsError
from bilidm_overlay.statspoller import RoomStatsPoller


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail = False

    def fetch(self, rids):
        self.calls.append(list(rids))
        if self.fail:
            raise RoomStatsError(0, "boom")
        return {
            f"bilibili:{rid}": RoomStats(
                rid=rid, room_id=rid, live_status=1, online=123, online_text="123"
            )
            for rid in rids
        }


class FakePool:
    def start(self, worker) -> None:
        # 同步执行:避免测试依赖线程调度,信号仍在同一线程直接回调
        worker.run()


def _poller(client=None):
    poller = RoomStatsPoller(client=client or FakeClient(), pool=FakePool())
    poller.start()
    return poller


def test_set_rooms_filters_bilibili_and_fetches(app):
    client = FakeClient()
    poller = _poller(client)
    seen = []
    poller.updated.connect(seen.append)

    poller.set_rooms(["bilibili:1:cookie", "douyin:2", "bilibili:2", ""])

    assert poller.rooms() == ["bilibili:1", "bilibili:2"]
    assert client.calls == [["1", "2"]]
    assert set(seen[-1]) == {"bilibili:1", "bilibili:2"}


def test_watch_adds_room_and_ignores_other_platforms(app):
    client = FakeClient()
    poller = _poller(client)
    poller.watch("bilibili", "3")
    poller.watch("bilibili", "3")  # 重复发现不重复请求
    poller.watch("douyin", "4")
    assert poller.rooms() == ["bilibili:3"]
    assert client.calls == [["3"]]


def test_set_rooms_drops_removed_stats(app):
    poller = _poller()
    poller.set_rooms(["bilibili:1", "bilibili:2"])
    poller.set_rooms(["bilibili:1"])
    assert set(poller.stats()) == {"bilibili:1"}


def test_failure_keeps_last_snapshot(app):
    client = FakeClient()
    poller = _poller(client)
    poller.set_rooms(["bilibili:1"])
    assert poller.stats()["bilibili:1"].online == 123

    client.fail = True
    poller.poll()
    assert poller.stats()["bilibili:1"].online == 123  # 网络抖一下别把旧值抹掉


def test_stopped_poller_does_not_poll_until_restarted(app):
    client = FakeClient()
    poller = _poller(client)
    poller.set_rooms(["bilibili:1"])
    poller.stop()
    poller.watch("bilibili", "2")
    assert client.calls == [["1"]]  # stop 后只记房间,不请求
    poller.start()
    assert client.calls[-1] == ["1", "2"]
