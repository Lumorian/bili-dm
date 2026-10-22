"""滚动墙纯逻辑:计数淘汰 + 像素级视口(可上下滚动查看历史)。"""

from bilidm_overlay.danmaku.lifecycle import (
    Viewport,
    Wall,
    added_height,
    clamp_offset,
    content_height,
    scroll_offset_by,
    viewport,
    visible_window,
)
from bilidm_overlay.danmaku.model import Danmaku


def msg(content="hi"):
    return Danmaku(name="A", content=content)


def _fixed(h=20.0):
    return lambda row: h


# --- 数据轴 ---


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


# --- 视口:贴底 ---


def test_offset_zero_pins_newest_row():
    wall = Wall(max_rows=50)
    for i in range(10):
        wall.add(msg(str(i)))
    vp = viewport(wall.snapshot(), avail_height=100, measure=_fixed())
    assert vp.following is True
    assert vp.rows()[-1].msg.content == "9", "贴底时最新一条必须可见"
    assert vp.scrollable is True, "内容比屏幕长,就应该能滚"


def test_content_shorter_than_panel_is_not_scrollable():
    wall = Wall()
    wall.add(msg("only"))
    vp = viewport(wall.snapshot(), avail_height=100, measure=_fixed())
    assert vp.max_offset == 0.0
    assert vp.scrollable is False
    assert vp.entries[0][1] == 0.0, "内容不满一屏时从顶部开始,不贴着底部"


def test_empty_wall():
    vp = viewport([], avail_height=100, measure=_fixed())
    assert vp.entries == ()
    assert vp.rows() == []
    assert vp.max_offset == 0.0
    assert vp.following is True


# --- 视口:向上翻 ---


def test_scrolling_up_reveals_older_rows():
    wall = Wall()
    for i in range(10):
        wall.add(msg(str(i)))
    rows = wall.snapshot()
    vp = viewport(rows, avail_height=100, measure=_fixed(), offset=60)
    assert vp.following is False
    texts = [r.msg.content for r in vp.rows()]
    assert "9" not in texts, "往上翻 60px(3 行)后最新行应已翻出屏幕"
    assert "3" in texts
    assert vp.offset == 60.0


def test_offset_is_pixel_accurate_not_row_snapped():
    """上滚一点点就该动一点点:整行跳变会让滚轮和滚动条都不跟手。"""
    wall = Wall()
    for i in range(10):
        wall.add(msg(str(i)))
    rows = wall.snapshot()
    base = {r.msg.content: y for r, y in viewport(rows, 100, _fixed(), offset=0).entries}
    half = {r.msg.content: y for r, y in viewport(rows, 100, _fixed(), offset=7).entries}
    assert viewport(rows, 100, _fixed(), offset=7).offset == 7.0, "偏移要原样保留,不能吸到整行"
    # 上滚 7px = 内容整体下移 7px:同一行在两帧里的 y 正好差 7
    shared = set(base) & set(half)
    assert shared, "上滚 7px 后应与贴底时仍有共同可见行(否则就是整行跳变了)"
    for text in shared:
        assert half[text] == base[text] + 7


def test_scroll_clamped_to_content_edges():
    wall = Wall()
    for i in range(5):
        wall.add(msg(str(i)))
    rows = wall.snapshot()
    # 总高 100,屏幕 60 → 最多能往上翻 40
    vp = viewport(rows, avail_height=60, measure=_fixed(), offset=999)
    assert vp.max_offset == 40.0
    assert vp.offset == 40.0, "滚过头要收在顶端"
    assert vp.rows()[0].msg.content == "0", "翻到顶就是最旧一行"
    # 负数(往下滚过头)= 回到底部跟随
    assert viewport(rows, avail_height=60, measure=_fixed(), offset=-30).offset == 0.0


def test_zero_height_panel_degrades_to_newest_row():
    """窗口还没量出高度时只画最新一行,不能把整屏当成"全都可见"。"""
    wall = Wall()
    for i in range(3):
        wall.add(msg(str(i)))
    vp = viewport(wall.snapshot(), avail_height=0, measure=_fixed())
    assert [r.msg.content for r in vp.rows()] == ["2"]


def test_tall_row_is_clipped_not_hidden():
    wall = Wall()
    wall.add(msg("big"))
    vp = viewport(wall.snapshot(), avail_height=50, measure=_fixed(120.0))
    assert len(vp.entries) == 1, "超高的行仍然要画(裁切即可),不能整行吞掉"


def test_variable_heights_stay_aligned():
    heights = {"0": 30.0, "1": 40.0, "2": 50.0}
    wall = Wall()
    for i in ("0", "1", "2"):
        wall.add(msg(i))
    vp = viewport(
        wall.snapshot(), avail_height=100, measure=lambda row: heights[row.msg.content]
    )
    # 总高 120,贴底 → top=20:第一行被裁掉 20px,后两行完整可见
    assert [r.msg.content for r in vp.rows()] == ["0", "1", "2"]
    assert vp.entries[0][1] == -20.0
    assert vp.entries[2][1] == 50.0


# --- 贴底/离底 ---


def test_following_flag_means_pinned_to_bottom():
    vp = Viewport((), offset=0.0, max_offset=10.0, content_height=110.0, avail_height=100.0)
    assert vp.following is True
    assert Viewport((), 0.5, 10.0, 110.0, 100.0).following is False
    assert Viewport((), 10.0, 10.0, 110.0, 100.0).following is False


def test_added_height_counts_only_new_rows():
    first = [msg("a"), msg("b")]
    second = [first[0], first[1], msg("c")]
    assert added_height(first, second, _fixed()) == 20.0
    assert added_height(first, first, _fixed()) == 0.0


def test_scroll_by_deltas():
    wall = Wall()
    for i in range(10):
        wall.add(msg(str(i)))  # 总高 200
    rows = wall.snapshot()
    assert scroll_offset_by(0.0, 45.0, rows, 100, _fixed()) == 45.0
    assert scroll_offset_by(45.0, -45.0, rows, 100, _fixed()) == 0.0
    assert scroll_offset_by(0.0, -45.0, rows, 100, _fixed()) == 0.0, "已经在底部就别变负数"
    assert scroll_offset_by(99.0, 999.0, rows, 100, _fixed()) == 100.0


def test_clamp_offset_helper():
    assert clamp_offset(5.0, 10.0) == 5.0
    assert clamp_offset(-5.0, 10.0) == 0.0
    assert clamp_offset(50.0, 10.0) == 10.0
    assert clamp_offset(50.0, 0.0) == 0.0, "没有可滚空间时偏移恒为 0"


def test_content_height_helper():
    assert content_height([msg("a"), msg("b")], _fixed(15.0)) == 30.0
    assert content_height([], _fixed()) == 0.0


# --- 旧接口 ---


def test_visible_window_is_offset_zero_viewport():
    wall = Wall()
    for i in range(10):
        wall.add(msg(str(i)))
    assert visible_window(wall.snapshot(), 100, _fixed()) == viewport(
        wall.snapshot(), 100, _fixed()
    ).rows()
