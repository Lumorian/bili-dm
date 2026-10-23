"""悬浮窗:基于 kotonoha.platform 的 Wayland layer-shell 装配。"""

from __future__ import annotations

import logging
import time

from kotonoha.icons import lock_icon, settings_icon
from kotonoha.platform import (
    DefaultOverlayPlatformFactory,
    LayerShellController,
    QtWindowHost,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
    default_package_dir,
)
from kotonoha.platform.overlay_contracts import DragMode
from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QStyle,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .config import Config, save
from .danmaku.avatars import AvatarCache
from .danmaku.composer import Composer
from .danmaku.echo import EchoTracker
from .danmaku.lifecycle import Wall
from .danmaku.model import Danmaku
from .danmaku.theme import panel_rgb, theme_for
from .danmaku.wall import PANEL_RADIUS, WallWidget
from .keyboard import apply_keyboard_interactivity
from .layershell_qt_compat import ensure_for_session
from .roomstats import RoomStats, format_count
from .sender import parse_csrf, pick_observed_room, split_room, validate_text
from .submit import DanmakuSubmitter, Identity, target_for

logger = logging.getLogger(__name__)

RENDER_INTERVAL_MS = 30
MIN_W = 280
MIN_H = 160
RESIZE_GRAB_PX = 14  # 右下角缩放手柄边长

# 右上角控制按钮:kotonoha 同款圆形玻璃态(22×22、11px 圆角)
CONTROL_ICON_COLOR = "#9AA0A6"
CONTROL_BUTTON_STYLE = """
QToolButton {
    background: rgba(255, 255, 255, 28);
    color: rgba(255, 255, 255, 210);
    border: none;
    border-radius: 11px;
    font-size: 13px;
}
QToolButton:hover { background: rgba(255, 255, 255, 60); }
QToolButton:pressed { background: rgba(255, 255, 255, 90); }
"""


