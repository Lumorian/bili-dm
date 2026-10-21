import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import QApplication

from bilidm_overlay.danmaku.layout import Run, tokenize, wrap_runs
from bilidm_overlay.danmaku.lifecycle import Wall
from bilidm_overlay.danmaku.medal import (
    GUARD_PAD_LEFT,
    PILL_HEIGHT,
    PILL_PAD_LEFT,
    PILL_PAD_RIGHT,
    level_slot_width,
    medal_from,
)
from bilidm_overlay.danmaku.model import Danmaku, MedalInfo
from bilidm_overlay.danmaku.theme import DARK, LIGHT, theme_for
from bilidm_overlay.danmaku.wall import PANEL_PAD_Y, ROW_PAD, TEXT_X, WallWidget

LONG_TEXT = "这条弹幕真的非常长" * 6  # 72 个 CJK 字符,远超单行宽度


def _painted_ys(img, x0: int, x1: int) -> list[int]:
    """文本列 x∈[x0,x1) 内与背景色不同的行号列表(验证行带堆叠)。"""
    bg = img.pixelColor(0, 0)  # grab 以 palette base 填充背景(非透明)
    return [
        y for y in range(img.height()) if any(img.pixelColor(x, y) != bg for x in range(x0, x1))
    ]


_APP = None  # 模块级持有引用:QApplication 被 GC 后 QWidget 构造会 abort


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_paints_rows_without_error():
    _app()
    widget = WallWidget()
    widget.resize(400, 300)
    wall = Wall(max_rows=5)
    wall.add(Danmaku(type="chat", platform="bilibili", name="A", content="你好"))
    wall.add(Danmaku(type="gift", name="B", item="辣条", num=20))
    wall.add(Danmaku(type="superchat", name="C", content="加油!", price=30))
    widget.update_wall(wall)
    img = widget.grab().toImage()  # 走真实渲染管线(grab 会调用 paintEvent)
    assert widget.row_count() == 3  # 三行均已入墙,绘制过程无异常
    assert _painted_ys(img, 0, img.width()), "应有可见像素"


def test_clear_rows():
    _app()
    widget = WallWidget()
    wall = Wall()
    widget.update_wall(wall)
    wall.add(Danmaku(name="A"))
    widget.update_wall(wall)
    wall.clear()
    widget.update_wall(wall)
    widget.grab()
    assert widget.row_count() == 0


def test_long_content_wraps_to_multiple_lines():
    _app()
    widget = WallWidget()
    widget.resize(400, 300)
    widget.set_font("Sans Serif", 12)
    measure = widget._measure
    runs = [Run(text=LONG_TEXT)]
    lines = wrap_runs(runs, widget._text_width(), measure, widget._line_height())
    assert len(lines) > 1
    # 短文本不换行:保持单行
    short = wrap_runs([Run(text="你好")], widget._text_width(), measure, widget._line_height())
    assert len(short) == 1


def test_wrap_lines_are_stacked():
    _app()
    widget = WallWidget()
    widget.resize(400, 300)
    widget.set_font("Sans Serif", 12)
    measure = widget._measure
    lines = wrap_runs([Run(text=LONG_TEXT)], widget._text_width(), measure, widget._line_height())
    assert len(lines) > 1
    ys = [round(line.y, 1) for line in lines]
    assert len(set(ys)) == len(lines)  # 各行 y 互不相同
    assert lines[1].y > lines[0].y


def test_ascii_words_are_not_split():
    assert tokenize("hello world!") == ["hello", " ", "world", "!"]
    assert tokenize("中文abc") == ["中", "文", "abc"]


def test_long_content_renders_stacked_bands():
    _app()
    widget = WallWidget()
    widget.resize(400, 300)
    wall = Wall(max_rows=5)
    wall.add(Danmaku(type="chat", platform="bilibili", name="A", content=LONG_TEXT))
    widget.update_wall(wall)
    img = widget.grab().toImage()
    ys = _painted_ys(img, int(TEXT_X) + 1, int(TEXT_X) + 80)  # 文本列,避开头像区
    assert ys, "文本列应画出文字"
    font = QFont()
    font.setPixelSize(11)
    line_h = QFontMetrics(font).height()
    span = ys[-1] - ys[0]
    # 多行堆叠:纵向跨度 ≥ 2 个行高;重叠 bug 时整块文字聚在一行
    assert span >= 2 * line_h, f"长弹幕应渲染为多个行带,实际跨度 {span}px < {2 * line_h}px"


