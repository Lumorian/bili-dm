"""行内流式排版(纯逻辑):token 切分、折行、盒子换行、行尾 margin。"""

from bilidm_overlay.danmaku.layout import Run, block_height, tokenize, wrap_runs


def fixed_measure(width_per_char: float = 10.0):
    """等宽度量:每个字符 10px,便于精确推算。"""

    def measure(text: str, run: Run) -> float:
        return len(text) * width_per_char * run.scale

    return measure


def test_tokenize_splits_ascii_words_and_cjk_chars():
    assert tokenize("hi 中文") == ["hi", " ", "中", "文"]
    assert tokenize("") == []


def test_wrap_single_line_when_fits():
    lines = wrap_runs([Run(text="abc")], avail_width=100, measure_text=fixed_measure(), line_height=18)
    assert len(lines) == 1
    assert lines[0].items[0].text == "abc"


def test_wrap_breaks_on_cjk_overflow():
    lines = wrap_runs([Run(text="中文中文")], avail_width=20, measure_text=fixed_measure(), line_height=18)
    assert len(lines) == 2
    # 同 run 的相邻字符合并进同一项,便于一次性绘制
    assert [item.text for item in lines[0].items] == ["中文"]
    assert [item.text for item in lines[1].items] == ["中文"]


def test_wrap_does_not_split_ascii_word():
    lines = wrap_runs([Run(text="hello world")], avail_width=50, measure_text=fixed_measure(), line_height=18)
    # "hello" + " " 占 60px 已超 50,所以 hello 单独一行
    assert lines[0].items[0].text == "hello"
    assert any("world" in item.text for line in lines for item in line.items)


def test_word_wider_than_line_is_hard_broken():
    lines = wrap_runs(
        [Run(text="abcdefgh")], avail_width=20, measure_text=fixed_measure(), line_height=18
    )
    assert len(lines) == 4
    assert "".join(item.text for line in lines for item in line.items) == "abcdefgh"


def test_box_wraps_as_atomic_unit():
    box = Run(box_kind="medal", box_width=40, box_height=15)
    lines = wrap_runs(
        [Run(text="abcd"), box], avail_width=50, measure_text=fixed_measure(), line_height=18
    )
    assert len(lines) == 2
    assert lines[1].items[0].run is box
    assert lines[1].height == 18  # 盒高 15 < 行高 18


def test_box_taller_than_line_grows_line_height():
    box = Run(box_kind="medal", box_width=10, box_height=24)
    lines = wrap_runs([box], avail_width=50, measure_text=fixed_measure(), line_height=18)
    assert lines[0].height == 24


def test_trailing_margin_dropped_at_line_end():
    # 只有后面还有内容的 run 才补 pad_right;行尾不补(与浏览器一致)
    runs = [Run(text="a", pad_right=5.0)]
    lines = wrap_runs(runs, avail_width=100, measure_text=fixed_measure(), line_height=18)
    assert lines[0].width == 10.0
    runs2 = [Run(text="a", pad_right=5.0), Run(text="b")]
    lines2 = wrap_runs(runs2, avail_width=100, measure_text=fixed_measure(), line_height=18)
    assert lines2[0].items[1].x == 15.0


def test_zero_width_returns_no_lines():
    assert wrap_runs([Run(text="a")], avail_width=0, measure_text=fixed_measure(), line_height=18) == []


def test_block_height_sums_line_heights():
    lines = wrap_runs(
        [Run(text="中文中文中文")], avail_width=20, measure_text=fixed_measure(), line_height=18
    )
    assert block_height(lines, 18) == 18 * len(lines)
    assert block_height([], 18) == 18
