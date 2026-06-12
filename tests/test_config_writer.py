import pathlib
import tomllib
import pytest

from mmud.config.schema import MudConfig
from mmud.config.writer import write_config


def _write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_roundtrip_scalar_change(tmp_path):
    p = _write(tmp_path, "[server]\nhost = \"old\"\nport = 4000\n")
    cfg = MudConfig()
    cfg.server.host = "new"
    cfg.server.port = 9999
    write_config(cfg, p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["server"]["host"] == "new"
    assert data["server"]["port"] == 9999


def test_creates_file_when_missing(tmp_path):
    p = tmp_path / "config.toml"
    cfg = MudConfig()
    cfg.server.host = "fresh"
    write_config(cfg, p)
    assert p.exists()
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["server"]["host"] == "fresh"


def test_preserves_comments_and_unknown_keys(tmp_path):
    text = (
        "# top of file\n"
        "[server]\n"
        "host = \"old\"  # inline note\n"
        "port = 4000\n"
        "future_key = \"keep me\"\n"
    )
    p = _write(tmp_path, text)
    cfg = MudConfig()
    cfg.server.host = "new"
    write_config(cfg, p)
    out = p.read_text(encoding="utf-8")
    assert "# top of file" in out
    assert "# inline note" in out
    assert "future_key" in out
    assert "keep me" in out
    assert "host = \"new\"" in out


def test_atomic_no_partial_file_on_dump_error(tmp_path, monkeypatch):
    text = "[server]\nhost = \"good\"\nport = 4000\n"
    p = _write(tmp_path, text)
    cfg = MudConfig()
    cfg.server.host = "halfway"
    import mmud.config.writer as writer_mod
    def boom(_doc):
        raise RuntimeError("serialization failed")
    monkeypatch.setattr(writer_mod.tomlkit, "dumps", boom)
    with pytest.raises(RuntimeError):
        write_config(cfg, p)
    assert p.read_text(encoding="utf-8") == text
    assert not (tmp_path / "config.toml.tmp").exists()


def test_roundtrip_scalar_list_and_dataclass_list(tmp_path):
    # scalar-list (combat.monster_priority) + dataclass-list (spells.bless) survive
    from mmud.config.schema import BlessSpell
    p = tmp_path / "config.toml"
    cfg = MudConfig()
    cfg.combat.monster_priority = ["orc", "goblin"]
    cfg.spells.bless = [BlessSpell(cmd="cast bless", mana_pct=0.5)]
    cfg.players  # top-level array; leave empty
    write_config(cfg, p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["combat"]["monster_priority"] == ["orc", "goblin"]
    assert data["spells"]["bless"][0]["cmd"] == "cast bless"
    assert data["spells"]["bless"][0]["mana_pct"] == pytest.approx(0.5)


def test_roundtrip_players_array(tmp_path):
    from mmud.config.schema import PlayerRule
    p = tmp_path / "config.toml"
    cfg = MudConfig()
    cfg.players = [PlayerRule(name="Krang", friend=True, remote_cmds=["*"], dont_heal=False)]
    write_config(cfg, p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["players"][0]["name"] == "Krang"
    assert data["players"][0]["friend"] is True
    assert data["players"][0]["remote_cmds"] == ["*"]
