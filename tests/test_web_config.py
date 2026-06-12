from __future__ import annotations
import pathlib
from mmud.config.loader import load_config
from mmud.config.schema import MudConfig, WebConfig


def test_web_config_defaults():
    cfg = WebConfig()
    assert cfg.enabled is False
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8080


def test_mudconfig_has_web_default():
    cfg = MudConfig()
    assert isinstance(cfg.web, WebConfig)
    assert cfg.web.enabled is False


def test_loader_absent_web_section(tmp_path):
    p = tmp_path / "char.toml"
    p.write_text('[server]\nhost = "x"\nport = 1\n', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.web.enabled is False


def test_loader_parses_web_section(tmp_path):
    p = tmp_path / "char.toml"
    p.write_text('[web]\nenabled = true\nhost = "0.0.0.0"\nport = 9000\n', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.web.enabled is True
    assert cfg.web.host == "0.0.0.0"
    assert cfg.web.port == 9000
