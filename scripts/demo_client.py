#!/usr/bin/env python3
"""验收辅助:作为假 dmnotifier 客户端,往 overlay socket 写 demo 弹幕。"""

import asyncio
import json
import os

from bilidm_overlay.main import _demo_danmaku


async def main() -> None:
    sock = os.environ.get("XDG_RUNTIME_DIR", "/tmp") + "/bilidm-danmaku.sock"
    _reader, writer = await asyncio.open_unix_connection(sock)
    for i in range(30):
        d = _demo_danmaku(i % 4)
        payload = {"time": "2026-08-21T20:00:00+08:00", "platform": d.platform, "rid": d.rid,
                   "type": d.type, "name": d.name}
        if d.content:
            payload["content"] = d.content
        if d.item:
            payload["item"] = d.item
        if d.price is not None:
            payload["price"] = d.price
        writer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await writer.drain()
        await asyncio.sleep(0.4)
    writer.close()
    await writer.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
