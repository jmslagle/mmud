# tests/test_config.py
import pathlib
import pytest
from mmud.config.loader import load_config
from mmud.config.schema import MudConfig


def test_none_returns_all_defaults():
    cfg = load_config(None)
    assert isinstance(cfg, MudConfig)
    assert cfg.server.host == "localhost"
    assert cfg.server.port == 4000
    assert cfg.combat.flee_threshold == 0.15
    assert cfg.spells.bless == []
    assert cfg.players == []


def test_server_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[server]\nhost = "mud.test"\nport = 5000\n')
    cfg = load_config(p)
    assert cfg.server.host == "mud.test"
    assert cfg.server.port == 5000


def test_missing_section_uses_defaults(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[server]\nhost = "x"\n')
    cfg = load_config(p)
    assert cfg.combat.backstab is False
    assert cfg.stealth.auto_sneak is False
    assert cfg.navigation.loop_path == ""


def test_spells_bless_array(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[[spells.bless]]\ncmd = "bless"\nmana_pct = 0.90\n\n'
        '[[spells.bless]]\ncmd = "protect"\nmana_pct = 0.70\n'
    )
    cfg = load_config(p)
    assert len(cfg.spells.bless) == 2
    assert cfg.spells.bless[0].cmd == "bless"
    assert cfg.spells.bless[0].mana_pct == 0.90
    assert cfg.spells.bless[1].cmd == "protect"


def test_party_bless_array(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[[party.bless]]\ncmd = "party bless"\nwait_seconds = 45\n')
    cfg = load_config(p)
    assert len(cfg.party.bless) == 1
    assert cfg.party.bless[0].cmd == "party bless"
    assert cfg.party.bless[0].wait_seconds == 45


def test_players_array(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[[players]]\nname = "Buddy"\nfriend = true\nremote_cmds = ["@do"]\n\n'
        '[[players]]\nname = "Enemy"\nfriend = false\ndont_heal = true\n'
    )
    cfg = load_config(p)
    assert len(cfg.players) == 2
    assert cfg.players[0].name == "Buddy"
    assert cfg.players[0].friend is True
    assert cfg.players[0].remote_cmds == ["@do"]
    assert cfg.players[1].dont_heal is True


def test_ui_defaults(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[ui]\nshow_right_panel = false\ndefault_tab = "players"\n')
    cfg = load_config(p)
    assert cfg.ui.show_right_panel is False
    assert cfg.ui.default_tab == "players"
    assert cfg.ui.show_stats_bar is True   # not set → default
