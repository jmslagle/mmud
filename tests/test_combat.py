from mmud.state.game_state import GameState
from mmud.combat.combat import CombatEngine
from mmud.config.schema import CombatConfig
from mmud.state.game_state import MonsterSighting


def test_attacks_when_in_combat():
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(50, 100)
    ce = CombatEngine()
    cmd = ce.decide(gs)
    assert cmd == "kill"


def test_flees_when_critically_low_hp():
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(10, 100)   # 10% HP
    gs.set_mana(50, 100)
    ce = CombatEngine(CombatConfig(flee_threshold=0.15))
    cmd = ce.decide(gs)
    assert cmd == "flee"


def test_no_command_when_not_in_combat_and_healthy():
    gs = GameState()
    gs.set_combat(False)
    gs.set_hp(100, 100)
    ce = CombatEngine()
    cmd = ce.decide(gs)
    assert cmd is None


def test_rests_when_not_in_combat_and_low_hp():
    gs = GameState()
    gs.set_combat(False)
    gs.set_hp(30, 100)
    ce = CombatEngine(CombatConfig(rest_threshold=0.5))
    cmd = ce.decide(gs)
    assert cmd == "rest"


def test_uses_config_attack_cmd():
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(50, 100)
    gs.monsters_present = [MonsterSighting(name="orc warrior")]
    ce = CombatEngine(CombatConfig(attack_cmd="kill"))
    assert ce.decide(gs) == "kill orc warrior"

def test_attack_without_monster_name():
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(50, 100)
    gs.monsters_present = []
    ce = CombatEngine(CombatConfig(attack_cmd="kill"))
    assert ce.decide(gs) == "kill"

def test_respects_mana_attack_pct():
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(10, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    ce = CombatEngine(CombatConfig(mana_attack_pct=0.20))
    assert ce.decide(gs) is None  # 10% mana < 20% threshold

def test_config_flee_threshold():
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(5, 100)
    gs.set_mana(50, 100)
    ce = CombatEngine(CombatConfig(flee_threshold=0.10))
    assert ce.decide(gs) == "flee"

def test_no_config_uses_defaults():
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(50, 100)
    ce = CombatEngine()
    cmd = ce.decide(gs)
    assert cmd == "kill"  # default attack_cmd


def test_sneak_before_first_attack():
    from mmud.config.schema import CombatConfig
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(80, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    ce = CombatEngine(CombatConfig(), sneak_cmd="sneak")
    assert ce.decide(gs) == "sneak"         # first: sneak
    assert ce.decide(gs) == "kill orc"      # second: attack


def test_must_sneak_holds_attack_until_sneak_succeeds():
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(80, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    ce = CombatEngine(CombatConfig(), sneak_cmd="sneak", must_sneak=True)
    assert ce.decide(gs) == "sneak"     # issue the sneak
    assert ce.decide(gs) is None        # hold: not confirmed yet
    ce.on_line("You move silently into the shadows.")
    assert ce.decide(gs) == "kill orc"  # confirmed: attack


def test_must_sneak_issues_sneak_without_auto_sneak():
    # Regression: with sneak_cmd supplied + must_sneak, the FIRST decide must
    # issue the sneak (not deadlock on None waiting for a confirm that never
    # comes). Proves the engine is fine; the deadlock was bot wiring passing "".
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(80, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    ce = CombatEngine(CombatConfig(), sneak_cmd="sneak", must_sneak=True)
    assert ce.decide(gs) == "sneak"     # first: issues the sneak, no deadlock
    assert ce.decide(gs) is None        # then holds until confirmed
    ce.on_line("You move silently into the shadows.")
    assert ce.decide(gs) == "kill orc"  # confirmed: attack


def test_must_sneak_retries_after_failure():
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(80, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    ce = CombatEngine(CombatConfig(), sneak_cmd="sneak", must_sneak=True)
    assert ce.decide(gs) == "sneak"     # issue the sneak
    ce.on_line("You fail to sneak and make a noise.")
    assert ce.decide(gs) == "sneak"     # retry the sneak
    assert ce.decide(gs) is None        # still holding
    ce.on_line("You begin to sneak around.")
    assert ce.decide(gs) == "kill orc"  # confirmed: attack


def _sightings(gs, *names):
    for n in names:
        gs.monsters_present.append(MonsterSighting(name=n))


def test_priority_target_first():
    cfg = CombatConfig(monster_priority=["orc chieftain"])
    gs = GameState(); gs.set_hp(100, 100); gs.set_combat(True)
    _sightings(gs, "giant rat", "orc chieftain")
    assert CombatEngine(cfg).decide(gs) == "kill orc chieftain"


def test_attack_order_last():
    cfg = CombatConfig(attack_order="last")
    gs = GameState(); gs.set_hp(100, 100); gs.set_combat(True)
    _sightings(gs, "rat", "orc")
    assert CombatEngine(cfg).decide(gs) == "kill orc"


def test_polite_attacks_blocks_when_player_present():
    cfg = CombatConfig(polite_attacks=True)
    gs = GameState(); gs.set_hp(100, 100); gs.set_combat(True)
    _sightings(gs, "rat")
    gs.players_present = ["Krang"]
    assert CombatEngine(cfg).decide(gs) is None


def test_polite_attacks_allows_when_alone():
    cfg = CombatConfig(polite_attacks=True)
    gs = GameState(); gs.set_hp(100, 100); gs.set_combat(True)
    _sightings(gs, "rat")
    assert CombatEngine(cfg).decide(gs) == "kill rat"
