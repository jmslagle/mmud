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


def test_phase4_combat_config(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        """
[combat]
max_monsters = 3
max_monster_exp = 5000
run_backwards = true
run_if_bs_fails = true
monster_priority = ["ancient dragon", "orc chieftain"]

[spells]
max_cast_count = 4
cast_weapon_cmd = "arm staff"
melee_weapon_cmd = "arm warhammer"

[pvp]
action = "flee"
spell = ""
flee_rooms = 2
hangup_delay_s = 10
"""
    )
    cfg = load_config(p)
    assert cfg.combat.max_monsters == 3
    assert cfg.combat.max_monster_exp == 5000
    assert cfg.combat.run_backwards is True
    assert cfg.combat.monster_priority == ["ancient dragon", "orc chieftain"]
    assert cfg.spells.max_cast_count == 4
    assert cfg.spells.melee_weapon_cmd == "arm warhammer"
    assert cfg.pvp.action == "flee"
    assert cfg.pvp.hangup_delay_s == 10


def test_phase4_defaults():
    cfg = load_config(None)
    assert cfg.combat.max_monsters == 0          # 0 = no limit
    assert cfg.combat.max_monster_exp == 0       # 0 = no limit
    assert cfg.spells.max_cast_count == 0        # 0 = unlimited
    assert cfg.pvp.action == ""                  # "" = ignore players


def test_phase5_items_config(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[items]
max_coins = 500
max_wealth = 20000
min_wealth = 1000
""")
    cfg = load_config(p)
    assert cfg.items.max_coins == 500
    assert cfg.items.max_wealth == 20000
    assert cfg.items.min_wealth == 1000


def test_phase5_items_defaults():
    cfg = load_config(None)
    assert cfg.items.max_coins == 0      # 0 = no limit
    assert cfg.items.max_wealth == 0
    assert cfg.items.min_wealth == 0


def test_learning_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[learning]
enabled = true
store_path = "mydb.json"
""")
    cfg = load_config(p)
    assert cfg.learning.enabled is True
    assert cfg.learning.store_path == "mydb.json"


def test_learning_disabled_by_default():
    cfg = load_config(None)
    assert cfg.learning.enabled is False
    assert cfg.learning.store_path == "gamedb.json"


def test_phase6_navigation_config(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[navigation]
auto_search = true
search_max = 2
roam = true
bash_doors = true
""")
    cfg = load_config(p)
    assert cfg.navigation.auto_search is True
    assert cfg.navigation.search_max == 2
    assert cfg.navigation.roam is True
    assert cfg.navigation.bash_doors is True


def test_phase6_navigation_defaults():
    cfg = load_config(None)
    assert cfg.navigation.auto_search is False
    assert cfg.navigation.search_max == 3
    assert cfg.navigation.roam is False
    assert cfg.navigation.bash_doors is False


def test_commerce_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[commerce]
bank_room = "BANK"
shop_room = "SHOP"
train_room = "TRNR"
sell_items = ["rusty sword"]
buy_items = ["torch"]
auto_train = true
""")
    cfg = load_config(p)
    assert cfg.commerce.bank_room == "BANK"
    assert cfg.commerce.shop_room == "SHOP"
    assert cfg.commerce.train_room == "TRNR"
    assert cfg.commerce.sell_items == ["rusty sword"]
    assert cfg.commerce.buy_items == ["torch"]
    assert cfg.commerce.auto_train is True


def test_commerce_defaults():
    cfg = load_config(None)
    assert cfg.commerce.bank_room == ""       # "" = banking disabled
    assert cfg.commerce.auto_train is False
    assert cfg.commerce.sell_items == []


def test_session_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[session]
capture_file = "session.log"
max_hours_per_day = 4
min_exp_rate = 5000
grace_minutes = 10
low_rate_action = "relog"
logout_cmd = "=x"
""")
    cfg = load_config(p)
    assert cfg.session.capture_file == "session.log"
    assert cfg.session.max_hours_per_day == 4
    assert cfg.session.min_exp_rate == 5000
    assert cfg.session.grace_minutes == 10
    assert cfg.session.low_rate_action == "relog"
    assert cfg.session.logout_cmd == "=x"


def test_session_defaults():
    cfg = load_config(None)
    assert cfg.session.capture_file == ""        # "" = capture off
    assert cfg.session.max_hours_per_day == 0    # 0 = unlimited
    assert cfg.session.min_exp_rate == 0         # 0 = disabled
    assert cfg.session.grace_minutes == 15
    assert cfg.session.low_rate_action == "hangup"
    assert cfg.session.logout_cmd == "x"


def test_party_additions(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[party]
status_cmd = "par"
status_interval_s = 30
""")
    cfg = load_config(p)
    assert cfg.party.status_cmd == "par"
    assert cfg.party.status_interval_s == 30


def test_party_additions_defaults():
    cfg = load_config(None)
    assert cfg.party.status_cmd == ""        # "" = no periodic refresh
    assert cfg.party.status_interval_s == 60


def test_schedule_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[[schedule.events]]
type = "relog"
every_seconds = 3600
count = 0

[[schedule.events]]
type = "command"
every_seconds = 600
count = 3
arg = "say hello||say hi"
""")
    cfg = load_config(p)
    assert len(cfg.schedule.events) == 2
    assert cfg.schedule.events[0].type == "relog"
    assert cfg.schedule.events[0].every_seconds == 3600
    assert cfg.schedule.events[0].count == 0          # 0 = forever
    assert cfg.schedule.events[1].arg == "say hello||say hi"


def test_schedule_empty_by_default():
    cfg = load_config(None)
    assert cfg.schedule.events == []
