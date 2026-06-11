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


def test_health_and_safety_sections(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        """
[health]
blind_cmd = "cast purify vision"
poison_cmd = "cast neutralize poison"

[safety]
hangup_on_death = true
hangup_players = ["BadGuy", "Killer"]
panic_cmd = "recall"
reconnect = true
max_redials = 5
"""
    )
    cfg = load_config(p)
    assert cfg.health.blind_cmd == "cast purify vision"
    assert cfg.health.poison_cmd == "cast neutralize poison"
    assert cfg.health.disease_cmd == ""
    assert cfg.safety.hangup_on_death is True
    assert cfg.safety.hangup_players == ["BadGuy", "Killer"]
    assert cfg.safety.panic_cmd == "recall"
    assert cfg.safety.reconnect is True
    assert cfg.safety.max_redials == 5


def test_health_and_safety_defaults():
    cfg = load_config(None)
    assert cfg.health.blind_cmd == ""
    assert cfg.safety.hangup_on_death is True
    assert cfg.safety.reconnect is False
    assert cfg.safety.max_redials == 3


def test_remote_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        """
[remote]
enabled = true
tell_format = "/{name} {text}"

[[players]]
name = "Friend"
friend = true
remote_cmds = ["*"]
"""
    )
    cfg = load_config(p)
    assert cfg.remote.enabled is True
    assert cfg.remote.tell_format == "/{name} {text}"
    assert cfg.players[0].remote_cmds == ["*"]


def test_remote_disabled_by_default():
    cfg = load_config(None)
    assert cfg.remote.enabled is False
