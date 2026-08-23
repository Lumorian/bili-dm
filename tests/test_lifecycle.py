from bilidm_overlay.danmaku.lifecycle import Wall
from bilidm_overlay.danmaku.model import Danmaku


def msg(content="hi"):
    return Danmaku(name="A", content=content)


def test_add_and_snapshot_order():
    wall = Wall(max_rows=3, ttl=60)
    wall.add(msg("1"), now=0.0)
    wall.add(msg("2"), now=1.0)
    rows = wall.snapshot()
    assert len(rows) == 2
    assert rows[0].msg.content == "1"
    assert rows[1].msg.content == "2"
    assert rows[1].born == 1.0


def test_max_rows_evicts_oldest():
    wall = Wall(max_rows=3, ttl=60)
    for i, t in enumerate([0.0, 1.0, 2.0, 3.0]):
        wall.add(msg(str(i)), now=t)
    assert [r.msg.content for r in wall.snapshot()] == ["1", "2", "3"]


def test_prune_expires_by_ttl():
    wall = Wall(max_rows=10, ttl=60)
    wall.add(msg("old"), now=0.0)
    wall.add(msg("new"), now=50.0)
    wall.prune(now=61.0)
    assert [r.msg.content for r in wall.snapshot()] == ["new"]


def test_alpha_fade_curve():
    wall = Wall(max_rows=10, ttl=60)
    wall.add(msg("x"), now=0.0)
    assert wall.alpha_of(wall.snapshot()[0], now=0.0) == 1.0
    assert wall.alpha_of(wall.snapshot()[0], now=45.0) == 0.5
    assert wall.alpha_of(wall.snapshot()[0], now=60.0) == 0.0
    assert wall.alpha_of(wall.snapshot()[0], now=90.0) == 0.0


def test_visible_window_takes_latest_rows():
    from bilidm_overlay.danmaku.lifecycle import visible_window

    wall = Wall(max_rows=50, ttl=30)
    for i in range(10):
        wall.add(msg(str(i)), now=float(i))
    vis = visible_window(wall.snapshot(), avail_height=100, line_height=20)
    assert len(vis) == 5
    assert vis[-1].msg.content == "9"  # 自动滚底:最新一条必在
    assert vis[0].msg.content == "5"


def test_visible_window_empty_and_insufficient():
    from bilidm_overlay.danmaku.lifecycle import visible_window

    assert visible_window([], avail_height=100, line_height=20) == []
    wall = Wall()
    wall.add(msg("x"), now=0.0)
    vis = visible_window(wall.snapshot(), avail_height=100, line_height=20)
    assert len(vis) == 1


def test_visible_window_line_height_bigger_than_panel():
    from bilidm_overlay.danmaku.lifecycle import visible_window

    wall = Wall()
    for i in range(3):
        wall.add(msg(str(i)), now=float(i))
    vis = visible_window(wall.snapshot(), avail_height=10, line_height=20)
    assert len(vis) == 1
    assert vis[0].msg.content == "2"
