#!/usr/bin/env python3
"""验收辅助:作为假 dmnotifier 客户端,往 overlay socket 写 demo 弹幕。

发的字段与 dmnotifier float 插件的协议行一致(含官方排版所需的 user 元信息、
醒目留言配色),便于肉眼核对勋章胶囊/礼物分色/SC 卡片的渲染。
"""

import asyncio
import json
import os

from bilidm_overlay.main import _demo_danmaku


def payload_of(d) -> dict:
    payload = {
        "time": "2026-08-21T20:00:00+08:00",
        "platform": d.platform,
        "rid": d.rid,
        "type": d.type,
        "name": d.name,
    }
    if d.content:
        payload["content"] = d.content
    if d.item:
        payload["item"] = d.item
    if d.price is not None:
        payload["price"] = d.price
    if d.num:
        payload["num"] = d.num
    if d.avatar:
        payload["avatar"] = d.avatar
    if d.user_level:
        payload["user_level"] = d.user_level
    if d.guard_level:
        payload["guard_level"] = d.guard_level
    if d.name_color:
        payload["name_color"] = d.name_color
    if d.bg_color_start:
        payload["bg_color_start"] = d.bg_color_start
    if d.bg_color_end:
        payload["bg_color_end"] = d.bg_color_end
    if d.price_color:
        payload["price_color"] = d.price_color
    if d.medal is not None:
        payload["medal"] = {
            "name": d.medal.name,
            "level": d.medal.level,
            "color_start": d.medal.color_start,
            "color_end": d.medal.color_end,
            "color_border": d.medal.color_border,
            "color_text": d.medal.color_text,
            "guard_level": d.medal.guard_level,
            "is_light": d.medal.is_light,
        }
    return payload


async def main() -> None:
    sock = os.environ.get("XDG_RUNTIME_DIR", "/tmp") + "/bilidm-danmaku.sock"
    _reader, writer = await asyncio.open_unix_connection(sock)
    for i in range(30):
        d = _demo_danmaku(i % 5)
        writer.write((json.dumps(payload_of(d), ensure_ascii=False) + "\n").encode())
        await writer.drain()
        await asyncio.sleep(0.4)
    writer.close()
    await writer.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
