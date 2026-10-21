"""layer-shell Qt ABI 兜底:选库、预载、只在需要时动手(纯逻辑,不依赖 Qt 会话)。"""

import ctypes
from pathlib import Path

import pytest

from bilidm_overlay import layershell_qt_compat as compat


def _touch(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# --- 缓存目录与搜索顺序 ---


def test_cache_dir_follows_xdg_cache_home(tmp_path):
    env = {"XDG_CACHE_HOME": str(tmp_path / "cache")}
    assert compat.cache_dir(env) == tmp_path / "cache" / "bilidm-overlay" / "layer-shell-qt"


def test_search_dirs_puts_env_override_first(tmp_path):
    override = tmp_path / "vendored"
    env = {
        compat.LIBRARY_DIR_ENV: str(override),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }
    dirs = compat.search_dirs(env)
    assert dirs[0] == override
    assert dirs[-1] == compat.cache_dir(env)


def test_search_dirs_accepts_env_pointing_at_a_file(tmp_path):
    """环境变量可以指向库文件本身(比指向目录更直接),此时取它的父目录。"""
    lib = _touch(tmp_path / "vendored" / "libLayerShellQtInterface.so.6.7.5")
    env = {compat.LIBRARY_DIR_ENV: str(lib), "XDG_CACHE_HOME": str(tmp_path / "cache")}
    assert compat.search_dirs(env)[0] == tmp_path / "vendored"


# --- 选库 ---


def test_find_picks_abi_suffixed_file_over_bare_symlink(tmp_path):
    """带 ABI 后缀的真实文件优先于不带后缀的链接:预载的是文件本身,链接在别的
    目录里可能指不到目标。"""
    _touch(tmp_path / "libLayerShellQtInterface.so.6.7.5")
    (tmp_path / "libLayerShellQtInterface.so.6").symlink_to("missing-target.so")
    found = compat.find_compatible_library([tmp_path])
    assert found is not None and found.name == "libLayerShellQtInterface.so.6.7.5"


def test_find_returns_none_when_directory_is_empty(tmp_path):
    assert compat.find_compatible_library([tmp_path]) is None


def test_find_skips_dangling_symlink(tmp_path):
    (tmp_path / "libLayerShellQtInterface.so.6.7.5").symlink_to("gone.so")
    assert compat.find_compatible_library([tmp_path]) is None


def test_find_prefers_earlier_directories(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    _touch(first / "libLayerShellQtInterface.so.6.7.5")
    _touch(second / "libLayerShellQtInterface.so.6.8.0")
    found = compat.find_compatible_library([first, second])
    assert found is not None and found.parent == first


# --- 是否需要兜底 ---


def _bridge(tmp_path: Path) -> Path:
    return _touch(tmp_path / "libkoto-layer.so")


def test_no_bridge_means_no_work(tmp_path):
    """没有桥(X11、未构建)时不动手:这不是 ABI 问题。"""
    assert compat.ensure_compatible_layer_shell_qt(None) is None


def test_bridge_that_loads_needs_no_fallback(tmp_path, monkeypatch):
    """桥本来能加载时不得预载任何兼容库:否则会平白把另一套库塞进进程。"""
    loaded = []
    monkeypatch.setattr(compat, "_loads", lambda p: True)
    monkeypatch.setattr(compat, "_load_global", lambda p: loaded.append(p) or True)
    monkeypatch.setattr(compat, "preload_qt_runtime", lambda *a: loaded.append("qt-runtime") or [])
    assert compat.ensure_compatible_layer_shell_qt(_bridge(tmp_path), dirs=[tmp_path]) is None
    assert loaded == []


def test_missing_compatible_library_warns_and_does_nothing(tmp_path, monkeypatch, caplog):
    """没有兼容库时不假装成功:必须留下明确警告,否则用户只知道窗口拖不动。"""
    monkeypatch.setattr(compat, "_loads", lambda p: False)
    monkeypatch.setattr(compat, "preload_qt_runtime", lambda *a: [])
    with caplog.at_level("WARNING"):
        result = compat.ensure_compatible_layer_shell_qt(_bridge(tmp_path), dirs=[tmp_path])
    assert result is None
    assert "ABI" in caplog.text and "fetch-layer-shell-qt.sh" in caplog.text


def test_matching_library_is_preloaded_with_qt_runtime_first(tmp_path, monkeypatch):
    """顺序要求:先 Qt 运行时、后兼容库——反过来的话兼容库的 NEEDED 仍会落到系统那份。"""
    order = []
    compatible = _touch(tmp_path / "libLayerShellQtInterface.so.6.7.5")
    monkeypatch.setattr(compat, "_loads", lambda p: False)
    monkeypatch.setattr(compat, "preload_qt_runtime", lambda *a: order.append("qt") or [])
    monkeypatch.setattr(compat, "_load_global", lambda p: order.append(Path(p).name) or True)
    result = compat.ensure_compatible_layer_shell_qt(_bridge(tmp_path), dirs=[tmp_path])
    assert result == compatible
    assert order == ["qt", "libLayerShellQtInterface.so.6.7.5"]


def test_preload_failure_is_reported_not_swallowed(tmp_path, monkeypatch, caplog):
    _touch(tmp_path / "libLayerShellQtInterface.so.6.7.5")  # 有库,但这份也加载不了
    monkeypatch.setattr(compat, "_loads", lambda p: False)
    monkeypatch.setattr(compat, "preload_qt_runtime", lambda *a: [])
    monkeypatch.setattr(compat, "_load_global", lambda p: False)
    with caplog.at_level("WARNING"):
        assert compat.ensure_compatible_layer_shell_qt(_bridge(tmp_path), dirs=[tmp_path]) is None
    assert "兜底失败" in caplog.text


# --- 会话门:只在 Wayland 动手 ---


def test_session_shim_is_skipped_on_x11(monkeypatch):
    called = []
    monkeypatch.setattr(compat, "ensure_compatible_layer_shell_qt", lambda p: called.append(p))
    assert compat.ensure_for_session("xcb") is None
    assert called == []


def test_session_shim_runs_on_wayland(monkeypatch, tmp_path):
    bridge = _bridge(tmp_path)
    called = []
    monkeypatch.setattr(compat, "bridge_library_path", lambda: bridge)
    monkeypatch.setattr(
        compat, "ensure_compatible_layer_shell_qt", lambda p: called.append(p) or "preloaded"
    )
    assert compat.ensure_for_session("wayland") == "preloaded"
    assert called == [bridge]


# --- 加载器本身 ---


def test_load_global_reports_failure_without_raising(tmp_path, monkeypatch):
    def _boom(path, mode=0):
        raise OSError("nope")

    monkeypatch.setattr(ctypes, "CDLL", _boom)
    assert compat._load_global(tmp_path / "lib.so") is False


def test_loads_is_false_for_a_missing_file(tmp_path):
    assert compat._loads(tmp_path / "does-not-exist.so") is False


# --- Qt 运行时预载 ---


def test_preload_qt_runtime_loads_only_existing_named_libs(tmp_path, monkeypatch):
    """只预载自己列出的那几个 soname,目录里其它文件一律不碰。"""
    (tmp_path / "libQt6Core.so.6").write_text("x")
    (tmp_path / "libQt6Gui.so.6").write_text("x")
    (tmp_path / "libQt6SomethingElse.so.6").write_text("x")
    loaded = []
    monkeypatch.setattr(compat, "_load_global", lambda p: loaded.append(Path(p).name) or True)
    result = compat.preload_qt_runtime(tmp_path)
    assert loaded == ["libQt6Core.so.6", "libQt6Gui.so.6"], "顺序固定且不含未列出的库"
    assert [p.name for p in result] == loaded


def test_preload_qt_runtime_skips_libs_that_fail_to_load(tmp_path, monkeypatch):
    (tmp_path / "libQt6Core.so.6").write_text("x")
    monkeypatch.setattr(compat, "_load_global", lambda p: False)
    assert compat.preload_qt_runtime(tmp_path) == []


def test_preload_qt_runtime_without_a_lib_dir_is_a_noop(monkeypatch):
    monkeypatch.setattr(compat, "pyqt_qt_lib_dir", lambda: None)
    assert compat.preload_qt_runtime(None) == []


# --- 会话探测 ---


def test_session_shim_detects_the_platform_when_not_given_one(monkeypatch):
    """不传平台名时自己读;offscreen(测试环境)不是 wayland,应当什么都不做。"""
    called = []
    monkeypatch.setattr(compat, "ensure_compatible_layer_shell_qt", lambda p: called.append(p))
    assert compat.ensure_for_session() is None
    assert called == []


def test_bridge_library_path_returns_none_without_a_bridge(monkeypatch, tmp_path):
    from kotonoha.platform import detect

    monkeypatch.setattr(detect, "find_layer_shell_library", lambda package_dir: None)
    assert compat.bridge_library_path() is None


def test_bridge_library_path_wraps_the_found_file(monkeypatch, tmp_path):
    from kotonoha.platform import detect

    bridge = tmp_path / "libkoto-layer.so"
    bridge.write_text("x")
    monkeypatch.setattr(detect, "find_layer_shell_library", lambda package_dir: str(bridge))
    assert compat.bridge_library_path() == bridge


def test_loads_succeeds_for_a_real_shared_library():
    """_loads 的正向分支:随手拿一个确实能 dlopen 的库(缺它时退回 False 即可)。"""
    import ctypes.util

    candidate = ctypes.util.find_library("m") or ctypes.util.find_library("c")
    if candidate is None:
        pytest.skip("找不到可用于验证 dlopen 的系统库")
    assert compat._loads(candidate) is True