def test_prepare_caches_by_text_and_width():
    _app()
    widget = WallWidget()
    widget.resize(400, 300)
    wall = Wall()
    wall.add(Danmaku(type="chat", name="A", content=LONG_TEXT))
    row = wall.snapshot()[0]
    first = widget._prepare(row, 300.0)
    second = widget._prepare(row, 300.0)
    assert first[0] is second[0]  # 相同文本与宽度复用排版结果
    other = widget._prepare(row, 200.0)
    assert other[0] is not first[0]  # 宽度变化需要重排


# --- 官方排版对齐:勋章 / 等级宽度 / 主题 ---


def test_medal_pill_width_follows_official_metrics():
    _app()
    widget = WallWidget()
    widget.set_font("Sans Serif", 12)  # 回到官方基准 12px,便于逐像素对照
    medal = medal_from(MedalInfo(name="酷萨", level=33, guard_level=3))
    assert medal is not None
    width, height = widget._medal_size(medal)
    assert height == PILL_HEIGHT
    name_w = widget._metrics(12).horizontalAdvance("酷萨")  # 名字宽度不缩放
    # 官方:胶囊左内边距 2 + 舰长图标位 12 + 名字 + 2 + 等级槽 8 + 右内边距 6
    expected = PILL_PAD_LEFT + GUARD_PAD_LEFT + name_w + 2.0 + level_slot_width(33) + PILL_PAD_RIGHT
    assert width == expected
    # 非舰队成员:仅胶囊左内边距 2px
    plain = medal_from(MedalInfo(name="酷萨", level=16))
    assert plain is not None
    plain_w, _ = widget._medal_size(plain)
    assert plain_w == PILL_PAD_LEFT + name_w + 2.0 + level_slot_width(16) + PILL_PAD_RIGHT
    assert plain_w < width  # 舰队款左侧多 12px 留给图标


def test_level_slot_width_matches_official_classes():
    assert level_slot_width(9) == 4.0  # .one-digit-level
    assert level_slot_width(10) == 8.0
    assert level_slot_width(99) == 8.0
    assert level_slot_width(100) == 15.0  # .three-digits-level


def test_medal_run_reserves_gap():
    _app()
    widget = WallWidget()
    widget.set_font("Sans Serif", 12)
    run = widget._medal_run(medal_from(MedalInfo(name="酷萨", level=33)))
    assert run.box_kind == "medal"
    # .fans-medal-item-ctnr{margin-left:4px;margin-right:3px}:左并进盒子,右交给排版器
    assert run.pad_right == 3.0
    assert run.box_width == widget._medal_size(medal_from(MedalInfo(name="酷萨", level=33)))[0] + 4.0


def test_medal_omitted_when_not_worn():
    assert medal_from(None) is None
    assert medal_from(MedalInfo(name="", level=10)) is None
    assert medal_from(MedalInfo(name="酷萨", level=0)) is None


def test_chat_row_runs_order_is_official():
    """行内顺序:勋章 → 昵称 → " : " → 正文(官方 danmaku-item-left/right)。"""
    _app()
    widget = WallWidget()
    widget.set_font("Sans Serif", 12)
    wall = Wall()
    wall.add(
        Danmaku(
            type="chat",
            name="浮***",
            content="哈哈",
            medal=MedalInfo(name="酷萨", level=33, guard_level=3),
            guard_level=3,
        )
    )
    runs = widget._runs_for(wall.snapshot()[0])
    assert runs[0].box_kind == "medal"
    assert runs[1].text == "浮***"
    assert runs[2].text == " : "
    assert runs[3].text == "哈哈"
    # 舰队成员昵称取官方青色
    assert runs[1].color == "#00D1F1"


def test_gift_row_uses_pay_yellow():
    _app()
    widget = WallWidget()
    widget.set_font("Sans Serif", 12)
    widget.set_theme("dark")
    wall = Wall()
    wall.add(Danmaku(type="gift", name="Bob", item="辣条", num=20))
    runs = widget._runs_for(wall.snapshot()[0])
    texts = [r.text for r in runs]
    assert texts == ["Bob", "赠送", "辣条", "x20"]
    assert runs[2].color == DARK.pay_yellow
    assert runs[3].color == DARK.pay_yellow


