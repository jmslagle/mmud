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


def test_flees_by_moving_out_an_exit_when_low_hp():
    # MegaMud never sends the literal "flee" — at low HP it WALKS OUT an exit (one room
    # per turn), avoiding the reverse of the way it came, then rests. This replaces the
    # old "flee" spam.
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(10, 100)   # 10% HP
    gs.set_mana(50, 100)
    gs.last_exits = ["n", "s"]
    gs.move_history.append("n")          # came in via 'n' -> avoid 's' (its reverse)
    ce = CombatEngine(CombatConfig(flee_threshold=0.15))
    assert ce.decide(gs) == "n"          # moves out, NOT the literal "flee"


def test_flee_falls_back_to_flee_command_with_no_known_exits():
    # Genuinely trapped (no exits parsed) -> the MajorMUD "flee" verb is the last resort.
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(10, 100)
    gs.set_mana(50, 100)
    ce = CombatEngine(CombatConfig(flee_threshold=0.15))
    assert ce.decide(gs) == "flee"


def test_flee_run_backwards_retraces_move_history():
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(10, 100)
    gs.set_mana(50, 100)
    gs.last_exits = ["n", "s", "e", "w"]
    gs.move_history.extend(["n", "e"])   # came in n then e
    ce = CombatEngine(CombatConfig(flee_threshold=0.15, run_backwards=True, flee_rooms=2))
    assert ce.decide(gs) == "w"          # retrace: reverse of last move 'e'
    assert ce.decide(gs) == "s"          # then reverse of 'n'


def test_emergency_decider_fires_once_below_threshold():
    # Critical-HP escape lives in its own always-active decider (so "run" mode still
    # bails when dying). Fires the configurable command ONCE, re-arms after recovery.
    from mmud.combat.combat import EmergencyDecider
    gs = GameState()
    gs.set_hp(3, 100)                   # 3% < 5%
    d = EmergencyDecider(CombatConfig(emergency_threshold=0.05, emergency_cmd="sys go sil"))
    assert d.decide(gs) == "sys go sil"
    assert d.decide(gs) is None         # debounced — don't spam the recall
    gs.set_hp(80, 100)                  # recovered above threshold -> re-arm
    assert d.decide(gs) is None
    gs.set_hp(2, 100)                   # critical again
    assert d.decide(gs) == "sys go sil"


def test_emergency_decider_fires_even_in_run_mode_and_when_hp_negative():
    from mmud.combat.combat import EmergencyDecider
    gs = GameState()
    gs.set_hp(-5, 100)                  # HP went negative
    gs.combat_enabled = False           # "run" mode (combat toggled off)
    d = EmergencyDecider(CombatConfig(emergency_threshold=0.05, emergency_cmd="recall"))
    assert d.decide(gs) == "recall"     # still bails


def test_emergency_decider_off_when_unconfigured():
    from mmud.combat.combat import EmergencyDecider
    gs = GameState()
    gs.set_hp(1, 100)
    assert EmergencyDecider(CombatConfig()).decide(gs) is None   # no emergency_cmd


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


def test_rests_when_mana_low_and_holds_until_recovered():
    # Warlock-style: out of combat with low mana -> rest, and HOLD the loop (a
    # RESTING task) until mana recovers, instead of resting one tick and walking off.
    from mmud.state.tasks import TaskType
    gs = GameState()
    gs.set_combat(False)
    gs.set_hp(100, 100)
    gs.set_mana(10, 50)                 # 20% mana
    ce = CombatEngine(CombatConfig(rest_mana_pct=0.30))
    assert ce.decide(gs) == "rest"
    assert gs.task.type is TaskType.RESTING   # holds (blocks travel)
    ce.on_line("[HP=100/MA=10]: (Resting)")
    assert ce.decide(gs) is None              # resting -> don't re-spam
    gs.set_mana(49, 50)                        # recovered (98%)
    assert ce.decide(gs) is None              # done
    assert not gs.task.is_active               # loop resumes


def test_rest_not_respammed_before_resting_confirmation():
    # Live bug: we flooded the server with `rest` (30+ in 0.5s -> "slow down") because
    # we re-issued it on every line in the window before the "(Resting)" prompt. Send
    # it ONCE per prompt cycle.
    gs = GameState()
    gs.set_combat(False)
    gs.set_hp(30, 100)
    ce = CombatEngine(CombatConfig(rest_threshold=0.5))
    assert ce.decide(gs) == "rest"           # sent once
    ce.on_line("You are now resting.")       # not a [HP=] prompt -> no confirmation yet
    assert ce.decide(gs) is None             # must NOT re-send before the prompt
    ce.on_line("You fire a magic missile!")  # other chatter
    assert ce.decide(gs) is None             # still no spam
    ce.on_line("[HP=31/MA=10]: (Resting)")   # confirmed resting
    assert ce.decide(gs) is None             # resting -> stays quiet


def test_resumes_resting_after_a_cast_until_full():
    # Sitting idle resting, a bless cast stands us up. We must RESUME resting until
    # full (like MegaMud, which rests through buff casts) — not stop just because
    # mana climbed back over the *start* threshold. The RESTING task gets aborted by
    # the (higher-priority) cast, so recovery must be tracked in our own flag.
    gs = GameState()
    gs.set_combat(False)
    gs.set_hp(100, 100)
    gs.set_mana(10, 50)                        # 20% mana < 30% start
    ce = CombatEngine(CombatConfig(rest_mana_pct=0.30))
    assert ce.decide(gs) == "rest"
    ce.on_line("[HP=100/MA=10]: (Resting)")    # resting
    assert ce.decide(gs) is None               # holding
    gs.set_mana(20, 50)                         # recovered to 40% (over start, under full)
    gs.abort_task()                             # the cast preempted -> RESTING task gone
    ce.on_line("You cast blur on Raist!")       # the cast itself
    ce.on_line("[HP=100/MA=18]:")               # stood up -> no "(Resting)" in prompt
    assert ce.decide(gs) == "rest"             # RESUME resting (still recovering to full)


