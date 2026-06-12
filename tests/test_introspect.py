import pytest
from mmud.config import introspect


def test_section_dataclasses_excludes_players():
    d = introspect.section_dataclasses()
    assert "server" in d and "combat" in d
    assert "players" not in d
    from mmud.config.schema import ServerConfig
    assert d["server"] is ServerConfig


def test_section_names_has_players_last():
    names = introspect.section_names()
    assert names[-1] == "players"
    assert "server" in names and "ui" in names


def test_field_type_resolves_real_types():
    assert introspect.field_type("server", "port") is int
    assert introspect.field_type("server", "host") is str
    assert introspect.field_type("combat", "flee_threshold") is float
    assert introspect.field_type("stealth", "auto_sneak") is bool


def test_field_type_unknown_raises():
    with pytest.raises(KeyError):
        introspect.field_type("nope", "x")
    with pytest.raises(KeyError):
        introspect.field_type("combat", "no_such")


def test_is_scalar_field_and_raises():
    assert introspect.is_scalar_field("combat", "attack_cmd") is True
    # monster_priority is list[str] -> not scalar
    assert introspect.is_scalar_field("combat", "monster_priority") is False
    with pytest.raises(KeyError):
        introspect.is_scalar_field("combat", "no_such")


def test_scalar_fields_skips_lists():
    sf = introspect.scalar_fields("combat")
    assert "attack_cmd" in sf and "flee_threshold" in sf
    assert "monster_priority" not in sf       # list[str] excluded


def test_scalar_list_fields():
    assert "monster_priority" in introspect.scalar_list_fields("combat")
    assert "bless" not in introspect.scalar_list_fields("spells")   # list of dataclass


def test_dataclass_list_fields():
    from mmud.config.schema import BlessSpell
    dlf = dict(introspect.dataclass_list_fields("spells"))
    assert dlf.get("bless") is BlessSpell
