"""设置对话框:房间管理(列表/添加/删除,直调 UniBarrage API)+ 外观与窗口配置。"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .api import UniBarrageAPI, UniBarrageError
from .config import Config

logger = logging.getLogger(__name__)

PLATFORMS = ["bilibili", "douyin", "kuaishou", "douyu", "huya", "xiaohongshu"]


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg: Config, api: UniBarrageAPI | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._api = api or UniBarrageAPI(cfg.api_address, cfg.api_token)
        self._services: list[dict] = []
        self._error: str | None = None
        self.setWindowTitle("设置")
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)

        # --- 订阅(房间)区 ---
        root.addWidget(QLabel("订阅房间(直连 UniBarrage 服务):"))
        self._list = QListWidget(self)
        root.addWidget(self._list, 1)
        row1 = QHBoxLayout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.reload_services)
        row1.addWidget(refresh)
        row1.addStretch(1)
        del_btn = QPushButton("删除选中")
        del_btn.clicked.connect(self.delete_selected)
        row1.addWidget(del_btn)
        root.addLayout(row1)
        row2 = QHBoxLayout()
        self._platform = QComboBox(self)
        self._platform.addItems(PLATFORMS)
        self._rid = QLineEdit(self)
        self._rid.setPlaceholderText("房间号")
        self._cookie = QLineEdit(self)
        self._cookie.setPlaceholderText("cookie(可选)")
        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self.add_room)
        row2.addWidget(self._platform)
        row2.addWidget(self._rid, 2)
        row2.addWidget(self._cookie, 2)
        row2.addWidget(add_btn)
        root.addLayout(row2)
        self._note = QLabel("", self)
        self._note.setStyleSheet("color: #C62828;")
        root.addWidget(self._note)

        # --- 外观区 ---
        form = QFormLayout()
        self._font = QSpinBox(self)
        self._font.setRange(9, 40)
        self._font.setValue(cfg.font_size)
        self._opacity = QDoubleSpinBox(self)
        self._opacity.setRange(0.1, 1.0)
        self._opacity.setSingleStep(0.05)
        self._opacity.setValue(cfg.opacity)
        self._rows = QSpinBox(self)
        self._rows.setRange(5, 200)
        self._rows.setValue(cfg.max_rows)
        self._width = QSpinBox(self)
        self._width.setRange(280, 2000)
        self._width.setValue(cfg.width)
        self._height = QSpinBox(self)
        self._height.setRange(160, 1200)
        self._height.setValue(cfg.height)
        self._mode = QComboBox(self)
        self._mode.addItems(["merged", "per-room"])
        if cfg.mode in ("merged", "per-room"):
            self._mode.setCurrentText(cfg.mode)
        self._theme = QComboBox(self)
        self._theme.addItems(["dark", "light"])
        if getattr(cfg, "theme", "dark") in ("dark", "light"):
            self._theme.setCurrentText(cfg.theme)
        # --- 发弹幕区 ---
        self._send_enabled = QCheckBox("在卡片底部显示输入条", self)
        self._send_enabled.setChecked(getattr(cfg, "send_enabled", True))
        self._send_cookie = QLineEdit(self)
        self._send_cookie.setPlaceholderText("SESSDATA=…; bili_jct=…(留空则用房间订阅时的 cookie)")
        self._send_cookie.setEchoMode(QLineEdit.EchoMode.Password)
        self._send_cookie.setText(getattr(cfg, "send_cookie", "") or "")
        form.addRow("字号", self._font)
        form.addRow("主题", self._theme)
        form.addRow("透明度", self._opacity)
        form.addRow("墙行数上限", self._rows)
        form.addRow("宽度", self._width)
        form.addRow("高度", self._height)
        form.addRow("窗口模式", self._mode)
        root.addLayout(form)

        # --- 发弹幕区:登录态只用于发送,cookie 里的 bili_jct 同时充当 csrf ---
        root.addWidget(QLabel("发弹幕(需登录 cookie,含 SESSDATA 与 bili_jct):"))
        self._send_enabled.setText("启用发送栏")
        root.addWidget(self._send_enabled)
        cookie_row = QHBoxLayout()
        cookie_row.addWidget(self._send_cookie, 1)
        reveal = QPushButton("显示", self)
        reveal.setCheckable(True)
        reveal.toggled.connect(self._toggle_cookie_visible)
        cookie_row.addWidget(reveal)
        root.addLayout(cookie_row)
        self._send_note = QLabel("", self)
        self._send_note.setStyleSheet("color: #9AA0A6; font-size: 11px;")
        self._send_note.setWordWrap(True)
        root.addWidget(self._send_note)
        self._refresh_send_note()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._send_cookie.textChanged.connect(self._refresh_send_note)
        self.reload_services()

    # --- 房间管理 ---
    def reload_services(self) -> None:
        try:
            self._services = self._api.list_all()
            self._note.setText("")
        except UniBarrageError as exc:
            self._services = []
            self._note.setText(f"刷新失败: {exc}")
            logger.warning("refresh services: %s", exc)
        self._list.clear()
        for svc in self._services:
            item = QListWidgetItem(f"{svc['platform']}  {svc['rid']}")
            item.setData(1, svc)
            self._list.addItem(item)

    def delete_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        svc = item.data(1)
        try:
            self._api.stop(svc["platform"], svc["rid"])
            self.reload_services()
        except UniBarrageError as exc:
            self._note.setText(f"删除失败: {exc}")

    def add_room(self) -> None:
        rid = self._rid.text().strip()
        if not rid:
            self._note.setText("房间号不能为空")
            return
        try:
            self._api.start(self._platform.currentText(), rid, self._cookie.text().strip())
            self._rid.clear()
            self._cookie.clear()
            self.reload_services()
        except UniBarrageError as exc:
            self._note.setText(f"添加失败: {exc}")

    # --- 发弹幕 ---
    def _toggle_cookie_visible(self, show: bool) -> None:
        self._send_cookie.setEchoMode(
            QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        )

    def _refresh_send_note(self) -> None:
        """cookie 缺 bili_jct 时当场说清楚:否则点发送只会收到一个 -111。"""
        from .sender import parse_csrf

        cookie = self._send_cookie.text().strip()
        if not cookie:
            self._send_note.setText(
                "未填 cookie:将沿用 --room 参数里的 cookie,或 dmnotifier history 中该房间的 cookie。"
            )
            return
        if not parse_csrf(cookie):
            self._send_note.setText("cookie 里没有 bili_jct,发不出去:请从浏览器复制完整 cookie。")
            return
        self._send_note.setText("cookie 看起来可用。")

    def send_values(self) -> tuple[bool, str]:
        """发弹幕设置:(启用发送栏, 发送用 cookie)。"""
        return self._send_enabled.isChecked(), self._send_cookie.text().strip()

    # --- 结果 ---
    def values(self) -> tuple[int, float, int, int, int, str, str]:
        """返回 (font_size, opacity, max_rows, width, height, mode, theme)。"""
        return (
            self._font.value(),
            self._opacity.value(),
            self._rows.value(),
            self._width.value(),
            self._height.value(),
            self._mode.currentText(),
            self._theme.currentText(),
        )
