"""头像加载:QNetworkAccessManager 异步下载 + 磁盘/内存缓存,供悬浮窗行首绘制。"""

from __future__ import annotations

import hashlib
import os

from PyQt6.QtCore import QObject, QStandardPaths, QUrl, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

AVATAR_SIDE = 24  # 行内头像边长(px)


def avatar_cache_path(url: str, cache_dir: str | None = None) -> str:
    """头像缓存文件路径:sha1(url) 命名,扩展名固定 png。"""
    base = cache_dir or os.path.join(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation),
        "bilidm-overlay",
        "avatars",
    )
    digest = hashlib.sha1(url.encode()).hexdigest()
    return os.path.join(base, f"{digest}.png")


class AvatarCache(QObject):
    """url → QPixmap 的内存+磁盘缓存;未命中时发起异步下载,完成后发 loaded。"""

    loaded = pyqtSignal()

    def __init__(self, parent: QObject | None = None, cache_dir: str | None = None) -> None:
        super().__init__(parent)
        self._cache_dir = cache_dir
        self._mem: dict[str, QPixmap] = {}
        self._pending: set[str] = set()
        self._net = QNetworkAccessManager(self)
        self._net.finished.connect(self._on_finished)

    def pixmap(self, url: str) -> QPixmap | None:
        """命中返回头像;未命中返回 None 并触发一次下载。"""
        if not url:
            return None
        pix = self._mem.get(url)
        if pix is not None:
            return pix
        path = avatar_cache_path(url, self._cache_dir)
        if os.path.isfile(path):
            pix = QPixmap(path)
            if not pix.isNull():
                self._mem[url] = pix
                return pix
        if url not in self._pending:
            self._fetch(url)
        return None

    def _fetch(self, url: str) -> None:
        self._pending.add(url)
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        self._net.get(request)

    def _on_finished(self, reply: QNetworkReply) -> None:
        url = reply.url().toString()
        self._pending.discard(url)
        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = reply.readAll()
            pix = QPixmap()
            if pix.loadFromData(data):
                self._mem[url] = pix
                path = avatar_cache_path(url, self._cache_dir)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                pix.save(path, "PNG")
                self.loaded.emit()
        reply.deleteLater()
