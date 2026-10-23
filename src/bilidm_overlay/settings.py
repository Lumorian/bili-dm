"""设置对话框:房间管理(列表/添加/删除,直调 UniBarrage API)+ 外观与窗口配置。

视觉上跟悬浮窗本身保持一套语言:圆角深色卡片、细边框、低对比度的说明文字,
重点操作只用一个 B 站粉主按钮。顶部是自绘标题栏(Wayland 下用
startSystemMove 交给合成器拖动),设置项按「订阅房间 / 外观 / 发弹幕」分卡片,
内容放滚动区,小屏幕也不会把按钮挤出窗口。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QGuiApplication, QMouseEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .api import UniBarrageAPI, UniBarrageError
from .config import Config

logger = logging.getLogger(__name__)

PLATFORMS = ["bilibili", "douyin", "kuaishou", "douyu", "huya", "xiaohongshu"]

_ASSETS = Path(__file__).with_name("assets")
_CHECKMARK = (_ASSETS / "checkmark.svg").as_posix()
_CHEVRON_DOWN = (_ASSETS / "chevron-down.svg").as_posix()
_CHEVRON_UP = (_ASSETS / "chevron-up.svg").as_posix()


_QSS = """
* { outline: none; }
QWidget {
    color: %TEXT%;
    font-family: "Noto Sans CJK SC", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
}
QFrame#panel {
    background: %PANEL_BG%;
    border: 1px solid %PANEL_BORDER%;
    border-radius: 16px;
}
QWidget#content { background: transparent; }
QLabel { background: transparent; }
QLabel#dialogTitle { color: %TEXT_STRONG%; font-size: 17px; font-weight: 600; }
QLabel#dialogSubtitle { color: %HINT%; font-size: 11px; }
QLabel#sectionTitle { color: %TEXT_STRONG%; font-size: 14px; font-weight: 600; }
QLabel#sectionHint { color: %HINT%; font-size: 11px; }
QLabel#fieldLabel { color: %HINT%; font-size: 11px; }
QLabel#hint { color: %HINT%; font-size: 11px; }
QLabel#roomRid { color: %TEXT_STRONG%; font-size: 12px; font-weight: 500; }
QLabel#platformTag {
    color: %ACCENT%;
    background: %ACCENT_SOFT%;
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 600;
}
QLabel#emptyState { color: %HINT%; font-size: 12px; }
QLabel#logoBadge {
    color: #FFFFFF;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FF77A5, stop:1 #D94B80);
    border-radius: 9px;
    font-size: 15px;
    font-weight: 700;
}
QFrame#card {
    background: %CARD_BG%;
    border: 1px solid %CARD_BORDER%;
    border-radius: 12px;
}
QFrame#divider { background: %CARD_BORDER%; border: none; }

