"""入口:CLI 解析、qasync 事件循环、socket 服务端装配、--demo 假消息流。"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import signal
import sys
from pathlib import Path

import qasync
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from .client import DanmakuServer
from .config import Config, load, merge_cli
from .danmaku.model import Danmaku, MedalInfo
from .window import DanmakuWindow

logger = logging.getLogger(__name__)

DEMO_NAMES = ["Alice", "Bob", "Carol", "Dave", "Eve"]
DEMO_LINES = [
    "主播你好呀", "前排!!", "666666", "礼物闪电链!!!",
    "刚来,前面发生了什么", "这个主播的声线我爱了",
]
# 演示用粉丝勋章:名字/等级/配色/是否舰队(对齐官方面板的几种典型样式)
DEMO_MEDALS = [
    MedalInfo(name="酷萨", level=33, color_start="#638FFE", color_end="#638FFE",
              color_border="#638FFE", guard_level=3),
    MedalInfo(name="酷萨", level=16, color_start="#FF86B2", color_end="#FF86B2",
              color_border="#FF86B2"),
    MedalInfo(name="小蛋糕", level=39, color_start="#5B8AF5", color_end="#638FFE",
              color_border="#638FFE"),
    None,  # 未佩戴勋章的用户
]


def _demo_danmaku(i: int) -> Danmaku:
    """演示流:把官方面板的几种行都跑到(勋章/舰队/礼物/SC/上舰/点赞)。"""
    medal = random.choice(DEMO_MEDALS)
    guard = medal.guard_level if medal else 0
    name = random.choice(DEMO_NAMES)
    if i == 0:
        return Danmaku(type="chat", platform="bilibili", rid="689422",
                       name=name, content=random.choice(DEMO_LINES),
                       medal=medal, guard_level=guard, user_level=random.randint(3, 60))
    if i == 1:
        return Danmaku(type="gift", platform="bilibili", rid="689422",
                       name=name, item="辣条", num=random.randint(1, 99), price=0.1,
                       medal=medal, guard_level=guard)
    if i == 2:
        return Danmaku(type="superchat", platform="bilibili", rid="689422",
                       name=name, content="加油加油!", price=random.choice([30, 50, 100]),
                       medal=medal, guard_level=guard)
    if i == 3:
        return Danmaku(type="subscribe", platform="bilibili", rid="689422",
                       name=name, item=random.choice(["舰长", "提督", "总督"]),
                       num=1, price=198, medal=medal, guard_level=guard)
    return Danmaku(type="like", platform="bilibili", rid="689422", name=name,
                   user_level=random.randint(3, 60))


async def _demo_gen(sink: list[Danmaku]) -> None:
    """每 0.4s 产一条假消息,chat/gift/superchat/subscribe 轮流。"""
    for i in range(30):
        sink.append(_demo_danmaku(i % 4))
        await asyncio.sleep(0.4)


def _build_windows(cfg: Config) -> list[DanmakuWindow]:
    if cfg.mode == "per-room":
        windows = []
        for room in cfg.rooms:
            if not room:
                continue
            windows.append(DanmakuWindow(cfg, room_filter=room, show_tag=False))
        return windows or [DanmakuWindow(cfg)]
    # merged:多房间时显示来源标签
    return [DanmakuWindow(cfg, show_tag=len(cfg.rooms) > 1)]


def entry_point() -> None:
    parser = argparse.ArgumentParser(prog="bilidm-overlay",
                                     description="Floating danmaku overlay for bilibili live")
    parser.add_argument("--room", action="append", help="bilibili:689422(:cookie 可选,多路可重复)")
    parser.add_argument("--merged", action="store_true")
    parser.add_argument("--per-room", action="store_true")
    parser.add_argument("--socket")
    parser.add_argument("--config")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--theme", choices=["dark", "light"], help="面板配色(dark/light,默认取配置)")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    cfg = load(Path(args.config) if args.config else None)
    cfg = merge_cli(cfg, args)

    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    windows = _build_windows(cfg)
    server: DanmakuServer | None = None
    exit_code = 0
    if not args.demo:
        server = DanmakuServer(cfg.socket, lambda d: [w.feed(d) for w in windows])

        status_check = QTimer()
        status_check.setInterval(1000)

        def _update_status() -> None:
            text = "" if server.connected() else "dmnotifier 离线,连接中…"
            for w in windows:
                w.set_status(text)

        status_check.timeout.connect(_update_status)
        status_check.start()

    async def _run() -> None:
        # 信号先行:即使 server 启动失败,退出也走已注册的 loop.stop() 清理路径。
        loop.add_signal_handler(signal.SIGINT, loop.stop)
        loop.add_signal_handler(signal.SIGTERM, loop.stop)
        if server is not None:
            try:
                await server.start()
            except OSError as exc:
                # 启动失败(典型:socket 已被另一实例占用)必须显式退出,否则窗口
                # 配着一个从不接收消息的服务端继续显示"离线";若还带着未绑定的
                # server 走 finally,_stop() 在旧实现里会误删占用者的活 socket。
                logger.error("socket 已被占用,另一个 overlay 实例在运行? %s", exc)
                nonlocal exit_code
                exit_code = 1
                loop.stop()
                return
        if args.demo:
            async def _demo_loop() -> None:
                for i in range(120):
                    for w in windows:
                        w.feed(_demo_danmaku(i % 5))
                    await asyncio.sleep(0.4)

            asyncio.create_task(_demo_loop())

    async def _stop() -> None:
        if server is not None:
            await server.stop()

    loop.create_task(_run())
    for w in windows:
        w.resize(cfg.width, cfg.height)
        w.move(cfg.position[0], cfg.position[1])  # X11 回退下生效;layer-shell 下被合成器重定位,精确锚点属后续微调
        w.show()
    try:
        loop.run_forever()
    finally:
        loop.run_until_complete(_stop())
    if exit_code:
        sys.exit(exit_code)


if __name__ == "__main__":
    entry_point()
