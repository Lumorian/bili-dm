"""layer-shell 桥的 Qt ABI 兜底。

系统 `layer-shell-qt` 从 6.8.0 起用 Qt 6.12 编译,而 PyQt6 的 wheel 自带 Qt 6.11:
`libkoto-layer.so` 一 dlopen 就报 `version `Qt_6.12' not found (required by
/usr/lib/libLayerShellQtInterface.so.6)`。kotonoha 把这个异常当成"桥不可用",于是
layer-shell 能力整体消失——Wayland 上窗口退化成合成器排布的普通顶层窗:无法拖动、
无法点击穿透、无法定位(实测 niri 直接把它当平铺窗排进工作区)。

这里在 kotonoha 加载桥之前补一次 ABI 兜底,只在"桥确实加载不了"时动手:

1. 用 `RTLD_GLOBAL` 预载 venv 自带的 Qt 运行时库,让 soname 解析落到 6.11 那份上;
2. 预载一份与 venv Qt 同 ABI 的 `libLayerShellQtInterface.so.6`(由
   `scripts/fetch-layer-shell-qt.sh` 取回到缓存目录),桥的 NEEDED 条目即命中这个
   已加载的 soname,dlopen 成功。

没有兼容库时不假装成功:记一条明确的警告,让用户知道窗口为什么拖不动。
"""

from __future__ import annotations

import ctypes
import glob
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: 桥 NEEDED 的 soname(RTLD_GLOBAL 预载后按它命中)。
LAYER_SHELL_QT_SONAME = "libLayerShellQtInterface.so.6"
#: 兼容库的候选文件名:优先带 ABI 后缀的真实文件,最后才是不带后缀的链接。
LAYER_SHELL_QT_PATTERNS = (
    "libLayerShellQtInterface.so.6.*",
    "libLayerShellQtInterface.so.6",
    "libLayerShellQtInterface.so",
)
#: 桥间接依赖的 Qt 运行时库;预载它们,避免 soname 解析落到系统那套 6.12 上。
QT_RUNTIME_NAMES = (
    "libQt6Core.so.6",
    "libQt6Gui.so.6",
    "libQt6DBus.so.6",
    "libQt6WaylandClient.so.6",
)
#: 指向兼容库所在目录(或文件本身)的环境变量,压过缓存目录。
LIBRARY_DIR_ENV = "BILIDM_LAYER_SHELL_QT"
CACHE_SUBDIR = Path("bilidm-overlay") / "layer-shell-qt"

HINT = (
    "运行 overlay/scripts/fetch-layer-shell-qt.sh 取回与 venv Qt 同 ABI 的 "
    "layer-shell-qt 后重启;在此之前窗口会是普通顶层窗(无法拖动)。"
)


def cache_dir(env: dict[str, str] | None = None) -> Path:
    """兼容库的默认缓存目录(遵循 XDG_CACHE_HOME)。"""
    environ = os.environ if env is None else env
    base = environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / CACHE_SUBDIR


def search_dirs(env: dict[str, str] | None = None) -> list[Path]:
    """兼容库的搜索目录:环境变量在前(可指向文件),缓存目录在后。"""
    environ = os.environ if env is None else env
    dirs: list[Path] = []
    override = environ.get(LIBRARY_DIR_ENV)
    if override:
        path = Path(override).expanduser()
        dirs.append(path.parent if path.is_file() else path)
    dirs.append(cache_dir(environ))
    return dirs


def find_compatible_library(dirs: list[Path] | None = None) -> Path | None:
    """在搜索目录里挑一份 `libLayerShellQtInterface`;没有则 None。

    带 ABI 后缀的真实文件排在不带后缀的链接之前:预载的是文件本身,而链接可能在
    dlopen 时被它指向的另一套 Qt 库拖回去。"""
    for directory in dirs if dirs is not None else search_dirs():
        for pattern in LAYER_SHELL_QT_PATTERNS:
            matches = sorted(glob.glob(str(Path(directory) / pattern)))
            real = [Path(match) for match in matches if Path(match).resolve().is_file()]
            if real:
                return real[-1]
    return None


