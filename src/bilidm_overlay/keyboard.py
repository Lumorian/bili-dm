"""键盘交互:让 layer-shell 表面在解锁后能真正收到按键。

`make_overlay()` 把表面设成 `KeyboardInteractivityNone`(kotonoha 是给歌词条用的),
层壳表面于是**永远拿不到键盘焦点**——发送栏的输入框点得着也没法打字。桥里本来就有
切换该项的入口(`set_keyboard_interactivity`,实际设成 OnDemand),只是 kotonoha 的
`OverlayPlatform` 协议还没把它露出来。

于是这里按"能调就调"的顺序退让:

1. 适配器自己有了 `set_keyboard_interactivity`(kotonoha 将来把它加进协议)——直接调;
2. 否则经适配器的 `_controller`(即桥)调,表面指针取自 host;
3. 都不行(普通顶层窗、offscreen、X11)就什么都不做:这些窗口本来就收键盘。

失败不抛异常:打不了字是体验问题,不该把整个悬浮窗带崩。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def pointer_for(host) -> int | None:
    """取窗口的原生句柄;取不到(窗口已销毁/offscreen)返回 None。"""
    try:
        return host.native_window_pointer()
    except (RuntimeError, AttributeError):
        return None


def apply_keyboard_interactivity(platform, host, enabled: bool) -> bool:
    """开/关该表面的键盘交互;返回是否真的调到了桥(False=当前平台不需要或调不到)。"""
    direct = getattr(platform, "set_keyboard_interactivity", None)
    if callable(direct):
        try:
            direct(enabled)
            return True
        except (OSError, RuntimeError) as exc:  # 桥在,但表面还没建好等
            logger.debug("切换键盘交互失败(改走桥直调):%s", exc)
    controller = getattr(platform, "_controller", None)
    setter = getattr(controller, "set_keyboard_interactivity", None)
    pointer = pointer_for(host)
    if callable(setter) and pointer is not None:
        try:
            setter(pointer, enabled)
            return True
        except (OSError, RuntimeError) as exc:
            logger.debug("桥不接受键盘交互切换:%s", exc)
            return False
    # 普通窗口(X11 / 无层壳的 Wayland)天然能接受键盘输入,无需也不该干预。
    logger.debug("当前平台无需切换键盘交互(enabled=%s)", enabled)
    return False