def test_subscribe_row_wording():
    _app()
    widget = WallWidget()
    widget.set_font("Sans Serif", 12)
    wall = Wall()
    wall.add(Danmaku(type="subscribe", name="Dave", item="舰长"))
    texts = [r.text for r in widget._runs_for(wall.snapshot()[0])]
    assert texts == ["Dave", "开通了", "舰长"]


def test_theme_tokens_are_official():
    assert DARK.bg == "#101011"  # dark.css --Ga0 (--bg2)
    assert DARK.text == "#A2A7AE"  # dark.css --Ga7 (--text2)
    assert LIGHT.bg == "#F6F7F8"  # light.css --Ga0
    assert LIGHT.text == "#61666D"  # light.css --Ga7
    assert theme_for("nope") is DARK


def test_superchat_paints_card_background():
    _app()
    widget = WallWidget()
    widget.resize(400, 200)
    wall = Wall()
    wall.add(Danmaku(type="superchat", name="Carol", content="加油!", price=30))
    widget.update_wall(wall)
    img = widget.grab().toImage()
    # 卡片右半区应是 SC 主题黄(#F2C55C 起),而非空白;
    # 取样点避开行首头像列(头像已覆盖 x∈[PANEL_PAD_X, +24px] 的整条竖带)。
    pixel = img.pixelColor(int(TEXT_X) + 120, 8)
    assert pixel.red() > 200 and pixel.green() > 150 and pixel.blue() < 160


# --- 绘制分支覆盖:勋章胶囊 / 航海锚 / 醒目留言卡片 / 头像 ---


def _render(wall, *, w=340, h=420, size=12, theme="light", avatars=None):
    _app()
    widget = WallWidget()
    widget.resize(w, h)
    widget.set_font("Sans Serif", size)
    widget.set_theme(theme)
    if avatars is not None:
        widget.set_avatars(avatars)
    widget.update_wall(wall)
    return widget, widget.grab().toImage()


def test_paints_guard_medal_with_anchor():
    """舰队成员的胶囊会画锚图标:同一行里胶囊区域应出现白色描边像素。"""
    wall = Wall()
    wall.add(
        Danmaku(
            type="chat",
            name="浮***",
            content="测试",
            guard_level=3,
            medal=MedalInfo(
                name="酷萨", level=33, color_start="#638FFE", color_end="#5B8AF5",
                color_border="#638FFE", guard_level=3,
            ),
        )
    )
    widget, img = _render(wall)
    assert widget.row_count() == 1
    # 胶囊主体色(#638FFE 附近)必须出现
    blues = [
        (x, y)
        for y in range(40)
        for x in range(30, 140)
        if abs(img.pixelColor(x, y).blue() - 254) < 40
        and abs(img.pixelColor(x, y).red() - 99) < 40
    ]
    assert blues, "舰队勋章胶囊未绘制"
    # 锚的白色描边(靠近胶囊左缘外侧)
    whites = [
        (x, y)
        for y in range(40)
        for x in range(30, 60)
        if img.pixelColor(x, y).red() > 220
        and img.pixelColor(x, y).green() > 220
        and img.pixelColor(x, y).blue() > 220
    ]
    assert whites, "航海锚图标未绘制"


def test_paints_plain_medal_without_anchor_overflow():
    """普通勋章左内边距只有 2px:胶囊左缘比舰队款更靠近文字列。"""
    plain = MedalInfo(name="酷萨", level=16, color_start="#FF86B2", color_end="#FF86B2",
                      color_border="#FF86B2")
    wall = Wall()
    wall.add(Danmaku(type="chat", name="予***", content="文本", medal=plain))
    _widget, img = _render(wall)
    pinks = [
        x
        for y in range(40)
        for x in range(20, 140)
        if img.pixelColor(x, y).red() > 240 and img.pixelColor(x, y).green() < 160
    ]
    assert pinks, "普通勋章胶囊未绘制"


