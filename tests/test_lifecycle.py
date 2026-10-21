from bilidm_overlay.danmaku.lifecycle import Wall
from bilidm_overlay.danmaku.model import Danmaku


def msg(content="hi"):
    return Danmaku(name="A", content=content)


def test_add_and_snapshot_order():
    wall = Wall(max_rows=3)
    wall.add(msg("1"))
    wall.add(msg("2"))
    rows = wall.snapshot()
    assert len(rows) == 2
    assert rows[0].msg.content == "1"
    assert rows[1].msg.content == "2"


def test_max_rows_evicts_oldest():
    wall = Wall(max_rows=3)
    for i in [0, 1, 2, 3]:
        wall.add(msg(str(i)))
    assert [r.msg.content for r in wall.snapshot()] == ["1", "2", "3"]


def test_rows_stay_until_counts_evict():
    wall = Wall(max_rows=3)
    wall.add(msg("a"))
    wall.add(msg("b"))
    # 无时间淘汰:不传时间,弹幕一直保留,直到数量顶替
    assert [r.msg.content for r in wall.snapshot()] == ["a", "b"]
    wall.add(msg("c"))
    wall.add(msg("d"))
    assert [r.msg.content for r in wall.snapshot()] == ["b", "c", "d"]


def test_visible_window_takes_latest_rows():
    from bilidm_overlay.danmaku.lifecycle import visible_window

    wall = Wall(max_rows=50)
    for i in range(10):
        wall.add(msg(str(i)))
    vis = visible_window(wall.snapshot(), avail_height=100, measure=lambda row: 20.0)
    assert len(vis) == 5
    assert vis[-1].msg.content == "9"  # 自动滚底:最新一条必在
    assert vis[0].msg.content == "5"


def test_visible_window_empty_and_insufficient():
    from bilidm_overlay.danmaku.lifecycle import visible_window

    assert visible_window([], avail_height=100, measure=lambda row: 20.0) == []
    wall = Wall()
    wall.add(msg("x"))
    vis = visible_window(wall.snapshot(), avail_height=100, measure=lambda row: 20.0)
    assert len(vis) == 1


def test_visible_window_row_taller_than_panel():
    from bilidm_overlay.danmaku.lifecycle import visible_window

    wall = Wall()
    for i in range(3):
        wall.add(msg(str(i)))
    vis = visible_window(wall.snapshot(), avail_height=10, measure=lambda row: 20.0)
    assert len(vis) == 1
    assert vis[0].msg.content == "2"


def test_visible_window_variable_heights():
    from bilidm_overlay.danmaku.lifecycle import visible_window

    wall = Wall()
    for i, h in enumerate([30.0, 40.0, 50.0]):
        wall.add(msg(str(i)))
    # 最新 50 + 40 = 90 ≤ 100,再往前 30 就超了:只显示最近两条
    heights = {str(i): h for i, h in enumerate([30.0, 40.0, 50.0])}
    vis = visible_window(
        wall.snapshot(), avail_height=100, measure=lambda row: heights[row.msg.content]
    )
    assert [r.msg.content for r in vis] == ["1", "2"]


def test_visible_window_newest_taller_than_panel():
    from bilidm_overlay.danmaku.lifecycle import visible_window

    wall = Wall()
    for i in range(3):
        wall.add(msg(str(i)))
    # 最新行 120 高,超过面板:退化为只有最新一条(始终可见)
    vis = visible_window(wall.snapshot(), avail_height=100, measure=lambda row: 120.0)
    assert [r.msg.content for r in vis] == ["2"]