QPushButton {
    background: %BTN_BG%;
    border: 1px solid %CARD_BORDER%;
    border-radius: 7px;
    padding: 7px 14px;
    color: %TEXT_STRONG%;
}
QPushButton:hover { background: %BTN_HOVER%; }
QPushButton:pressed { background: %BTN_PRESSED%; }
QPushButton:checked { background: %ACCENT_SOFT%; color: %ACCENT%; border-color: %ACCENT%; }
QPushButton:disabled { color: %HINT%; }
QPushButton#primary {
    background: %ACCENT%;
    border: none;
    color: #FFFFFF;
    font-weight: 600;
    padding: 8px 22px;
}
QPushButton#primary:hover { background: %ACCENT_HOVER%; }
QPushButton#primary:pressed { background: %ACCENT%; }
QPushButton#accentGhost {
    background: %ACCENT_SOFT%;
    border: 1px solid transparent;
    color: %ACCENT%;
    font-weight: 600;
}
QPushButton#accentGhost:hover { border-color: %ACCENT%; }
QPushButton#danger { color: %DANGER%; }
QPushButton#danger:hover { background: %DANGER_SOFT%; border-color: %DANGER%; }
QPushButton#closeButton {
    background: transparent;
    border: none;
    color: %HINT%;
    font-size: 15px;
    border-radius: 14px;
    padding: 0;
}
QPushButton#closeButton:hover { color: %TEXT_STRONG%; background: %BTN_HOVER%; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: %FIELD_BG%;
    border: 1px solid %FIELD_BORDER%;
    border-radius: 8px;
    padding: 6px 10px;
    color: %TEXT%;
    min-height: 20px;
}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {
    border-color: %FIELD_HOVER%;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid %ACCENT%;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    color: %HINT%;
}
QComboBox { combobox-popup: 0; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    border: none;
    width: 26px;
}
QComboBox::down-arrow { image: url(%CHEVRON_DOWN%); width: 12px; height: 12px; }
QComboBox QAbstractItemView {
    background: %PANEL_BG%;
    color: %TEXT%;
    border: 1px solid %CARD_BORDER%;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: %ACCENT%;
    selection-color: #FFFFFF;
    outline: none;
}
QComboBox QAbstractItemView::item { padding: 7px 10px; border-radius: 5px; }
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    border: none;
    background: transparent;
    width: 20px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-position: top right; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-position: bottom right; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url(%CHEVRON_UP%); width: 11px; height: 11px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url(%CHEVRON_DOWN%); width: 11px; height: 11px;
}

QCheckBox { spacing: 9px; color: %TEXT%; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid %FIELD_BORDER%;
    border-radius: 5px;
    background: %FIELD_BG%;
}
QCheckBox::indicator:hover { border-color: %FIELD_HOVER%; }
QCheckBox::indicator:checked {
    background: %ACCENT%;
    border-color: %ACCENT%;
    image: url(%CHECK%);
}

QListWidget#roomList {
    background: %LIST_BG%;
    border: 1px solid %LIST_BORDER%;
    border-radius: 10px;
    padding: 4px;
    outline: none;
}
QListWidget#roomList::item {
    margin: 2px;
    padding: 0;
    border-radius: 8px;
}
QListWidget#roomList::item:hover { background: %ITEM_HOVER%; }
QListWidget#roomList::item:selected { background: %ITEM_SELECTED%; }
QWidget#roomRow { background: transparent; }

QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: %SCROLL%;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: %SCROLL_HOVER%; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QToolTip {
    background: %PANEL_BG%;
    color: %TEXT%;
    border: 1px solid %CARD_BORDER%;
    padding: 6px 8px;
}
"""

_PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "TEXT": "#E6E8EB",
        "TEXT_STRONG": "#FFFFFF",
        "HINT": "rgba(255,255,255,130)",
        "PANEL_BG": "#17181C",
        "PANEL_BORDER": "rgba(255,255,255,22)",
        "CARD_BG": "rgba(255,255,255,8)",
        "CARD_BORDER": "rgba(255,255,255,16)",
        "FIELD_BG": "rgba(255,255,255,10)",
        "FIELD_BORDER": "rgba(255,255,255,28)",
        "FIELD_HOVER": "rgba(255,255,255,70)",
        "ACCENT": "#FF6699",
        "ACCENT_HOVER": "#FF7DA8",
        "ACCENT_SOFT": "rgba(255,102,153,38)",
        "BTN_BG": "rgba(255,255,255,14)",
        "BTN_HOVER": "rgba(255,255,255,26)",
        "BTN_PRESSED": "rgba(255,255,255,42)",
        "DANGER": "#FF7A7A",
        "DANGER_SOFT": "rgba(255,90,90,24)",
        "LIST_BG": "rgba(255,255,255,6)",
        "LIST_BORDER": "rgba(255,255,255,14)",
        "ITEM_HOVER": "rgba(255,255,255,18)",
        "ITEM_SELECTED": "rgba(255,102,153,35)",
        "SCROLL": "rgba(255,255,255,50)",
        "SCROLL_HOVER": "rgba(255,255,255,90)",
    },
    "light": {
        "TEXT": "#1F2329",
        "TEXT_STRONG": "#111318",
        "HINT": "rgba(0,0,0,120)",
        "PANEL_BG": "#FFFFFF",
        "PANEL_BORDER": "rgba(0,0,0,18)",
        "CARD_BG": "#F7F8FA",
        "CARD_BORDER": "rgba(0,0,0,12)",
        "FIELD_BG": "#FFFFFF",
        "FIELD_BORDER": "rgba(0,0,0,24)",
        "FIELD_HOVER": "rgba(0,0,0,45)",
        "ACCENT": "#FF5C92",
        "ACCENT_HOVER": "#FF75A2",
        "ACCENT_SOFT": "rgba(255,92,146,28)",
        "BTN_BG": "#F2F3F5",
        "BTN_HOVER": "#E9EBEF",
        "BTN_PRESSED": "#E0E3E8",
        "DANGER": "#D9363E",
        "DANGER_SOFT": "rgba(217,54,62,18)",
        "LIST_BG": "#FFFFFF",
        "LIST_BORDER": "rgba(0,0,0,16)",
        "ITEM_HOVER": "rgba(0,0,0,6)",
        "ITEM_SELECTED": "rgba(255,92,146,22)",
        "SCROLL": "rgba(0,0,0,60)",
        "SCROLL_HOVER": "rgba(0,0,0,100)",
    },
}


def _skin(theme: str) -> str:
    qss = _QSS
    for token, value in _PALETTES.get(theme, _PALETTES["dark"]).items():
        qss = qss.replace(f"%{token}%", value)
    return (
        qss.replace("%CHECK%", _CHECKMARK)
        .replace("%CHEVRON_DOWN%", _CHEVRON_DOWN)
        .replace("%CHEVRON_UP%", _CHEVRON_UP)
    )


class _HeaderBar(QWidget):
    """自绘标题栏:Wayland 下 move() 无效,交给合成器的 system move。"""

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                a0.accept()
                return
        super().mousePressEvent(a0)


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg: Config, api: UniBarrageAPI | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._api = api or UniBarrageAPI(cfg.api_address, cfg.api_token)
        self._services: list[dict] = []
        self._theme_name = getattr(cfg, "theme", "dark")
        if self._theme_name not in _PALETTES:
            self._theme_name = "dark"
        self._palette = _PALETTES[self._theme_name]

        self.setWindowTitle("设置")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(600, 540)

        panel = QFrame(self)
        panel.setObjectName("panel")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(panel)

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(24, 20, 24, 18)
        outer.setSpacing(14)
        outer.addWidget(self._build_header())

        scroll = QScrollArea(panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setObjectName("content")
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 4, 0)
        body.setSpacing(14)
        body.addWidget(self._build_rooms_card())
        body.addWidget(self._build_appearance_card())
        body.addWidget(self._build_send_card())
        body.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        divider = QFrame(panel)
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        outer.addWidget(divider)
        outer.addLayout(self._build_footer())

        self._resize_to_screen()
        self._apply_theme(self._theme_name)
        self.reload_services()

    # --- 构建:标题栏与页脚 ---
    def _build_header(self) -> QWidget:
        bar = _HeaderBar()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        logo = QLabel("B")
        logo.setObjectName("logoBadge")
        logo.setFixedSize(32, 32)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("设置")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Bilidm Overlay · 直播间弹幕悬浮窗")
        subtitle.setObjectName("dialogSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        layout.addLayout(titles)
        layout.addStretch(1)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeButton")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)
        return bar

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setSpacing(10)
        hint = QLabel("配置保存在 ~/.config/bilidm-overlay/config.yaml")
        hint.setObjectName("hint")
        footer.addWidget(hint)
        footer.addStretch(1)

        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        footer.addWidget(cancel)
        footer.addWidget(save)
        return footer

    # --- 构建:三个卡片 ---
    def _card(self, title: str, hint: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        body = QVBoxLayout(card)
        body.setContentsMargins(18, 16, 18, 16)
        body.setSpacing(10)

        head = QVBoxLayout()
        head.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        hint_label = QLabel(hint)
        hint_label.setObjectName("sectionHint")
        hint_label.setWordWrap(True)
        head.addWidget(title_label)
        head.addWidget(hint_label)
        body.addLayout(head)
        body.addSpacing(2)
        return card, body

    def _build_rooms_card(self) -> QFrame:
        card, body = self._card(
            "订阅房间", "直连 UniBarrage 服务;在这里添加或删除,保存后 dmnotifier 会自动对齐订阅。"
        )
        self._list = QListWidget()
        self._list.setObjectName("roomList")
        self._list.setMinimumHeight(128)
        self._list.setMaximumHeight(144)
        self._list.setSpacing(2)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        body.addWidget(self._list)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.reload_services)
        delete = QPushButton("删除选中")
        delete.setObjectName("danger")
        delete.clicked.connect(self.delete_selected)
        actions.addWidget(refresh)
        actions.addStretch(1)
        actions.addWidget(delete)
        body.addLayout(actions)

        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self._platform = QComboBox()
        self._platform.addItems(PLATFORMS)
        self._platform.setFixedWidth(112)
        self._platform.setFixedHeight(34)
        self._rid = QLineEdit()
        self._rid.setPlaceholderText("房间号,如 689422")
        self._rid.setFixedHeight(34)
        self._cookie = QLineEdit()
        self._cookie.setPlaceholderText("cookie(可选,发送用)")
        self._cookie.setFixedHeight(34)
        add_btn = QPushButton("添加")
        add_btn.setFixedHeight(34)
        add_btn.setObjectName("accentGhost")
        add_btn.clicked.connect(self.add_room)
        add_row.addWidget(self._platform)
        add_row.addWidget(self._rid, 2)
        add_row.addWidget(self._cookie, 3)
        add_row.addWidget(add_btn)
        body.addLayout(add_row)

        self._note = QLabel("")
        self._note.setObjectName("hint")
        self._note.setWordWrap(True)
        self._note.setVisible(False)
        body.addWidget(self._note)
        return card

    def _build_appearance_card(self) -> QFrame:
        card, body = self._card("外观", "面板字号、主题、透明度与窗口尺寸。")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        self._font = QSpinBox()
        self._font.setRange(9, 40)
        self._font.setSuffix(" px")
        self._font.setValue(self._cfg.font_size)

        self._theme = QComboBox()
        self._theme.addItem("深色", "dark")
        self._theme.addItem("浅色", "light")
        theme_index = self._theme.findData(getattr(self._cfg, "theme", "dark"))
        self._theme.setCurrentIndex(max(0, theme_index))
        self._theme.currentIndexChanged.connect(self._on_theme_changed)

        self._opacity = QDoubleSpinBox()
        self._opacity.setRange(10, 100)
        self._opacity.setDecimals(0)
        self._opacity.setSuffix(" %")
        self._opacity.setValue(round(float(self._cfg.opacity) * 100))

        self._rows = QSpinBox()
        self._rows.setRange(5, 200)
        self._rows.setSuffix(" 行")
        self._rows.setValue(self._cfg.max_rows)

        self._width = QSpinBox()
        self._width.setRange(280, 2000)
        self._width.setSuffix(" px")
        self._width.setValue(self._cfg.width)

        self._height = QSpinBox()
        self._height.setRange(160, 1200)
        self._height.setSuffix(" px")
        self._height.setValue(self._cfg.height)

        self._mode = QComboBox()
        self._mode.addItem("合并显示", "merged")
        self._mode.addItem("每个房间独立窗口", "per-room")
        mode_index = self._mode.findData(getattr(self._cfg, "mode", "merged"))
        self._mode.setCurrentIndex(max(0, mode_index))

        grid.addWidget(self._field("字号", self._font), 0, 0)
        grid.addWidget(self._field("主题", self._theme), 0, 1)
        grid.addWidget(self._field("透明度", self._opacity), 0, 2)
        grid.addWidget(self._field("墙行数上限", self._rows), 1, 0)
        grid.addWidget(self._field("宽度", self._width), 1, 1)
        grid.addWidget(self._field("高度", self._height), 1, 2)
        grid.addWidget(self._field("窗口模式", self._mode), 2, 0, 1, 3)
        body.addLayout(grid)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        body.addWidget(divider)

        self._show_online = QCheckBox("在卡片右上角显示当前直播间在线人数")
        self._show_online.setChecked(getattr(self._cfg, "show_online", True))
        online_hint = QLabel("匿名查询 B 站公开接口,每 30 秒刷新;关闭后不产生网络请求。")
        online_hint.setObjectName("hint")
        online_hint.setContentsMargins(25, 0, 0, 0)
        online_hint.setWordWrap(True)
        body.addWidget(self._show_online)
        body.addWidget(online_hint)
        return card

    def _build_send_card(self) -> QFrame:
        card, body = self._card(
            "发弹幕",
            "需要登录 cookie(含 SESSDATA 与 bili_jct);cookie 只用于发送,等同于登录态,注意别外传。",
        )
        self._send_enabled = QCheckBox("启用底部发送栏")
        self._send_enabled.setChecked(getattr(self._cfg, "send_enabled", True))
        body.addWidget(self._send_enabled)

        cookie_label = QLabel("登录 cookie")
        cookie_label.setObjectName("fieldLabel")
        body.addWidget(cookie_label)
        cookie_row = QHBoxLayout()
        cookie_row.setSpacing(8)
        self._send_cookie = QLineEdit()
        self._send_cookie.setPlaceholderText(
            "SESSDATA=…; bili_jct=…(留空则沿用房间订阅时的 cookie)"
        )
        self._send_cookie.setEchoMode(QLineEdit.EchoMode.Password)
        self._send_cookie.setText(getattr(self._cfg, "send_cookie", "") or "")
        self._send_cookie.setFixedHeight(34)
        self._reveal = QPushButton("显示")
        self._reveal.setFixedSize(58, 34)
        self._reveal.setCheckable(True)
        self._reveal.toggled.connect(self._toggle_cookie_visible)
        cookie_row.addWidget(self._send_cookie, 1)
        cookie_row.addWidget(self._reveal)
        body.addLayout(cookie_row)

        self._send_note = QLabel("")
        self._send_note.setObjectName("hint")
        self._send_note.setWordWrap(True)
        body.addWidget(self._send_note)
        self._send_cookie.textChanged.connect(self._refresh_send_note)
        self._refresh_send_note()
        return card

    @staticmethod
    def _field(label: str, widget: QWidget) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        text = QLabel(label)
        text.setObjectName("fieldLabel")
        layout.addWidget(text)
        widget.setFixedHeight(34)
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(widget)
        return box

    # --- 主题 ---
    def _apply_theme(self, name: str) -> None:
        name = name if name in _PALETTES else "dark"
        self._theme_name = name
        self._palette = _PALETTES[name]
        self.setStyleSheet(_skin(name))
        # 说明文字用内联色(错误红/弱化灰),换主题时要跟着换;QSS 管不到它们
        note = getattr(self, "_note", None)
        if note is not None:
            color = (
                self._palette["DANGER"]
                if getattr(self, "_note_error", False)
                else self._palette["HINT"]
            )
            note.setStyleSheet(f"color: {color};")
        if getattr(self, "_send_note", None) is not None:
            self._refresh_send_note()

    def _on_theme_changed(self) -> None:
        data = self._theme.currentData()
        if isinstance(data, str):
            self._apply_theme(data)

    # --- 房间管理 ---
    def reload_services(self) -> None:
        try:
            self._services = self._api.list_all()
            self._set_note("")
        except UniBarrageError as exc:
            self._services = []
            self._set_note(f"刷新失败: {exc}", error=True)
            logger.warning("refresh services: %s", exc)

        self._list.clear()
        if not self._services:
            item = QListWidgetItem()
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setSizeHint(QSize(0, 54))
            self._list.addItem(item)
            empty = QLabel("还没有订阅房间,在下面添加一个")
            empty.setObjectName("emptyState")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list.setItemWidget(item, empty)
            return
        for svc in self._services:
            item = QListWidgetItem()
            item.setData(1, svc)
            item.setSizeHint(QSize(0, 40))
            self._list.addItem(item)
            self._list.setItemWidget(item, self._room_row(svc["platform"], svc["rid"]))

    @staticmethod
    def _room_row(platform: str, rid: str) -> QWidget:
        row = QWidget()
        row.setObjectName("roomRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(10)
        tag = QLabel(platform)
        tag.setObjectName("platformTag")
        room = QLabel(rid)
        room.setObjectName("roomRid")
        layout.addWidget(tag)
        layout.addWidget(room)
        layout.addStretch(1)
        return row

    def delete_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        svc = item.data(1)
        if not isinstance(svc, dict):
            return
        try:
            self._api.stop(svc["platform"], svc["rid"])
            self.reload_services()
        except UniBarrageError as exc:
            self._set_note(f"删除失败: {exc}", error=True)

    def add_room(self) -> None:
        rid = self._rid.text().strip()
        if not rid:
            self._set_note("房间号不能为空", error=True)
            return
        try:
            self._api.start(self._platform.currentText(), rid, self._cookie.text().strip())
            self._rid.clear()
            self._cookie.clear()
            self.reload_services()
        except UniBarrageError as exc:
            self._set_note(f"添加失败: {exc}", error=True)

    def _set_note(self, text: str, error: bool = False) -> None:
        self._note_error = error
        self._note.setText(text)
        self._note.setVisible(bool(text))
        color = self._palette["DANGER"] if error else self._palette["HINT"]
        self._note.setStyleSheet(f"color: {color};")

    # --- 发弹幕 ---
    def _toggle_cookie_visible(self, show: bool) -> None:
        self._send_cookie.setEchoMode(
            QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        )
        self._reveal.setText("隐藏" if show else "显示")

    def _refresh_send_note(self) -> None:
        from .sender import parse_csrf

        cookie = self._send_cookie.text().strip()
        if not cookie:
            text = "未填 cookie:将沿用 --room 参数里的 cookie,或 dmnotifier history 中该房间的 cookie。"
            color = self._palette["HINT"]
        elif not parse_csrf(cookie):
            text = "cookie 里没有 bili_jct,发不出去:请从浏览器复制完整 cookie。"
            color = self._palette["DANGER"]
        else:
            text = "cookie 看起来可用。"
            color = self._palette["HINT"]
        self._send_note.setText(text)
        self._send_note.setStyleSheet(f"color: {color};")

    def send_values(self) -> tuple[bool, str]:
        return self._send_enabled.isChecked(), self._send_cookie.text().strip()

    # --- 结果 ---
    def values(self) -> tuple[int, float, int, int, int, str, str, bool]:
        return (
            self._font.value(),
            self._opacity.value() / 100.0,
            self._rows.value(),
            self._width.value(),
            self._height.value(),
            str(self._mode.currentData() or "merged"),
            str(self._theme.currentData() or "dark"),
            self._show_online.isChecked(),
        )

    def _resize_to_screen(self) -> None:
        width, height = 660, 860
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, max(600, available.width() - 64))
            height = min(height, max(540, available.height() - 80))
        self.resize(width, height)
