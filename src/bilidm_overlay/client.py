"""Unix socket 服务端:接收 dmnotifier float 插件的 JSON lines。"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Callable

from .danmaku.model import Danmaku, parse_message

logger = logging.getLogger(__name__)


def ensure_stale_socket_removed(socket_path: str) -> None:
    """探测残留 socket:能连上说明有人在用,抛错;连接被拒说明是残留文件,删除。"""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(socket_path)
    except ConnectionRefusedError:
        os.unlink(socket_path)
    except FileNotFoundError:
        pass  # 不存在,无需处理
    else:
        raise OSError(f"socket already in use: {socket_path}")
    finally:
        s.close()


class DanmakuServer:
    def __init__(self, socket_path: str, on_message: Callable[[Danmaku], None]) -> None:
        self._path = socket_path
        self._on_message = on_message
        self._server: asyncio.Server | None = None
        self._conns: set[asyncio.StreamWriter] = set()

    def connected(self) -> bool:
        return bool(self._conns)

    async def start(self) -> None:
        ensure_stale_socket_removed(self._path)
        self._server = await asyncio.start_unix_server(self._handler, path=self._path)

    async def stop(self) -> None:
        for writer in list(self._conns):
            writer.close()
        self._conns.clear()
        # 只清理自己成功绑定的 socket:start() 失败(如 socket 已被另一实例占用)时
        # _server 为 None,此时 unlink 会删掉占用者的活 socket。
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            try:
                os.unlink(self._path)
            except FileNotFoundError:
                pass

    async def _handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._conns.add(writer)
        try:
            while line := await reader.readline():
                if not line.strip():
                    continue
                try:
                    self._on_message(parse_message(line.decode("utf-8", errors="replace")))
                except ValueError as exc:
                    logger.warning("skipping bad danmaku line: %s", exc)
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        finally:
            self._conns.discard(writer)
            writer.close()