def test_no_mana_rest_by_default():
    gs = GameState()
    gs.set_combat(False)
    gs.set_hp(100, 100)
    gs.set_mana(2, 50)                  # very low mana, but mana-rest disabled
    ce = CombatEngine(CombatConfig())  # rest_mana_pct defaults to 0
    assert ce.decide(gs) is None
    assert not gs.task.is_active


def test_monster_preempts_mana_rest():
    gs = GameState()
    gs.set_combat(False)
    gs.set_hp(100, 100)
    gs.set_mana(2, 50)
    gs.monsters_present = [MonsterSighting(name="bat", kill_type=4)]
    ce = CombatEngine(CombatConfig(rest_mana_pct=0.30, attack_cmd="kill"))
    assert ce.decide(gs) == "kill bat"   # fights rather than resting


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

def test_melees_when_mana_below_attack_pct():
    # MegaMud: ManaAttack% is a floor — below it, MELEE (don't wait). The spell
    # engine declines to cast at low mana; the combat engine then swings.
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(10, 100)
    gs.monsters_present = [MonsterSighting(name="orc", kill_type=4)]
    ce = CombatEngine(CombatConfig(mana_attack_pct=0.20))
    assert ce.decide(gs) == "kill orc"   # 10% < 20% -> melee, not idle

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
    # The auto-sneak is an OPENER: it fires before engaging (not in combat), then attacks.
    from mmud.config.schema import CombatConfig
    gs = GameState()
    gs.set_combat(False)
    gs.set_hp(80, 100)
    gs.set_mana(80, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    ce = CombatEngine(CombatConfig(), sneak_cmd="sneak")
    assert ce.decide(gs) == "sneak"         # first: sneak (opener)
    assert ce.decide(gs) == "kill orc"      # second: attack


def test_no_sneak_once_in_combat_spell_to_melee():
    # The bug: at the cast->melee switch we're already in combat, so trying to sneak just
    # spams "You may not sneak right now!". The auto-sneak must NOT fire once in combat.
    from mmud.config.schema import CombatConfig
    gs = GameState()
    gs.set_combat(True)                     # spell already engaged
    gs.set_hp(80, 100)
    gs.set_mana(80, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    ce = CombatEngine(CombatConfig(), sneak_cmd="sneak")
    assert ce.decide(gs) == "kill orc"      # melee, NOT sneak
    # and a between-round *Combat Off* flicker (still the same fight) must not sneak either
    gs.set_combat(False)
    assert ce.decide(gs) is None            # already engaged this target -> no sneak


def test_must_sneak_holds_attack_until_sneak_succeeds():
    gs = GameState()
    gs.set_combat(False)
    gs.set_hp(80, 100)
    gs.set_mana(80, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    ce = CombatEngine(CombatConfig(), sneak_cmd="sneak", must_sneak=True)
    assert ce.decide(gs) == "sneak"     # issue the sneak (opener)
    assert ce.decide(gs) is None        # hold: not confirmed yet
    ce.on_line("You move silently into the shadows.")
    assert ce.decide(gs) == "kill orc"  # confirmed: attack


def test_must_sneak_issues_sneak_without_auto_sneak():
    # Regression: with sneak_cmd supplied + must_sneak, the FIRST decide must
    # issue the sneak (not deadlock on None waiting for a confirm that never
    # comes). Proves the engine is fine; the deadlock was bot wiring passing "".
    gs = GameState()
    gs.set_combat(False)
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
    gs.set_combat(False)
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


def test_activity_reason_reports_waiting_for_mana():
    from mmud.combat.combat import activity_reason
    gs = GameState(); gs.set_combat(True); gs.set_hp(80, 100); gs.set_mana(5, 100)
    # in combat, mana below the attack threshold, engine returned nothing -> waiting
    assert activity_reason(gs, None, mana_attack_pct=0.20, rest_threshold=0.40) \
        == "waiting for mana"
    # mana fine -> no wait reason
    gs.set_mana(80, 100)
    assert activity_reason(gs, None, 0.20, 0.40) == ""
    # actually acting (cmd present) -> no wait reason
    gs.set_mana(5, 100)
    assert activity_reason(gs, "mmis orc", 0.20, 0.40) == ""


def test_activity_reason_reports_resting():
    from mmud.combat.combat import activity_reason
    gs = GameState(); gs.set_combat(False); gs.set_hp(20, 100); gs.set_mana(50, 100)
    assert activity_reason(gs, None, 0.20, 0.40) == "resting"


def test_rests_once_not_respammed_while_resting():
    # HP 29/82 = 35% < 40% rest_threshold. Rest ONCE; while the prompt shows
    # "(Resting)" don't re-send rest every tick.
    gs = GameState(); gs.set_combat(False); gs.set_hp(29, 82)
    ce = CombatEngine(CombatConfig(rest_threshold=0.40))
    assert ce.decide(gs) == "rest"
    ce.on_line("[HP=29/MA=30]: (Resting) ")
    assert ce.decide(gs) is None          # already resting -> no respam
    assert ce.decide(gs) is None
    ce.on_line("[HP=29/MA=30]:")          # stood / interrupted -> resting cleared
    assert ce.decide(gs) == "rest"        # rest again (still low)


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
