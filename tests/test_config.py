import argparse

from bilidm_overlay.config import Config, default_socket_path, load, merge_cli


def test_default_socket_uses_runtime_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert default_socket_path() == f"{tmp_path}/bilidm-danmaku.sock"


def test_defaults():
    cfg = Config()
    assert cfg.mode == "merged"
    assert cfg.max_rows == 80
    assert not hasattr(cfg, "ttl_seconds")  # TTL 机制已移除,仅保留计数淘汰
    assert cfg.click_through is True
    assert cfg.opacity == 0.85
    assert cfg.position == [24, 100]


def test_load_expands_env_and_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    f = tmp_path / "cfg.yaml"
    f.write_text("socket: $XDG_RUNTIME_DIR/test.sock\nwidth: 600\nrooms:\n  - bilibili:689422\n")
    cfg = load(f)
    assert cfg.socket == f"{tmp_path}/test.sock"
    assert cfg.width == 600
    assert cfg.height == 400
    assert cfg.rooms == ["bilibili:689422"]
    # 未写的字段保持默认


def test_load_missing_file_is_defaults(tmp_path):
    cfg = load(tmp_path / "nope.yaml")
    assert cfg.mode == "merged"


def test_merge_cli_overrides():
    cfg = Config()
    args = argparse.Namespace(
        room=["bilibili:689422"], socket="/tmp/x.sock", no_tray=True, merged=None, per_room=None
    )
    merged = merge_cli(cfg, args)
    assert merged.rooms == ["bilibili:689422"]
    assert merged.socket == "/tmp/x.sock"
    assert merged.no_tray is True
    # flags 未给时不变
    assert merged.mode == "merged"


def test_merge_cli_per_room_flag_wins():
    cfg = Config()
    args = argparse.Namespace(
        room=["bilibili:1", "bilibili:2"], merged=None, per_room=True, socket=None, no_tray=None
    )
    assert merge_cli(cfg, args).mode == "per-room"


def test_save_roundtrip(tmp_path):
    from bilidm_overlay.config import save

    cfg = Config()
    cfg.width, cfg.height = 500, 360
    cfg.position = [64, 128]
    save(cfg, tmp_path / "c.yaml")
    loaded = load(tmp_path / "c.yaml")
    assert loaded.width == 500 and loaded.height == 360
    assert loaded.position == [64, 128]


def test_load_ignores_obsolete_ttl_key(tmp_path):
    """老配置里的 ttl_seconds 键应被静默忽略,不报错也不产生字段。"""
    f = tmp_path / "cfg.yaml"
    f.write_text("max_rows: 42\nttl_seconds: 30.0\n")
    cfg = load(f)
    assert cfg.max_rows == 42
    assert not hasattr(cfg, "ttl_seconds")


def test_theme_defaults_to_dark(tmp_path):
    cfg = Config()
    assert cfg.theme == "dark"


def test_theme_loaded_from_yaml(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("theme: light\n", encoding="utf-8")
    cfg = load(path)
    assert cfg.theme == "light"


def test_cli_theme_overrides(tmp_path):
    cfg = load(tmp_path / "missing.yaml")
    merged = merge_cli(cfg, argparse.Namespace(theme="light"))
    assert merged.theme == "light"


def test_font_size_default_is_official_12px():
    assert Config().font_size == 12  # 官方 .chat-history-list{font-size:12px}
