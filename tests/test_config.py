import argparse

from bilidm_overlay.config import Config, default_socket_path, load, merge_cli


def test_default_socket_uses_runtime_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert default_socket_path() == f"{tmp_path}/bilidm-danmaku.sock"


def test_defaults():
    cfg = Config()
    assert cfg.mode == "merged"
    assert cfg.max_rows == 80
    assert cfg.ttl_seconds == 30.0
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
    assert cfg.ttl_seconds == 30.0


def test_load_missing_file_is_defaults(tmp_path):
    cfg = load(tmp_path / "nope.yaml")
    assert cfg.mode == "merged"


def test_merge_cli_overrides():
    cfg = Config()
    args = argparse.Namespace(room=["bilibili:689422"], socket="/tmp/x.sock", no_tray=True,
                              merged=None, per_room=None)
    merged = merge_cli(cfg, args)
    assert merged.rooms == ["bilibili:689422"]
    assert merged.socket == "/tmp/x.sock"
    assert merged.no_tray is True
    # flags 未给时不变
    assert merged.mode == "merged"


def test_merge_cli_per_room_flag_wins():
    cfg = Config()
    args = argparse.Namespace(room=["bilibili:1", "bilibili:2"], merged=None, per_room=True,
                              socket=None, no_tray=None)
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
    # 未变字段保持默认
    assert loaded.ttl_seconds == 30.0