class DanmakuWindow(QWidget):
    show_online_changed = pyqtSignal(bool)

    def __init__(self, cfg: Config, room_filter: str | None = None, show_tag: bool = False) -> None:
        super().__init__()
        self._cfg = cfg
        # per-room 传进来的可能是 "platform:rid:cookie";过滤键只用前两段,
        # 否则带 cookie 启动的窗口既收不到弹幕,在线徽标也会一直空着。
        if room_filter:
            platform, rid, _ = split_room(room_filter)
            room_filter = f"{platform}:{rid}" if platform and rid else room_filter
        self._room_filter = room_filter
        self._wall = Wall(max_rows=cfg.max_rows)
        self._last_feed: float | None = None  # 最后一条弹幕的单调时钟(空闲隐藏用)
        self._passthrough = cfg.click_through
        self._status = ""
        # 右上角在线徽标:数据由 main 里的 RoomStatsPoller 统一喂给所有窗口
        self._show_online = bool(getattr(cfg, "show_online", True))
        self._room_stats: dict[str, RoomStats] = {}
        # 从流动的弹幕里学到的房间(platform:rid)。没有 --room/配置时,这是唯一
        # 知道"该发到哪"的来源:能收到弹幕就说明房间是活着的、合法的。
        self._observed_room: str | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(RENDER_INTERVAL_MS)

        self.setWindowTitle("Bilidm Overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 系统 layer-shell-qt 与 PyQt6 wheel 的 Qt 大版本 ABI 不一致时,桥会加载失败,
        # layer-shell 能力整体消失(窗口退化成普通顶层窗:拖不动/不穿透/不定位)。
        # 这一步在桥 dlopen 之前补上兼容库,详见 layershell_qt_compat。
        ensure_for_session(QGuiApplication.platformName())
        desktop = QGuiApplication.instance().property("xdg_current_desktop") or ""
        controller = LayerShellController(
            default_package_dir(), QGuiApplication.platformName(), desktop
        )
        self._host = QtWindowHost(self)
        self._platform = DefaultOverlayPlatformFactory(controller)(self._host)
        self._platform.prepare()
        capabilities = self._platform.capabilities
        if not capabilities.layer_shell:
            # 退化路径必须说清楚,否则用户只看到"拖不动、不穿透"却不知为何:
            # Wayland 的普通顶层窗由合成器排布,客户端既不能定位也不能自绘穿透。
            logger.warning(
                "layer-shell 不可用(退化为普通窗口,无法拖动/穿透/定位):%s",
                capabilities.layer_shell_reason or "原因未知",
            )
        elif not capabilities.client_positioning:
            logger.warning(
                "本次会话不允许客户端定位窗口,拖动与位置记忆不可用:%s",
                capabilities.client_positioning_reason or "原因未知",
            )
        # 控制栏先建好,set_passthrough 才能同步锁按钮的图标/可见性
        self._control_bar = self._build_controls()
        # make_overlay 把窗口提升为 layer-shell 表面:不调用时在 niri/KWin 上只是普通
        # 顶层窗,会被聚焦窗口盖住,失去"悬浮在弹幕内容之上"的意义。kotonoha 自身在首
        # 次 show() 前调用 activate()。offscreen 下即便通用适配器是 no-op 也会在后续
        # show() 崩溃,故仅在 Wayland 会话激活。
        if QGuiApplication.platformName().startswith("wayland"):
            result = self._platform.activate()
            if not result.succeeded:
                logger.debug(
                    "layer-shell activation skipped: %s", result.reason or "no reason given"
                )
        # 表面(层壳角色)就绪后再设穿透:经输入区域切换,而不是重建表面
        self.set_passthrough(self._passthrough)

        self._layer_pos = self._usable_position(cfg.position[0], cfg.position[1])
        # 位置记忆:layer-shell 下 w.move() 是 no-op,只能经桥的锚点设一次。不设的话
        # 不但恢复不了上次的位置,拖动的基线也停在 (0,0)——第一次按下拖动整块面板
        # 会直接跳走(位移被算成从原点起的绝对坐标)。
        if capabilities.client_positioning:
            moved = self._platform.move_to(
                WindowPoint(self._layer_pos.x(), self._layer_pos.y())
            )
            if not moved.succeeded:
                logger.debug("位置恢复跳过:%s", moved.reason or "原因未知")
        self._dragging = False
        self._resizing = False
        self._drag_origin_global = QPoint()  # 按下时的全局指针
        self._drag_origin_pos = QPoint()  # 按下时的窗口位置
        self._resize_start: tuple[QPoint, QPoint] | None = None  # (按下点, 原尺寸)

        self._wall_widget = WallWidget(self)
        self._wall_widget.set_font(cfg.font_family, cfg.font_size)
        self._wall_widget.set_theme(getattr(cfg, "theme", "dark"))
        self._wall_widget.set_show_tag(show_tag)
        self._avatars = AvatarCache(self)
        self._avatars.loaded.connect(self._on_avatars_loaded)
        self._wall_widget.set_avatars(self._avatars)
        self._status_label = QLabel("", self)
        self._status_label.setStyleSheet("color: #9AA0A6; font-size: 11px; padding-left: 6px;")
        self._status_label.setVisible(False)

        # 发弹幕:输入条贴在卡片底边(官方面板输入条的位置),回显去重负责
        # 不让"本地插一行 + ws 再推一行"变成两条。
        self._composer = Composer(self, theme=getattr(cfg, "theme", "dark"))
        self._composer.set_font(cfg.font_family, cfg.font_size)
        self._composer.submitted.connect(self._on_submit)
        # 初始锁定态跟随窗口:set_passthrough 在构造时已经跑过一遍(那时输入条还不存在)
        self._composer.set_locked(self._passthrough)
        self._send_enabled = bool(getattr(cfg, "send_enabled", True))
        self._composer.setVisible(self._send_enabled)
        self._echo = EchoTracker()
        self._submitter = DanmakuSubmitter()
        self._submitter.submitted_ok.connect(self._on_sent)
        self._submitter.failed.connect(self._on_send_failed)

        # 按钮带 + 弹幕墙包进同一容器(间距 0):带底色与卡片一致,按钮落在卡片内部
        # 右上角,随卡片高度变化整体移动——kotonoha 同款"控制条在卡片内"结构。
        self._container = QWidget(self)
        card_layout = QVBoxLayout(self._container)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card_layout.addWidget(self._control_bar)
        card_layout.addWidget(self._wall_widget)
        card_layout.addWidget(self._composer)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._container)
        layout.addWidget(self._status_label)
        # 卡片背景(圆角半透明)由容器 QSS 统一绘制,子控件保持透明
        self._apply_card_background(self._cfg.opacity)

        self._tray: QSystemTrayIcon | None = None
        if not cfg.no_tray:
            self._setup_tray()

    # --- 对外接口 ---
    def feed(self, d: Danmaku) -> None:
        if d.platform and d.rid:
            # 记下正在流动的房间:发弹幕时若没有更确定的来源(per-room 窗口/配置房间),
            # 就发回这里 —— 收到弹幕本身就证明它可用。多房间时不让目标来回跳(见
            # pick_observed_room)。
            self._observed_room = pick_observed_room(
                self._observed_room, f"{d.platform}:{d.rid}"
            )
        if self._room_filter is not None:
            key = f"{d.platform}:{d.rid}"
            if d.rid and d.platform and key != self._room_filter:
                return
        # 自己刚发的那条已经本地回显过,ws 再推进来一次就重复了
        echo = getattr(self, "_echo", None)
        if echo is not None and echo.consume(d):
            self._last_feed = time.monotonic()
            return
        self._wall.add(d)
        self._last_feed = time.monotonic()
        # 同步推给绘制 widget:_tick 只在事件循环里跑,同步测试无法先等到下一帧
        self._wall_widget.update_wall(self._wall)
        self.set_status("")
        if not self.isVisible():
            self.show()

    def row_count(self) -> int:
        return self._wall_widget.row_count()

    # --- 翻阅历史 ---
    def scroll_by(self, delta: float) -> None:
        """正 delta = 往上看更旧的内容(滚轮/PageUp 都走这里)。"""
        self._wall_widget.scroll_by(delta)

    def scroll_to_bottom(self) -> None:
        """回到最新(底部)。"""
        self._wall_widget.scroll_to_bottom()

    def scroll_to_top(self) -> None:
        """翻到最旧一条。"""
        self._wall_widget.scroll_to_top()

    def is_following_latest(self) -> bool:
        return self._wall_widget.is_following()

    def scroll_offset(self) -> float:
        return self._wall_widget.scroll_offset()

    def status_text(self) -> str:
        return self._status

    def set_status(self, text: str) -> None:
        self._status = text
        self._status_label.setVisible(bool(text))
        self._status_label.setText(text)

    # --- 在线人数徽标 ---
    def set_room_stats(self, stats: dict[str, RoomStats]) -> None:
        """喂入最新一轮直播间快照(main 的 poller 广播给所有窗口)。"""
        self._room_stats = dict(stats or {})
        self._refresh_stats_label()

    def set_show_online(self, enabled: bool) -> None:
        """设置里开关在线徽标;关掉后 main 侧也会停掉轮询(经信号)。"""
        enabled = bool(enabled)
        changed = enabled != self._show_online
        self._show_online = enabled
        self._refresh_stats_label()
        if changed:
            self.show_online_changed.emit(enabled)

    def _visible_stats(self) -> list[RoomStats]:
        """当前窗口该显示哪些房间:per-room 只看自己,merged 看所有已知房间。"""
        stats = list(self._room_stats.values())
        if self._room_filter:
            stats = [s for s in stats if s.key == self._room_filter]
        # 正在直播的排前面;同一状态按房间号稳定排序,避免刷新时顺序抖动
        return sorted(stats, key=lambda s: (not s.live, s.key))

    def _refresh_stats_label(self) -> None:
        label = getattr(self, "_stats_label", None)
        if label is None:
            return
        stats = self._visible_stats() if self._show_online else []
        if not stats:
            label.setVisible(False)
            label.setText("")
            label.setToolTip("")
            return
        theme = theme_for(getattr(self._cfg, "theme", "dark"))
        muted = "#9AA0A6" if theme.name == "dark" else "#61666D"
        label.setStyleSheet(f"color: {muted}; font-size: 11px;")
        label.setText(self._stats_html(stats, theme.brand_pink))
        label.setToolTip(self._stats_tooltip(stats))
        label.setVisible(True)

    @staticmethod
    def _stats_html(stats: list[RoomStats], live_color: str) -> str:
        """一行式徽标:单房间精确到在线数,多房间给直播数与在线总数。"""
        live = [s for s in stats if s.live]
        if len(stats) == 1:
            one = stats[0]
            color = live_color if one.live else "#757A81"
            detail = f" · {one.online_label}" if one.online_label else ""
            return f'<span style="color:{color};">●</span> {one.status_text}{detail}'
        if not live:
            return f'<span style="color:#757A81;">○</span> {len(stats)} 个直播间均未开播'
        known = [s.online for s in live if s.online is not None]
        detail = f" · 在线 {format_count(sum(known))}" if known else ""
        return (
            f'<span style="color:{live_color};">●</span> {len(live)} 个直播间直播中'
            f"{detail}"
        )

    @staticmethod
    def _stats_tooltip(stats: list[RoomStats]) -> str:
        """悬停看房间标题/分区/人气/粉丝数;数字和在线标签同一套缩写。"""
        blocks: list[str] = []
        for s in stats:
            name = s.uname or s.rid
            head = f"{name} · {s.status_text}"
            lines = [head]
            if s.title:
                lines.append(s.title)
            if s.area:
                lines.append(f"分区:{s.area}")
            if s.live:
                if s.online_text:
                    lines.append(f"在线用户:{s.online_text}")
                elif s.online is not None:
                    lines.append(f"在线用户:{s.online}")
                if s.popularity:
                    lines.append(f"人气:{format_count(s.popularity)}")
            if s.attention:
                lines.append(f"粉丝:{format_count(s.attention)}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def set_passthrough(self, on: bool) -> None:
        """锁定=除按钮带外全窗口点击穿透;解锁=窗口全区域可交互(拖动/缩放)。

        切换经 layer-shell 输入区域(而非重建表面):setWindowFlags 会销毁原生
        wl_surface,重建的新表面未经过 make_overlay(),失去 layer-shell 角色后
        窗口从屏幕上消失——kotonoha 同款 set_input_region 语义。锁定态保留按钮带
        可点击,锁/设置按钮始终可达,解锁不依赖托盘。
        """
        self._passthrough = on
        result = self._platform.set_input_region(self._input_region())
        if not result.succeeded:
            # 无层壳输入区域能力时退回 Qt 属性级穿透(不重建表面)
            self._host.apply_window_policy(
                WindowPolicy(
                    transparent_for_input=on,
                    mouse_events_transparent=on,
                    # 锁定(穿透)态不该抢焦点;解锁后要能打字,必须允许接受焦点
                    does_not_accept_focus=on,
                    recreate_surface=False,
                )
            )
        # 键盘交互跟随锁定态:层壳表面的 KeyboardInteractivityNone 让输入框永远拿不到
        # 按键,解锁(可交互)时才打开;锁定态关回去,别去抢聚焦窗口的输入。
        self._apply_keyboard(not on)
        composer = getattr(self, "_composer", None)
        if composer is not None:
            composer.set_locked(on)
        self._update_lock_icon()

    def _input_region(self) -> WindowRectangle | None:
        """当前穿透态对应的输入区域(窗口坐标系):
        锁定=仅按钮带矩形可点,其余点击穿透;解锁=整个窗口。"""
        if self._passthrough:
            top_left = self._control_bar.mapTo(self, QPoint(0, 0))
            return WindowRectangle(
                top_left.x(),
                top_left.y(),
                self._control_bar.width(),
                self._control_bar.height(),
            )
        return WindowRectangle(0, 0, self.width(), self.height())

    def resizeEvent(self, event) -> None:
        """输入区域是固定矩形,需跟随窗口/按钮带几何变化刷新。"""
        super().resizeEvent(event)
        self._platform.set_input_region(self._input_region())

    def show_window(self) -> None:
        self.show()

    def hide_window(self) -> None:
        self.hide()

    # --- 鼠标交互:非穿透时拖动/右下角缩放手柄 ---
    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and not self._passthrough and a0.button() == Qt.MouseButton.LeftButton:
            pos = a0.position().toPoint()
            if self._in_resize_grab(pos):
                self._resizing = True
                self._resize_start = (pos, self.size())
                a0.accept()
                return
            gp = a0.globalPosition().toPoint()
            result = self._platform.begin_drag(
                WindowPoint(pos.x(), pos.y()),
                WindowPoint(gp.x(), gp.y()),
            )
            if result.mode is not DragMode.MANUAL:
                super().mousePressEvent(a0)
                return
            self._dragging = True
            self._drag_origin_global = gp
            self._drag_origin_pos = QPoint(self._layer_pos)
            a0.accept()
            return
        super().mousePressEvent(a0)

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            super().mouseMoveEvent(a0)
            return
        if self._resizing and a0.buttons() & Qt.MouseButton.LeftButton:
            pos = a0.position().toPoint()
            start_pos, orig_size = self._resize_start
            w = max(MIN_W, orig_size.width() + pos.x() - start_pos.x())
            h = max(MIN_H, orig_size.height() + pos.y() - start_pos.y())
            self.resize(w, h)
            a0.accept()
            return
        if self._dragging and a0.buttons() & Qt.MouseButton.LeftButton:
            local = a0.position().toPoint()
            gp = a0.globalPosition().toPoint()
            # 位置记忆:layer-shell 下合成器不接受客户端查询(win.pos() 永远报请求值),
            # 只能自己算。拖动是"窗口跟手"的一比一映射,所以终点就是
            # "按下时的位置 + 指针从按下到现在的位移"——用指针位移而不是本地坐标增量:
            # 面板跟着指针走时本地坐标几乎不动,拿它累计会一路少算甚至原地不动。
            self._layer_pos = self._drag_origin_pos + (gp - self._drag_origin_global)
            self._platform.update_drag(
                WindowPoint(local.x(), local.y()),
                WindowPoint(gp.x(), gp.y()),
            )
            a0.accept()
            return
        super().mouseMoveEvent(a0)

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        if self._resizing:
            self._resizing = False
            self._resize_start = None
            self._save_geometry()
            a0.accept()
            return
        if self._dragging:
            self._dragging = False
            self._platform.end_drag()
            if self._platform.capabilities.client_positioning:
                self._save_geometry()
            a0.accept()
            return
        super().mouseReleaseEvent(a0)

    def keyPressEvent(self, a0) -> None:
        """翻阅历史的键盘入口:PageUp/PageDown 一屏,Home/End 到两端。

        只在解锁(窗口可交互)时成立:锁定态整个窗口在往外放行输入,按键本来
        就到这里了才会被处理 —— 不会抢下层窗口的键。
        """
        key = a0.key() if a0 is not None else None
        if key is None:
            super().keyPressEvent(a0)
            return
        page = max(40.0, self._wall_widget.height() - 40.0)
        if key == Qt.Key.Key_PageUp:
            self.scroll_by(page)
        elif key == Qt.Key.Key_PageDown:
            self.scroll_by(-page)
        elif key == Qt.Key.Key_Home:
            self._wall_widget.scroll_to_top()
        elif key == Qt.Key.Key_End:
            self.scroll_to_bottom()
        else:
            super().keyPressEvent(a0)
            return
        a0.accept()

    def _usable_position(self, x: int, y: int) -> QPoint:
        """把存下来的位置收进"看得见"的范围。

        位置是拖出来的,而拖动曾经算错(见 mouseMoveEvent):历史配置里可能留有几十万
        的坐标。启动时照搬这种值会把面板放到屏幕外——对用户来说就是"窗口彻底不见了",
        比位置不准更糟。落在所有屏幕之外时退回配置里的默认锚点,并提示一句。"""
        point = QPoint(x, y)
        screens = QGuiApplication.screens()
        if not screens:
            return point
        for screen in screens:
            if screen.geometry().contains(point):
                return point
        # 允许面板有一部分伸到屏幕外(贴边),但左上角必须落在某块屏幕内。
        fallback = QPoint(24, 100)
        logger.warning("配置里的位置 (%d, %d) 不在任何屏幕内,退回 %s", x, y, fallback)
        return fallback

    def _in_resize_grab(self, pos: QPoint) -> bool:
        """右下角缩放手柄命中区(无可见手柄,拖拽手感与原来一致)。"""
        return (
            pos.x() >= self.width() - RESIZE_GRAB_PX and pos.y() >= self.height() - RESIZE_GRAB_PX
        )

    def _save_geometry(self) -> None:
        self._cfg.position = [self._layer_pos.x(), self._layer_pos.y()]
        self._cfg.width, self._cfg.height = self.width(), self.height()
        save(self._cfg)

    def _build_controls(self) -> QWidget:
        """右上角按钮带:[🔒 锁][⚙ 设置],与卡片一体;kotonoha 同款圆形玻璃按钮。

        锁=点击穿透开关;按钮带在锁定态也保持可见/可点(set_passthrough 的输入区域
        只放行按钮带矩形),解锁与设置永远可以从窗口直达,不依赖托盘。解锁后左键
        拖动移动、右下角缩放手柄均可用(见 mousePressEvent 等)。
        """
        bar = QWidget(self)
        # 垂直方向固定为内容高:默认 Preferred 会随卡片一起拉伸,带子被对半分
        # (实测 196px),按钮因此悬浮在卡片中部——kotonoha 的按钮必须贴在卡片顶。
        bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 6, 10, 0)  # 上 6px、左右 10px 留白
        layout.setSpacing(6)
        # 左侧在线徽标(直播中/未开播 + 当前在线用户);没数据时隐藏,不占视觉
        self._stats_label = QLabel("", bar)
        self._stats_label.setTextFormat(Qt.TextFormat.RichText)
        self._stats_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._stats_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self._stats_label.setVisible(False)
        layout.addWidget(self._stats_label)
        layout.addStretch(1)  # 徽标贴左、按钮组贴右(右上角)

        self._lock_btn = self._make_control_button(bar)
        self._lock_btn.clicked.connect(lambda: self.set_passthrough(not self._passthrough))

        self._settings_btn = self._make_control_button(bar)
        self._settings_btn.setIcon(settings_icon(CONTROL_ICON_COLOR))
        self._settings_btn.setToolTip("设置")
        self._settings_btn.clicked.connect(self._open_settings)

        layout.addWidget(self._lock_btn)
        layout.addWidget(self._settings_btn)
        # 按钮带不画背景:卡片暗底由容器统一绘制(QSS),与弹幕卡片连成一块
        self._update_lock_icon()
        return bar

    def _apply_card_background(self, opacity: float) -> None:
        """给卡片容器填上圆角半透明底色(QSS 绘制,子控件保持透明)。

        底色取当前主题的官方令牌(深色 `--bg2:#101011` / 浅色 `#F6F7F8`,见
        danmaku/theme.py)。QSS 无选择器声明只作用于容器自身;窗口已设
        WA_TranslucentBackground,四角默认透明,视觉上就是圆角卡片。圆角值与
        niri layer-rule 的 geometry-corner-radius 保持同步(见 danmaku/wall.py)。
        """
        r, g, b = panel_rgb(getattr(self._cfg, "theme", "dark"))
        self._container.setStyleSheet(
            f"background: rgba({r}, {g}, {b}, {opacity});"
            f" border-radius: {PANEL_RADIUS}px;"
        )

    def _make_control_button(self, parent: QWidget) -> QToolButton:
        button = QToolButton(parent)
        button.setFixedSize(22, 22)
        button.setIconSize(QSize(15, 15))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(CONTROL_BUTTON_STYLE)
        return button

    def _update_lock_icon(self) -> None:
        """按 passthrough 状态刷新锁按钮:锁定=闭锁图标+「已锁定」,解锁=开锁+「已解锁」。"""
        lock = getattr(self, "_lock_btn", None)
        if lock is None:
            return
        lock.setIcon(lock_icon(self._passthrough, CONTROL_ICON_COLOR))
        lock.setToolTip("已锁定" if self._passthrough else "已解锁")

    # --- 发弹幕 ---
    def _apply_keyboard(self, enabled: bool) -> None:
        """把键盘交互交给平台桥(层壳表面默认收不到按键,见 keyboard 模块)。

        只在解锁(可交互)时打开:锁定态窗口整块在往外放行鼠标,这时抢键盘焦点
        只会把用户正在打字的别的窗口顶掉。
        """
        apply_keyboard_interactivity(self._platform, self._host, enabled)

    def set_send_enabled(self, enabled: bool) -> None:
        """显示/隐藏底部发送栏(设置对话框里的开关,即时生效)。"""
        self._send_enabled = enabled
        self._composer.setVisible(enabled)
        if enabled:
            self._composer.set_locked(self._passthrough)

    def composer(self) -> Composer:
        return self._composer

    def _on_submit(self, text: str) -> None:
        """发送栏点了发送:先在本地说清楚"发不了"的原因,再交给后台线程。"""
        text = text.strip()
        problem = validate_text(text)
        if problem:
            self._composer.flash(problem, error=True)
            return
        # 房间来源:per-room 窗口绑定的房间 → 配置里的房间 → 正在收弹幕的这个房间。
        # 最后一档是必须的:房间是 dmnotifier 订阅的,overlay 完全可以没有任何 --room
        # 配置却在收弹幕,此时不让发毫无道理。
        target = target_for(self._cfg, self._room_filter, self._observed_room)
        if target is None:
            self._composer.flash(
                "还没收到过弹幕,不知道发到哪个房间:先在设置里添加直播间", error=True
            )
            return
        if target.platform != "bilibili":
            self._composer.flash(
                f"暂只支持向 B 站直播间发送弹幕(当前 {target.platform})", error=True
            )
            return
        if not parse_csrf(target.cookie):
            # 收弹幕不需要登录(匿名也能看),发弹幕才需要 —— 这一条必须说清,否则
            # "我能看却不能发"看起来像 bug。
            self._composer.flash(
                "看弹幕不用登录,发弹幕需要:设置里填一次登录 cookie(含 bili_jct)", error=True
            )
            return
        # 期望先登记:回推可能比 HTTP 响应先到,晚登记就会漏掉一条去重
        self._echo.expect(text)
        if not self._submitter.submit(target, text):
            self._echo.cancel(text)
            return
        self._composer.set_busy(True)

    def _on_sent(self, text: str, identity: object, target: object) -> None:
        """发送成功:立刻本地回显自己那条(官方弹幕姬同样即时上屏)。"""
        self._composer.set_busy(False)
        self._composer.clear()
        ident = identity if isinstance(identity, Identity) else None
        if ident is not None:
            # 有了 uid,后面的回推就必须 uid 也对上,别把别人的同一句话吞掉
            self._echo.bind_uid(ident.uid)
        own = Danmaku(
            type="chat",
            platform=getattr(target, "platform", "bilibili"),
            rid=getattr(target, "rid", ""),
            name=ident.name if ident is not None else "我",
            content=text,
            uid=ident.uid if ident is not None else "",
            avatar=ident.avatar if ident is not None else "",
        )
        # 直接入墙,不走 feed():feed 会拿这条去抵扣它自己的那条期望记录
        self._wall.add(own)
        self._last_feed = time.monotonic()
        self._wall_widget.update_wall(self._wall)
        if not self.isVisible():
            self.show()
        self._composer.flash("已发送")

    def _on_send_failed(self, text: str, message: str) -> None:
        self._composer.set_busy(False)
        self._echo.cancel(text)
        self._composer.flash(message, error=True)

    # --- 内部 ---
    def _tick(self) -> None:
        # 无时间淡出:画面只在有新弹幕时变化;定时器仅服务"无新消息"空闲自动隐藏
        idle = self._cfg.hide_when_idle_seconds
        if not idle:
            return
        if not self._wall_widget.is_following():
            # 用户正在往上翻历史:这时候隐藏窗口等于把书合上,必须等他回到底部
            return
        if self._last_feed is None or time.monotonic() - self._last_feed > idle:
            self.hide_window()

    def _on_avatars_loaded(self) -> None:
        """某头像下载完成:重绘面板。"""
        self._wall_widget.update()

    def _setup_tray(self) -> None:
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DesktopIcon)
        self._tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        toggle = menu.addAction("切换点击穿透")
        toggle.setCheckable(True)
        toggle.setChecked(self._passthrough)
        toggle.setToolTip("开启后鼠标可穿过悬浮窗;关闭后窗口可拖拽")
        toggle.triggered.connect(lambda on: self.set_passthrough(on))
        latest_action = menu.addAction("回到最新弹幕")
        latest_action.triggered.connect(self.scroll_to_bottom)
        settings_action = menu.addAction("设置…")
        settings_action.triggered.connect(self._open_settings)
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(QApplication.instance().quit)
        self._tray.setContextMenu(menu)
        self._tray.show()

    def _open_settings(self) -> None:
        from .settings import SettingsDialog

        dialog = SettingsDialog(self, self._cfg)
        if dialog.exec():
            (size, opacity, rows, width, height, mode, theme, show_online) = dialog.values()
            send_enabled, send_cookie = dialog.send_values()
            (
                self._cfg.font_size,
                self._cfg.opacity,
                self._cfg.max_rows,
                self._cfg.width,
                self._cfg.height,
                self._cfg.mode,
                self._cfg.theme,
                self._cfg.show_online,
                self._cfg.send_enabled,
                self._cfg.send_cookie,
            ) = (
                size,
                opacity,
                rows,
                width,
                height,
                mode,
                theme,
                show_online,
                send_enabled,
                send_cookie,
            )
            self._wall_widget.set_font(self._cfg.font_family, size)
            self._wall_widget.set_theme(self._cfg.theme)
            self._composer.set_theme(self._cfg.theme)
            self._composer.set_font(self._cfg.font_family, size)
            self._refresh_stats_label()  # 主题切换后徽标文字色跟上
            self.set_show_online(show_online)
            self.set_send_enabled(send_enabled)
            self._apply_card_background(opacity)
            # 行数上限变更即时生效;行数变更清空重来(与 v1 约定一致)
            self._wall = Wall(max_rows=rows)
            self._wall_widget.update_wall(self._wall)  # 换墙会顺带把滚动偏移清零
            self.resize(width, height)
            save(self._cfg)
