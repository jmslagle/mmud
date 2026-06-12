import pathlib
import tomllib
import pytest

from mmud.config.schema import MudConfig
from mmud.config.runtime import ConfigService
from mmud.events import GameEventBus, ConfigChanged


def _service(tmp_path=None):
    bus = GameEventBus()
    seen = []
    bus.subscribe(ConfigChanged, seen.append)
    path = (tmp_path / "config.toml") if tmp_path else None
    return ConfigService(MudConfig(), bus=bus, path=path), seen


def test_patch_updates_live_config_and_emits_event():
    svc, seen = _service()
    svc.patch("combat", "attack_cmd", "bash")
    assert svc.config.combat.attack_cmd == "bash"
    assert seen == [ConfigChanged(section="combat", field="attack_cmd", value="bash")]


def test_patch_coerces_string_to_field_type():
    svc, _ = _service()
    svc.patch("server", "port", "1234")
    assert svc.config.server.port == 1234
    assert isinstance(svc.config.server.port, int)


def test_patch_coerces_bool_strings():
    svc, _ = _service()
    svc.patch("stealth", "auto_sneak", "on")
    assert svc.config.stealth.auto_sneak is True
    svc.patch("stealth", "auto_sneak", "off")
    assert svc.config.stealth.auto_sneak is False


def test_patch_coerces_float():
    svc, _ = _service()
    svc.patch("combat", "flee_threshold", "0.25")
    assert svc.config.combat.flee_threshold == pytest.approx(0.25)


def test_unknown_section_raises():
    svc, _ = _service()
    with pytest.raises(KeyError):
        svc.patch("nope", "field", "x")


def test_unknown_field_raises():
    svc, _ = _service()
    with pytest.raises(KeyError):
        svc.patch("combat", "no_such_field", "x")


def test_persist_writes_file(tmp_path):
    svc, _ = _service(tmp_path)
    svc.patch("combat", "attack_cmd", "bash", persist=True)
    data = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert data["combat"]["attack_cmd"] == "bash"


def test_persist_without_path_raises():
    svc, _ = _service(None)
    with pytest.raises(RuntimeError):
        svc.patch("combat", "attack_cmd", "bash", persist=True)


def test_save_writes_current_config(tmp_path):
    svc, _ = _service(tmp_path)
    svc.patch("combat", "attack_cmd", "smash")
    assert not (tmp_path / "config.toml").exists()
    svc.save()
    data = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert data["combat"]["attack_cmd"] == "smash"
