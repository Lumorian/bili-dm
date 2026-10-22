"""发送栏:卡片底部的「输入框 + 字数 + 发送」,对齐官方弹幕姬的输入条。

官方直播间面板底部就是这一条:圆角输入框、右侧发送按钮、普通用户 20 字上限。本项目照抄这套结构与文案,视觉上沿用卡片自身的玻璃态
(深色主题半透明白、浅色主题半透明黑),不引入官方那份蓝色实心按钮——悬浮在
直播画面上时,实心块比半透明更抢眼。

两条与穿透相关的约定(见 window.set_passthrough):

- 锁定(=点击穿透)时输入框不可编辑,占位文案提示「解锁后可发送」:锁定态
  整个窗口除按钮带外都在往外放行鼠标,输入框即便可点也拿不到键盘焦点。
- 解锁后正常输入,回车即发(与官方输入框一致),发送中禁用按钮防连点。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from .theme import Theme, theme_for

MAX_LEN = 20  # 普通用户弹幕上限;官方输入框同样卡 20
INPUT_HEIGHT = 26  # 输入框/按钮高度:官方那条输入条与卡片行高同量级
BAR_HEIGHT = 32  # 输入条最小高度;字号调大时随内容长高

PLACEHOLDER = "发送弹幕…"
LOCKED_PLACEHOLDER = "解锁后可发送弹幕"
FEEDBACK_MS = 4000


class Composer(QWidget):
    """底部发送栏:输入、字数提示、发送按钮、结果提示。"""

    submitted = pyqtSignal(str)

    def __init__(self, parent=None, theme: str = "dark", max_len: int = MAX_LEN) -> None:
        super().__init__(parent)
        self._theme_name = theme
        self._theme: Theme = theme_for(theme)
        self._max_len = max_len
        self._locked = True
        self._busy = False
        # 高度固定:放进卡片的 VBox 后不会被弹幕墙挤压/拉伸(最小高度随字号内容增长)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(BAR_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 8, 3)
        layout.setSpacing(6)

        self._input = QLineEdit(self)
        self._input.setMinimumHeight(INPUT_HEIGHT)
        self._input.setMaxLength(max_len)
        self._input.setPlaceholderText(LOCKED_PLACEHOLDER)
        self._input.setClearButtonEnabled(True)
        self._input.returnPressed.connect(self._emit)
        self._input.textChanged.connect(self._on_text_changed)
        # 手动调焦:QLineEdit 默认按 Tab 会跑进按钮,发送栏只该有一个输入焦点
        self._input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._hint = QLabel("", self)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._hint.setVisible(False)

        self._count = QLabel("", self)
        self._count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._send = QToolButton(self)
        self._send.setFixedHeight(INPUT_HEIGHT)
        self._send.setText("发送")
        self._send.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send.setToolTip("发送弹幕(回车)")
        self._send.clicked.connect(self._emit)

        layout.addWidget(self._input, 1)
        layout.addWidget(self._hint)
        layout.addWidget(self._count)
        layout.addWidget(self._send)

        self._apply_theme()
        self.set_locked(True)

    # --- 主题/字号 ---
    def set_theme(self, name: str) -> None:
        self._theme_name = name
        self._theme = theme_for(name)
        self._apply_theme()

    def set_font(self, family: str, size: int) -> None:
        font = QFont(family, size)
        for widget in (self, self._input, self._hint, self._count, self._send):
            widget.setFont(font)

    def _apply_theme(self) -> None:
        theme = self._theme
        alpha_fill = 26 if theme.name == "dark" else 16
        self.setStyleSheet(
            f"""
QLineEdit {{
    background: rgba(255, 255, 255, {alpha_fill});
    border: none;
    border-radius: 12px;
    padding: 2px 8px;
    color: {theme.text};
    selection-background-color: {theme.brand_pink};
}}
QLineEdit[readOnly="true"] {{
    color: {theme.name_text};
}}
QLineEdit:disabled {{
    color: {theme.name_text};
}}
QLabel {{
    color: {theme.name_text};
    font-size: 11px;
    background: transparent;
}}
QToolButton {{
    background: {theme.brand_pink};
    color: #FFFFFF;
    border: none;
    border-radius: 11px;
    padding: 0 10px;
}}
QToolButton:hover {{ background: {theme.brand_pink}; }}
QToolButton:disabled {{ background: rgba(255, 255, 255, 28); color: {theme.name_text}; }}
"""
        )

    # --- 状态 ---
    def set_locked(self, locked: bool) -> None:
        """锁定(点击穿透)态只读:此时窗口不接键盘焦点,输入框收不到字符。"""
        self._locked = locked
        self._input.setReadOnly(locked)
        self._input.setPlaceholderText(LOCKED_PLACEHOLDER if locked else PLACEHOLDER)
        self._input.setToolTip("先点右上角锁按钮解锁" if locked else "")
        self._refresh_state()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._refresh_state()

    def is_locked(self) -> bool:
        return self._locked

    def is_busy(self) -> bool:
        return self._busy

    def text(self) -> str:
        return self._input.text()

    def clear(self) -> None:
        self._input.clear()

    def focus_input(self) -> None:
        """把焦点交给输入框(解锁后调用;锁定态本就不该抢焦点)。"""
        if not self._locked:
            self._input.setFocus(Qt.FocusReason.OtherFocusReason)

    def send_button(self) -> QToolButton:
        return self._send

    def input_edit(self) -> QLineEdit:
        return self._input

    def hint_text(self) -> str:
        """当前回执文案(不管标签此刻是否可见 —— 窗口没 show 时 isVisible() 恒假)。"""
        return self._hint.text()

    def flash(self, text: str, error: bool = False) -> None:
        """在输入条里就地回执(已发送 / 失败原因),几秒后自动让位给字数。"""
        self._hint.setText(text)
        color = "#FF6699" if error else self._theme.name_text
        self._hint.setStyleSheet(f"color: {color}; font-size: 11px; background: transparent;")
        self._hint.setVisible(bool(text))
        self._count.setVisible(not text and not self._locked)
        if text:
            QTimer.singleShot(FEEDBACK_MS, self.clear_hint)

    def clear_hint(self) -> None:
        self._hint.clear()
        self._hint.setVisible(False)
        self._count.setVisible(not self._locked)

    # --- 内部 ---
    def _on_text_changed(self, _text: str) -> None:
        self._refresh_state()

    def _refresh_state(self) -> None:
        text = self._input.text()
        editable = not self._locked and not self._busy
        # 用只读而不是禁用:禁用的 QLineEdit 在部分 Qt 样式中不再画占位文案,
        # 而锁定态恰恰要靠占位文案("解锁后可发送弹幕")告诉用户为什么打不了字。
        self._input.setReadOnly(not editable)
        self._send.setEnabled(editable and bool(text.strip()))
        self._count.setText(f"{len(text)}/{self._max_len}" if text else "")
        self._count.setVisible(editable and not self._hint.isVisible() and bool(text))

    def _emit(self) -> None:
        if self._locked or self._busy:
            return
        text = self._input.text().strip()
        if not text:
            return
        self.submitted.emit(text)
