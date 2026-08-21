import asyncio
import os

import pytest

from bilidm_overlay.client import DanmakuServer, ensure_stale_socket_removed
from bilidm_overlay.danmaku.model import Danmaku


async def test_receives_messages(tmp_path):
    sock = str(tmp_path / "d.sock")
    got: list[Danmaku] = []
    srv = DanmakuServer(sock, got.append)
    await srv.start()
    try:
        reader, writer = await asyncio.open_unix_connection(sock)
        writer.write(b'{"type":"chat","name":"A","content":"hi"}\n')
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.close()
        await writer.wait_closed()
    finally:
        await srv.stop()
    assert got and got[0].name == "A" and got[0].content == "hi"


async def test_bad_line_skipped_not_crash(tmp_path):
    sock = str(tmp_path / "d.sock")
    got: list[Danmaku] = []
    srv = DanmakuServer(sock, got.append)
    await srv.start()
    try:
        reader, writer = await asyncio.open_unix_connection(sock)
        writer.write(b"not json\n")
        writer.write(b'{"type":"chat","name":"B"}\n')
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.close()
        await writer.wait_closed()
    finally:
        await srv.stop()
    assert len(got) == 1 and got[0].name == "B"


async def test_multiline_frame(tmp_path):
    sock = str(tmp_path / "d.sock")
    got: list[Danmaku] = []
    srv = DanmakuServer(sock, got.append)
    await srv.start()
    try:
        reader, writer = await asyncio.open_unix_connection(sock)
        writer.write(b'{"type":"chat","name":"C"}\n{"type":"chat","name":"D"}\n')
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.close()
        await writer.wait_closed()
    finally:
        await srv.stop()
    assert [g.name for g in got] == ["C", "D"]


def test_stale_socket_removed(tmp_path):
    sock = os.path.join(str(tmp_path), "stale.sock")
    s = __import__("socket").socket(__import__("socket").AF_UNIX, __import__("socket").SOCK_STREAM)
    s.bind(sock)
    s.close()  # 无人监听 -> 属于残留文件
    ensure_stale_socket_removed(sock)
    assert not os.path.exists(sock)


def test_live_socket_not_removed(tmp_path):
    sock = os.path.join(str(tmp_path), "live.sock")
    import socket

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(sock)
    s.listen(1)
    with pytest.raises(OSError, match="already in use"):
        ensure_stale_socket_removed(sock)
    s.close()


async def test_stop_never_started_leaves_foreign_socket(tmp_path):
    """从未 start() 的服务端在 stop() 时不得删除他人(另一实例)正在监听的 socket。"""
    import socket

    sock = os.path.join(str(tmp_path), "foreign.sock")
    srv = DanmakuServer(sock, lambda d: None)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(sock)
    s.listen(1)
    try:
        await srv.stop()  # server never started, but the socket belongs to someone else
        assert os.path.exists(sock)
    finally:
        s.close()
        if os.path.exists(sock):
            os.unlink(sock)
