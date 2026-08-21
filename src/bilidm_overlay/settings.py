"""轻量设置对话框:v1 仅内存生效(字号/透明度/最大行数)。"""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QSpinBox

from .config import Config


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg: Config) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self.setWindowTitle("设置")
        layout = QFormLayout(self)
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
        layout.addRow("字号", self._font)
        layout.addRow("透明度", self._opacity)
        layout.addRow("最大行数", self._rows)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self) -> tuple[int, float, int]:
        """返回 (font_size, opacity, max_rows),供窗口在 exec() 后应用。"""
        return self._font.value(), self._opacity.value(), self._rows.value()
