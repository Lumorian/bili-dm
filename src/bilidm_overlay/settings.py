"""设置对话框:房间管理(列表/添加/删除,直调 UniBarrage API)+ 外观与窗口配置。"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
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
        form.addRow("字号", self._font)
        form.addRow("主题", self._theme)
        form.addRow("透明度", self._opacity)
        form.addRow("墙行数上限", self._rows)
        form.addRow("宽度", self._width)
        form.addRow("高度", self._height)
        form.addRow("窗口模式", self._mode)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

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