def test_paints_superchat_card_with_price():
    wall = Wall()
    wall.add(Danmaku(type="superchat", name="Carol", content="加油!", price=30))
    _widget, img = _render(wall)
    # 卡片底色为 SC 主题黄;取卡片中心偏左的像素
    pixel = img.pixelColor(int(TEXT_X) + 40, 20)
    assert pixel.red() > 180 and pixel.green() > 120 and pixel.blue() < 140
    # 金额 ¥30 画在右侧:右半区应有白色像素
    whites = [
        x
        for y in range(8, 40)
        for x in range(240, 335)
        if img.pixelColor(x, y).red() > 230
        and img.pixelColor(x, y).green() > 230
        and img.pixelColor(x, y).blue() > 230
    ]
    assert whites, "醒目留言金额未绘制"


def test_superchat_uses_protocol_colors():
    """协议带来的卡片配色优先于默认黄。"""
    wall = Wall()
    wall.add(
        Danmaku(
            type="superchat", name="Carol", content="hi", price=100,
            bg_color_start="#E23D3D", bg_color_end="#9F1922", price_color="#FFF7D6",
        )
    )
    _widget, img = _render(wall)
    # 取卡片右侧空白处的底色(避开头像与文字)
    pixel = img.pixelColor(img.width() - 60, 30)
    assert pixel.red() > 100 and pixel.green() < 130, f"SC 未使用协议配色: {pixel.name()}"


def test_avatar_placeholder_and_pixmap_paths():
    """头像:未就绪时画灰圆+首字,缓存命中时画圆形裁切图片。"""
    from PyQt6.QtGui import QColor, QPixmap

    class FakeAvatars:
        def __init__(self, pix):
            self._pix = pix

        def pixmap(self, url):
            return self._pix

    _app()
    wall = Wall()
    wall.add(Danmaku(type="chat", name="小明", content="hi", avatar=""))
    widget = WallWidget()
    widget.resize(340, 120)
    widget.set_font("Sans Serif", 12)
    widget.set_theme("light")
    widget.update_wall(wall)
    img = widget.grab().toImage()
    grey = [
        (x, y)
        for y in range(6, 32)
        for x in range(10, 34)
        if img.pixelColor(x, y).red() < 120 and img.pixelColor(x, y).blue() < 140
    ]
    assert grey, "头像占位圆未绘制"

    pix = QPixmap(64, 64)
    pix.fill(QColor("#00AEEC"))
    widget.set_avatars(FakeAvatars(pix))
    img2 = widget.grab().toImage()
    blues = [
        (x, y)
        for y in range(6, 32)
        for x in range(10, 34)
        if img2.pixelColor(x, y).blue() > 180 and img2.pixelColor(x, y).red() < 120
    ]
    assert blues, "命中缓存的头像未绘制"



# --- 醒目留言卡片文字对比色 ---


def test_luminance_helper():
    from bilidm_overlay.danmaku.wall import _luminance

    assert _luminance("#FFFFFF") > 0.95
    assert _luminance("#000000") < 0.05
    assert _luminance("#F2C55C") > 0.55  # SC 主题黄:亮底
    assert _luminance("#9F1922") < 0.55  # 深红 SC:暗底
    assert _luminance("bad") == 0.7  # 坏值兜底


def test_sc_text_color_defaults_to_dark_on_bright_card():
    from bilidm_overlay.danmaku.theme import DARK
    from bilidm_overlay.danmaku.wall import sc_text_color

    msg = Danmaku(type="superchat", name="A", content="x", price=30)
    assert sc_text_color(msg, DARK) == DARK.card_text  # 官方 .card-item-* color:#333


def test_sc_text_color_uses_white_on_dark_card():
    from bilidm_overlay.danmaku.theme import DARK
    from bilidm_overlay.danmaku.wall import sc_text_color

    msg = Danmaku(type="superchat", name="A", content="x", price=30, bg_color_start="#9F1922")
    assert sc_text_color(msg, DARK) == "#FFFFFF"


def test_sc_text_color_respects_protocol_price_color():
    from bilidm_overlay.danmaku.theme import DARK
    from bilidm_overlay.danmaku.wall import sc_text_color

    msg = Danmaku(type="superchat", name="A", content="x", price=30, price_color="#123456")
    assert sc_text_color(msg, DARK) == "#123456"



