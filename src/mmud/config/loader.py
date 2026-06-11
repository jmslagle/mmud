from __future__ import annotations
import pathlib
import tomllib
from mmud.config.schema import (
    MudConfig, ServerConfig, LoginConfig, CombatConfig,
    BlessSpell, SpellsConfig, StealthConfig, NavigationConfig,
    ItemsConfig, PartyConfig, PartyBless, AfkConfig, PlayerRule, UiConfig,
    HealthConfig, SafetyConfig, RemoteConfig, PvpConfig, LearningConfig,
)


def load_config(path: pathlib.Path | None) -> MudConfig:
    if path is None:
        return MudConfig()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    cfg = MudConfig()

    if s := data.get("server"):
        cfg.server = ServerConfig(
            host=s.get("host", "localhost"),
            port=s.get("port", 4000),
        )
    if l := data.get("login"):
        cfg.login = LoginConfig(
            username=l.get("username", ""),
            password=l.get("password", ""),
            auto_login=l.get("auto_login", False),
            character=l.get("character", ""),
        )
    if c := data.get("combat"):
        cfg.combat = CombatConfig(
            attack_cmd=c.get("attack_cmd", "kill"),
            flee_threshold=c.get("flee_threshold", 0.15),
            rest_threshold=c.get("rest_threshold", 0.40),
            backstab=c.get("backstab", False),
            polite_attacks=c.get("polite_attacks", False),
            attack_order=c.get("attack_order", "first"),
            mana_attack_pct=c.get("mana_attack_pct", 0.20),
            max_monsters=c.get("max_monsters", 0),
            max_monster_exp=c.get("max_monster_exp", 0),
            run_backwards=c.get("run_backwards", False),
            run_if_bs_fails=c.get("run_if_bs_fails", False),
            monster_priority=c.get("monster_priority", []),
        )
    if sp := data.get("spells"):
        cfg.spells = SpellsConfig(
            attack=sp.get("attack", ""),
            pre_attack=sp.get("pre_attack", ""),
            multi_attack=sp.get("multi_attack", ""),
            heal=sp.get("heal", ""),
            heal_hp_pct=sp.get("heal_hp_pct", 0.50),
            mana_heal=sp.get("mana_heal", ""),
            mana_heal_pct=sp.get("mana_heal_pct", 0.30),
            bless=[
                BlessSpell(cmd=b.get("cmd", ""), mana_pct=b.get("mana_pct", 0.80))
                for b in sp.get("bless", [])
            ],
            max_cast_count=sp.get("max_cast_count", 0),
            cast_weapon_cmd=sp.get("cast_weapon_cmd", ""),
            melee_weapon_cmd=sp.get("melee_weapon_cmd", ""),
        )
    if st := data.get("stealth"):
        cfg.stealth = StealthConfig(
            auto_sneak=st.get("auto_sneak", False),
            sneak_cmd=st.get("sneak_cmd", "sneak"),
            must_sneak=st.get("must_sneak", False),
            auto_hide=st.get("auto_hide", False),
            hide_cmd=st.get("hide_cmd", "hide"),
        )
    if n := data.get("navigation"):
        cfg.navigation = NavigationConfig(
            loop_path=n.get("loop_path", ""),
            start_room=n.get("start_room", ""),
            auto_start=n.get("auto_start", False),
            flee_rooms=n.get("flee_rooms", 3),
            can_pick_locks=n.get("can_pick_locks", False),
            can_disarm_traps=n.get("can_disarm_traps", False),
        )
    if it := data.get("items"):
        cfg.items = ItemsConfig(
            auto_get=it.get("auto_get", False),
            auto_cash=it.get("auto_cash", True),
            collect_copper=it.get("collect_copper", True),
            collect_silver=it.get("collect_silver", True),
            collect_gold=it.get("collect_gold", True),
            collect_platinum=it.get("collect_platinum", True),
            collect_runic=it.get("collect_runic", False),
            runic_name=it.get("runic_name", "runic"),
            dont_go_heavy=it.get("dont_go_heavy", True),
            dont_go_medium=it.get("dont_go_medium", False),
            max_coins=it.get("max_coins", 0),
            max_wealth=it.get("max_wealth", 0),
            min_wealth=it.get("min_wealth", 0),
        )
    if p := data.get("party"):
        cfg.party = PartyConfig(
            heal_spell=p.get("heal_spell", ""),
            heal_hp_pct=p.get("heal_hp_pct", 0.50),
            wait_hp_pct=p.get("wait_hp_pct", 0.30),
            wait_max_seconds=p.get("wait_max_seconds", 30),
            wait_cmd=p.get("wait_cmd", "wait"),
            resume_cmd=p.get("resume_cmd", "go"),
            attack_with_leader=p.get("attack_with_leader", True),
            share_cash=p.get("share_cash", False),
            bless=[
                PartyBless(cmd=b.get("cmd", ""), wait_seconds=b.get("wait_seconds", 60))
                for b in p.get("bless", [])
            ],
        )
    if a := data.get("afk"):
        cfg.afk = AfkConfig(
            enabled=a.get("enabled", False),
            timeout_minutes=a.get("timeout_minutes", 5),
            reply=a.get("reply", "I am AFK"),
            hangup_on_low_hp=a.get("hangup_on_low_hp", False),
            alert=a.get("alert", False),
            popup_missed=a.get("popup_missed", True),
        )
    if h := data.get("health"):
        cfg.health = HealthConfig(
            blind_cmd=h.get("blind_cmd", ""),
            poison_cmd=h.get("poison_cmd", ""),
            disease_cmd=h.get("disease_cmd", ""),
            freedom_cmd=h.get("freedom_cmd", ""),
        )
    if sf := data.get("safety"):
        cfg.safety = SafetyConfig(
            hangup_on_death=sf.get("hangup_on_death", True),
            hangup_players=sf.get("hangup_players", []),
            panic_cmd=sf.get("panic_cmd", ""),
            reconnect=sf.get("reconnect", False),
            max_redials=sf.get("max_redials", 3),
        )
    if r := data.get("remote"):
        cfg.remote = RemoteConfig(
            enabled=r.get("enabled", False),
            tell_format=r.get("tell_format", "/{name} {text}"),
        )
    if pv := data.get("pvp"):
        cfg.pvp = PvpConfig(
            action=pv.get("action", ""),
            spell=pv.get("spell", ""),
            flee_rooms=pv.get("flee_rooms", 2),
            hangup_delay_s=pv.get("hangup_delay_s", 0),
        )
    if le := data.get("learning"):
        cfg.learning = LearningConfig(
            enabled=le.get("enabled", False),
            store_path=le.get("store_path", "gamedb.json"),
        )
    cfg.players = [
        PlayerRule(
            name=pl.get("name", ""),
            friend=pl.get("friend", False),
            remote_cmds=pl.get("remote_cmds", []),
            dont_heal=pl.get("dont_heal", False),
            dont_bless=pl.get("dont_bless", False),
        )
        for pl in data.get("players", [])
    ]
    if u := data.get("ui"):
        cfg.ui = UiConfig(
            show_right_panel=u.get("show_right_panel", True),
            show_stats_bar=u.get("show_stats_bar", True),
            default_tab=u.get("default_tab", "conversations"),
        )
    return cfg