def pyqt_qt_lib_dir() -> Path | None:
    """PyQt6 wheel 自带的 Qt 运行时库目录;没有这个目录时返回 None。"""
    try:
        import PyQt6  # 只在需要时才 import:纯逻辑测试不必装 Qt
    except ImportError:  # pragma: no cover - 装了 PyQt6 才可能走到另一支
        return None
    lib_dir = Path(PyQt6.__file__).parent / "Qt6" / "lib"
    return lib_dir if lib_dir.is_dir() else None


def preload_qt_runtime(lib_dir: Path | None = None) -> list[Path]:
    """用 `RTLD_GLOBAL` 预载 venv 的 Qt 运行时库,返回成功的那些。"""
    directory = lib_dir if lib_dir is not None else pyqt_qt_lib_dir()
    if directory is None:
        return []
    loaded: list[Path] = []
    for name in QT_RUNTIME_NAMES:
        candidate = directory / name
        if candidate.is_file() and _load_global(candidate):
            loaded.append(candidate)
    return loaded


def ensure_compatible_layer_shell_qt(
    bridge_path: str | Path | None,
    *,
    dirs: list[Path] | None = None,
) -> Path | None:
    """桥加载前调用:系统库 ABI 不匹配时预载一份兼容库,成功则返回它的路径。

    `bridge_path` 为 None(没有桥,如 X11 / 未构建)时什么都不做——这里只负责
    "桥本该能用却因 ABI 加载不了"这一种情形,其余留给出错的那一层报原因。"""
    if bridge_path is None:
        return None
    if _loads(bridge_path):
        return None  # 系统库与本进程 Qt 同 ABI,不需要兜底
    compatible = find_compatible_library(dirs)
    if compatible is None:
        logger.warning(
            "layer-shell 桥无法加载:系统 layer-shell-qt 与本 venv 的 Qt ABI 不匹配。%s", HINT
        )
        return None
    preload_qt_runtime()
    if not _load_global(compatible):
        logger.warning("ABI 兜底失败:%s 同样加载不了。%s", compatible, HINT)
        return None
    logger.info("已预载 ABI 兼容的 layer-shell-qt:%s", compatible)
    return compatible


def bridge_library_path() -> Path | None:
    """kotonoha 会去 dlopen 的那个桥文件;没构建/找不到时 None。"""
    from kotonoha.platform import default_package_dir
    from kotonoha.platform.detect import find_layer_shell_library

    found = find_layer_shell_library(default_package_dir())
    return Path(found) if found else None


def ensure_for_session(platform_name: str | None = None) -> Path | None:
    """窗口构造前调用一次:桥的 Qt ABI 与本进程不匹配时预载兼容库。

    只在 Wayland 会话里动手——X11 上 layer-shell 本来就不参与,拖动走窗口管理器,
    那里报 ABI 警告只会误导。幂等且廉价(已加载的库再 dlopen 只加引用)。"""
    name = platform_name
    if name is None:
        try:
            from PyQt6.QtGui import QGuiApplication  # 纯逻辑测试不装 Qt
        except ImportError:  # pragma: no cover - 装了 PyQt6 才可能走到另一支
            return None
        name = QGuiApplication.platformName()
    if not name.startswith("wayland"):
        return None
    return ensure_compatible_layer_shell_qt(bridge_library_path())


def _loads(path: str | Path) -> bool:
    """这份库能否在当前进程里 dlopen(版本化符号不满足时 false)。"""
    try:
        ctypes.CDLL(str(path))
    except OSError:
        return False
    return True


def _load_global(path: str | Path) -> bool:
    """以 `RTLD_GLOBAL` 加载:后续库的 NEEDED 解析才能命中它。"""
    try:
        ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
    except OSError as exc:
        logger.debug("预载 %s 失败:%s", path, exc)
        return False
    return True
