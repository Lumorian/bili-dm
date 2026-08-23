"""悬浮窗:基于 kotonoha.platform 的 Wayland layer-shell 装配。"""

from __future__ import annotations

import logging

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
from PyQt6.QtCore import QPoint, QSize, Qt, QTimer
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
from .danmaku.lifecycle import Wall
from .danmaku.model import Danmaku
from .danmaku.wall import PANEL_BG, PANEL_RADIUS, WallWidget

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
    def __init__(self, cfg: Config, room_filter: str | None = None, show_tag: bool = False) -> None:
        super().__init__()
        self._cfg = cfg
        self._room_filter = room_filter
        self._wall = Wall(max_rows=cfg.max_rows, ttl=cfg.ttl_seconds)
        self._passthrough = cfg.click_through
        self._status = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(RENDER_INTERVAL_MS)

        self.setWindowTitle("Bilidm Overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        desktop = QGuiApplication.instance().property("xdg_current_desktop") or ""
        controller = LayerShellController(
            default_package_dir(), QGuiApplication.platformName(), desktop
        )
        self._host = QtWindowHost(self)
        self._platform = DefaultOverlayPlatformFactory(controller)(self._host)
        self._platform.prepare()
        # 控制栏先建好,set_passthrough 才能同步锁按钮的图标/可见性
        self._control_bar = self._build_controls()
        # make_overlay 把窗口提升为 layer-shell 表面:不调用时在 niri/KWin 上只是普通
        # 顶层窗,会被聚焦窗口盖住,失去"悬浮在弹幕内容之上"的意义。kotonoha 自身在首
        # 次 show() 前调用 activate()。offscreen 下即便通用适配器是 no-op 也会在后续
        # show() 崩溃,故仅在 Wayland 会话激活。
        if QGuiApplication.platformName().startswith("wayland"):
            result = self._platform.activate()
            if not result.succeeded:
                logger.debug("layer-shell activation skipped: %s", result.reason or "no reason given")
        # 表面(层壳角色)就绪后再设穿透:经输入区域切换,而不是重建表面
        self.set_passthrough(self._passthrough)

        self._layer_pos = QPoint(cfg.position[0], cfg.position[1])
        self._dragging = False
        self._resizing = False
        self._drag_local = QPoint()
        self._resize_start: tuple[QPoint, QPoint] | None = None  # (按下点, 原尺寸)

        self._wall_widget = WallWidget(self)
        self._wall_widget.set_font(cfg.font_family, cfg.font_size)
        self._wall_widget.set_show_tag(show_tag)
        self._avatars = AvatarCache(self)
        self._avatars.loaded.connect(self._on_avatars_loaded)
        self._wall_widget.set_avatars(self._avatars)
        self._status_label = QLabel("", self)
        self._status_label.setStyleSheet("color: #9AA0A6; font-size: 11px; padding-left: 6px;")
        self._status_label.setVisible(False)

        # 按钮带 + 弹幕墙包进同一容器(间距 0):带底色与卡片一致,按钮落在卡片内部
        # 右上角,随卡片高度变化整体移动——kotonoha 同款"控制条在卡片内"结构。
        self._container = QWidget(self)
        card_layout = QVBoxLayout(self._container)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card_layout.addWidget(self._control_bar)
        card_layout.addWidget(self._wall_widget)

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
        if self._room_filter is not None:
            key = f"{d.platform}:{d.rid}"
            if d.rid and d.platform and key != self._room_filter:
                return
        self._wall.add(d, self._now())
        # 同步推给绘制 widget:_tick 只在事件循环里跑,同步测试无法先等到下一帧
        self._wall_widget.update_wall(self._wall, self._now())
        self.set_status("")
        if not self.isVisible():
            self.show()

    def row_count(self) -> int:
        return self._wall_widget.row_count()

    def status_text(self) -> str:
        return self._status

    def set_status(self, text: str) -> None:
        self._status = text
        self._status_label.setVisible(bool(text))
        self._status_label.setText(text)

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
                    does_not_accept_focus=True,
                    recreate_surface=False,
                )
            )
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
            self._drag_local = pos
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
            # 位置记忆:layer-shell 下合成器不接受客户端查询,用本地累计
            self._layer_pos += local - self._drag_local
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

    def _in_resize_grab(self, pos: QPoint) -> bool:
        """右下角缩放手柄命中区(无可见手柄,拖拽手感与原来一致)。"""
        return pos.x() >= self.width() - RESIZE_GRAB_PX and pos.y() >= self.height() - RESIZE_GRAB_PX

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
        layout.setContentsMargins(0, 6, 10, 0)  # 上 6px、右 10px 留白,按钮不贴卡片顶/右缘
        layout.setSpacing(6)
        layout.addStretch(1)  # 先前置 stretch,按钮组整体贴右缘(右上角)

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
        """给卡片容器填上圆角半透明深色背景(QSS 绘制,子控件保持透明)。

        QSS 无选择器声明只作用于容器自身;窗口已设 WA_TranslucentBackground,
        四角默认透明,视觉上就是圆角卡片。圆角值与 niri layer-rule 的
        geometry-corner-radius 保持同步(见 danmaku/wall.py PANEL_RADIUS)。
        """
        self._container.setStyleSheet(
            f"background: rgba({PANEL_BG[0]}, {PANEL_BG[1]}, {PANEL_BG[2]}, {opacity});"
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

    # --- 内部 ---
    def _now(self) -> float:
        import time as _t

        return _t.monotonic()

    def _tick(self) -> None:
        self._wall.prune(self._now())
        self._wall_widget.update_wall(self._wall, self._now())
        if self._cfg.hide_when_idle_seconds and self.row_count() == 0:
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
            (size, opacity, rows, ttl, width, height, mode) = dialog.values()
            (
                self._cfg.font_size,
                self._cfg.opacity,
                self._cfg.max_rows,
                self._cfg.ttl_seconds,
                self._cfg.width,
                self._cfg.height,
                self._cfg.mode,
            ) = (size, opacity, rows, ttl, width, height, mode)
            self._wall_widget.set_font(self._cfg.font_family, size)
            self._apply_card_background(opacity)
            # 行数上限/TTL 变更即时生效;行数变更清空重来(与 v1 约定一致)
            self._wall = Wall(max_rows=rows, ttl=ttl)
            self.resize(width, height)
            save(self._cfg)
