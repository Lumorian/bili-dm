"""悬浮窗:基于 kotonoha.platform 的 Wayland layer-shell 装配。"""

from __future__ import annotations

import logging

from kotonoha.platform import (
    DefaultOverlayPlatformFactory,
    LayerShellController,
    QtWindowHost,
    WindowPolicy,
    default_package_dir,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMenu,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .config import Config
from .danmaku.lifecycle import Wall
from .danmaku.model import Danmaku
from .danmaku.wall import WallWidget

logger = logging.getLogger(__name__)

RENDER_INTERVAL_MS = 30


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
        self.set_passthrough(self._passthrough)
        # make_overlay 把窗口提升为 layer-shell 表面:不调用时在 niri/KWin 上只是普通
        # 顶层窗,会被聚焦窗口盖住,失去"悬浮在弹幕内容之上"的意义。kotonoha 自身在首
        # 次 show() 前调用 activate()。offscreen 下即便通用适配器是 no-op 也会在后续
        # show() 崩溃,故仅在 Wayland 会话激活。
        if QGuiApplication.platformName().startswith("wayland"):
            result = self._platform.activate()
            if not result.succeeded:
                logger.debug("layer-shell activation skipped: %s", result.reason or "no reason given")

        self._wall_widget = WallWidget(self)
        self._wall_widget.set_font(cfg.font_family, cfg.font_size)
        self._wall_widget.set_panel_opacity(cfg.opacity)
        self._wall_widget.set_show_tag(show_tag)
        self._status_label = QLabel("", self)
        self._status_label.setStyleSheet("color: #9AA0A6; font-size: 11px; padding-left: 6px;")
        self._status_label.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._wall_widget)
        layout.addWidget(self._status_label)

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
        self._passthrough = on
        self._host.apply_window_policy(
            WindowPolicy(
                transparent_for_input=on,
                mouse_events_transparent=on,
                does_not_accept_focus=True,
                recreate_surface=True,
            )
        )
        # Qt keeps the WindowTransparentForInput window flag in sync with the
        # WA_TransparentForMouseEvents attribute. apply_window_policy sets the
        # flags while the attribute is still on (it is cleared afterwards), so
        # turning passthrough off leaves the input-transparency bit set and the
        # window stays click-through. Clear it now that the attribute is off.
        if not on:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowTransparentForInput)

    def show_window(self) -> None:
        self.show()

    def hide_window(self) -> None:
        self.hide()

    # --- 内部 ---
    def _now(self) -> float:
        import time as _t

        return _t.monotonic()

    def _tick(self) -> None:
        self._wall.prune(self._now())
        self._wall_widget.update_wall(self._wall, self._now())
        if self._cfg.hide_when_idle_seconds and self.row_count() == 0:
            self.hide_window()

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
            size, opacity, rows = dialog.values()
            self._cfg.font_size, self._cfg.opacity, self._cfg.max_rows = size, opacity, rows
            self._wall_widget.set_font(self._cfg.font_family, size)
            self._wall_widget.set_panel_opacity(opacity)
            # v1:行数上限即时生效,当前行清空重来;配置持久化到 yaml 属后续迭代
            self._wall = Wall(max_rows=rows, ttl=self._cfg.ttl_seconds)
