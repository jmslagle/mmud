from __future__ import annotations
import dataclasses
import pathlib
import tomllib
from typing import TypeVar
from mmud.config.schema import (
    MudConfig, ServerConfig, LoginConfig, LoginStep, CombatConfig,
    BlessSpell, SpellsConfig, StealthConfig, NavigationConfig,
    ItemsConfig, PartyConfig, PartyBless, AfkConfig, PlayerRule, UiConfig,
    HealthConfig, SafetyConfig, RemoteConfig, PvpConfig, LearningConfig,
    CommerceConfig, SessionConfig, ScheduleConfig, ScheduleEvent, WebConfig,
)

_T = TypeVar("_T")


def unpack_dataclass(cls: type[_T], data: dict, *, skip: set[str] | None = None) -> _T:
    """Build a flat dataclass from a TOML dict using the dataclass's own fields +
    defaults. Unknown keys are ignored (forward-compat). Nested dataclass /
    list-of-dataclass fields go in `skip` and are handled by the caller."""
    skip = skip or set()
    kwargs = {f.name: data[f.name] for f in dataclasses.fields(cls)
              if f.name not in skip and f.name in data}
    return cls(**kwargs)


def load_config(path: pathlib.Path | None) -> MudConfig:
    if path is None:
        return MudConfig()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    cfg = MudConfig()

    # Flat sections: every field maps 1:1 to a TOML key. unpack_dataclass uses
    # the dataclass's own defaults for any missing/unknown key, so a present-but-
    # empty section yields the same default instance the old explicit code did.
    if s := data.get("server"):
        cfg.server = unpack_dataclass(ServerConfig, s)
    if l := data.get("login"):
        cfg.login = unpack_dataclass(LoginConfig, l, skip={"script"})
        cfg.login.script = [
            LoginStep(prompt=s.get("prompt", ""), reply=s.get("reply", ""))
            for s in l.get("script", [])
        ]
    if c := data.get("combat"):
        cfg.combat = unpack_dataclass(CombatConfig, c)
    if st := data.get("stealth"):
        cfg.stealth = unpack_dataclass(StealthConfig, st)
    if n := data.get("navigation"):
        cfg.navigation = unpack_dataclass(NavigationConfig, n)
    if it := data.get("items"):
        cfg.items = unpack_dataclass(ItemsConfig, it)
    if a := data.get("afk"):
        cfg.afk = unpack_dataclass(AfkConfig, a)
    if h := data.get("health"):
        cfg.health = unpack_dataclass(HealthConfig, h)
    if sf := data.get("safety"):
        cfg.safety = unpack_dataclass(SafetyConfig, sf)
    if r := data.get("remote"):
        cfg.remote = unpack_dataclass(RemoteConfig, r)
    if pv := data.get("pvp"):
        cfg.pvp = unpack_dataclass(PvpConfig, pv)
    if le := data.get("learning"):
        cfg.learning = unpack_dataclass(LearningConfig, le)
    if co := data.get("commerce"):
        cfg.commerce = unpack_dataclass(CommerceConfig, co)
    if se := data.get("session"):
        cfg.session = unpack_dataclass(SessionConfig, se)
    if u := data.get("ui"):
        cfg.ui = unpack_dataclass(UiConfig, u)
    if w := data.get("web"):
        cfg.web = unpack_dataclass(WebConfig, w)

    # Sections with nested list-of-dataclass fields: unpack the flat fields,
    # then build the nested lists explicitly.
    if sp := data.get("spells"):
        cfg.spells = unpack_dataclass(SpellsConfig, sp, skip={"bless"})
        cfg.spells.bless = [
            BlessSpell(cmd=b.get("cmd", ""), mana_pct=b.get("mana_pct", 0.80),
                       interval_s=b.get("interval_s", 600.0),
                       refresh_on=b.get("refresh_on", ""))
            for b in sp.get("bless", [])
        ]
    if p := data.get("party"):
        cfg.party = unpack_dataclass(PartyConfig, p, skip={"bless"})
        cfg.party.bless = [
            PartyBless(cmd=b.get("cmd", ""), wait_seconds=b.get("wait_seconds", 60))
            for b in p.get("bless", [])
        ]
    if sc := data.get("schedule"):
        cfg.schedule = ScheduleConfig(events=[
            unpack_dataclass(ScheduleEvent, ev) for ev in sc.get("events", [])
        ])
    cfg.players = [
        unpack_dataclass(PlayerRule, pl) for pl in data.get("players", [])
    ]
    return cfg