# --- 行首头像对齐:所有消息类型共用同一列、同一垂直中线 ---

AVATAR_PROBE = "#0A58FF"  # 与主题/卡片配色都不撞的纯蓝,便于从像素里认出头像圆


class _FixedAvatars:
    """所有 url 都返回同一张纯色图:头像位置可由像素反查,无需真实下载。"""

    def pixmap(self, url):
        from PyQt6.QtGui import QColor, QPixmap

        pix = QPixmap(48, 48)
        pix.fill(QColor(AVATAR_PROBE))
        return pix


def _bands(ys: list[int]) -> list[tuple[int, int]]:
    """连续行号切成区间(检测"一行文字/一个圆"的纵向范围)。"""
    if not ys:
        return []
    groups = [[ys[0]]]
    for y in ys[1:]:
        if y - groups[-1][-1] <= 1:
            groups[-1].append(y)
        else:
            groups.append([y])
    return [(group[0], group[-1]) for group in groups]


def _avatar_boxes(img) -> list[tuple[int, int, int, int]]:
    """纯蓝头像圆的包围盒:所有行,按 y 分成若干块。"""
    rows = [
        y
        for y in range(img.height())
        if any(
            img.pixelColor(x, y).blue() > 170 and img.pixelColor(x, y).red() < 90
            for x in range(img.width() // 2)
        )
    ]
    boxes = []
    for top, bottom in _bands(rows):
        xs = [
            x
            for x in range(img.width() // 2)
            if any(
                img.pixelColor(x, y).blue() > 170 and img.pixelColor(x, y).red() < 90
                for y in range(top, bottom + 1)
            )
        ]
        boxes.append((min(xs), max(xs), top, bottom))
    return boxes


def test_avatar_column_is_shared_by_all_row_kinds():
    """头像错位回归:普通行 / 醒目留言卡片 / 礼物行必须落在同一条竖列上。

    曾经的 bug:SC 卡片额外内缩 5px,并且垂直基准多减/多加一次 ROW_PAD,
    于是头像整列在 SC 行上下右三个方向各偏移 5px,肉眼就是"头像区域明显错位"。
    """
    wall = Wall()
    wall.add(Danmaku(type="chat", name="Alice", content="在吗"))
    wall.add(Danmaku(type="superchat", name="Carol", content="加油!", price=39))
    wall.add(Danmaku(type="gift", name="Bob", item="辣条", num=20))
    wall.add(Danmaku(type="chat", name="Dave", content="又来一条"))
    widget, img = _render(wall, avatars=_FixedAvatars())
    assert widget.row_count() == 4
    boxes = _avatar_boxes(img)
    assert len(boxes) == 4, f"应画出 4 个头像圆,实际 {boxes}"
    lefts = {box[0] for box in boxes}
    rights = {box[1] for box in boxes}
    assert len(lefts) == 1 and len(rights) == 1, f"头像横向未对齐(各列不同):{boxes}"


def test_avatar_is_vertically_centered_on_first_text_line():
    """头像中线要对齐该行正文首行的中线(误差 ≤1px),含多行折行的行。"""
    wall = Wall()
    wall.add(Danmaku(type="chat", name="Alice", content="在吗"))
    wall.add(Danmaku(type="superchat", name="Carol", content="加油!", price=39))
    wall.add(Danmaku(type="chat", name="Bob", content=LONG_TEXT))  # 多行折行
    wall.add(Danmaku(type="gift", name="Bob", item="辣条", num=20))
    widget, img = _render(wall, h=520, avatars=_FixedAvatars())
    boxes = _avatar_boxes(img)
    assert len(boxes) == 4

    # 逐行算出"行块顶 + ROW_PAD + 行框高/2"(= 正文首行中线),与头像中线比对
    centers = []
    y = PANEL_PAD_Y
    for row in wall.snapshot():
        _lines, height = widget._prepare(row, widget._text_width())
        centers.append(y + ROW_PAD + widget._line_height() / 2)
        y += height + 2 * ROW_PAD
    for (_left, _right, top, bottom), center in zip(boxes, centers):
        avatar_center = (top + bottom) / 2
        assert abs(avatar_center - center) <= 1.5, (
            f"头像中线 {avatar_center}px 未对齐正文首行中线 {center}px"
        )
