from mmud.state.game_state import GameState
from mmud.combat.combat import CombatEngine
from mmud.config.schema import CombatConfig
from mmud.state.game_state import MonsterSighting


def test_attacks_when_in_combat():
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(50, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    ce = CombatEngine()
    cmd = ce.decide(gs)
    assert cmd == "kill orc"


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

def test_engages_target_once_not_every_round():
    # Re-sending the melee attack restarts the round and wastes swings; engage
    # once per target, re-engage only when the target changes.
    gs = GameState()
    gs.set_combat(True); gs.set_hp(80, 100); gs.set_mana(80, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    ce = CombatEngine(CombatConfig(attack_cmd="kill"))
    assert ce.decide(gs) == "kill orc"
    assert ce.decide(gs) is None          # same target, already engaged
    assert ce.decide(gs) is None
    # A new monster -> re-engage.
    gs.monsters_present = [MonsterSighting(name="goblin")]
    assert ce.decide(gs) == "kill goblin"
    # Encounter ends then a fresh orc appears -> engage again.
    gs.set_combat(False); gs.monsters_present = []
    assert ce.decide(gs) is None
    gs.set_combat(True); gs.monsters_present = [MonsterSighting(name="orc")]
    assert ce.decide(gs) == "kill orc"


def test_no_attack_without_target():
    # Regression: in_combat can linger after a kill before *Combat Off*; with no
    # monster to target the bot must NOT emit a bare "kill" (server reads it as
    # chat -> `You say "kill"`).
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(50, 100)
    gs.monsters_present = []
    ce = CombatEngine(CombatConfig(attack_cmd="kill"))
    assert ce.decide(gs) is None

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
    gs.monsters_present = [MonsterSighting(name="orc")]
    ce = CombatEngine()
    cmd = ce.decide(gs)
    assert cmd == "kill orc"  # default attack_cmd


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


def test_initiates_attack_when_monster_present_not_yet_in_combat():
    from mmud.combat.combat import CombatEngine
    from mmud.config.schema import CombatConfig
    from mmud.state.game_state import GameState, MonsterSighting
    gs = GameState(); gs.set_hp(100, 100); gs.set_combat(False)
    # kill_type 4 = hostile -> initiated on sight (MegaMud attack gate)
    gs.monsters_present = [MonsterSighting(name="fat giant rat", kill_type=4)]
    ce = CombatEngine(CombatConfig(attack_cmd="kill"))
    assert ce.decide(gs) == "kill fat giant rat"   # initiate, even out of combat


# ---- kill-type targeting (MegaMud: attack tier 4; tier 3 only if AttackNeutral;
#      never tier 2/5). Mirrors combat_flee_or_hide_decide's `tier != 4` gate. ----

def _gs_room(*sightings):
    from mmud.state.game_state import GameState
    gs = GameState(); gs.set_hp(100, 100); gs.set_mana(100, 100)
    gs.set_combat(False)
    gs.monsters_present = list(sightings)
    return gs


def test_never_initiates_on_good_npc_kill_type_2():
    # shopkeeper / healer / woodelf guard are kill-type 2 -> never auto-attacked
    gs = _gs_room(MonsterSighting(name="shopkeeper", kill_type=2))
    assert CombatEngine(CombatConfig()).decide(gs) is None


def test_does_not_initiate_on_neutral_when_attack_neutral_off():
    # giant rat / guardsman are kill-type 3; default attack_neutral=False -> skip
    gs = _gs_room(MonsterSighting(name="guardsman", kill_type=3))
    assert CombatEngine(CombatConfig()).decide(gs) is None


def test_initiates_on_neutral_when_attack_neutral_on():
    gs = _gs_room(MonsterSighting(name="giant rat", kill_type=3))
    cfg = CombatConfig(attack_neutral=True)
    assert CombatEngine(cfg).decide(gs) == "kill giant rat"


def test_initiates_on_hostile_kill_type_4():
    gs = _gs_room(MonsterSighting(name="kobold thief", kill_type=4))
    assert CombatEngine(CombatConfig()).decide(gs) == "kill kobold thief"


def test_targets_hostile_and_skips_npc_in_same_room():
    gs = _gs_room(MonsterSighting(name="shopkeeper", kill_type=2),
                  MonsterSighting(name="kobold thief", kill_type=4))
    assert CombatEngine(CombatConfig()).decide(gs) == "kill kobold thief"


def test_initiates_on_unknown_monster_not_in_db():
    # kill_type 0 = not catalogued -> attackable (DB protects known NPCs only)
    gs = _gs_room(MonsterSighting(name="weird beast", kill_type=0))
    assert CombatEngine(CombatConfig()).decide(gs) == "kill weird beast"


def test_fights_back_when_already_in_combat_regardless_of_kill_type():
    # Once engaged (a guard attacked us), fight back even though it's not a
    # type we would have initiated on.
    gs = _gs_room(MonsterSighting(name="guardsman", kill_type=3))
    gs.set_combat(True)
    assert CombatEngine(CombatConfig()).decide(gs) == "kill guardsman"
