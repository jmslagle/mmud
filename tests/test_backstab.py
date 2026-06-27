from mmud.combat.backstab import BackstabEngine
from mmud.config.schema import CombatConfig, StealthConfig
from mmud.state.game_state import GameState, MonsterSighting
from mmud.state.tasks import TaskType


def _engine(**combat):
    return BackstabEngine(
        CombatConfig(backstab=True, **combat),
        StealthConfig(),
    )


def _state_with_target():
    gs = GameState()
    gs.set_hp(100, 100)
    gs.monsters_present.append(MonsterSighting(name="orc"))
    return gs


def test_full_sequence():
    eng = _engine()
    gs = _state_with_target()
    assert eng.decide(gs) == "hide"
    assert eng.decide(gs) is None            # waiting for hide result
    eng.on_line("You slip into the shadows.")
    assert eng.decide(gs) == "sneak"
    eng.on_line("You move silently.")
    assert eng.decide(gs) == "bs orc"
    eng.on_line("You plant your weapon in the orc's back!")
    assert eng.decide(gs) is None            # done; melee takes over


def test_backstab_skips_good_npc():
    # kill-type 2 (guard/shopkeeper) -> never opened on
    eng = _engine()
    gs = GameState(); gs.set_hp(100, 100)
    gs.monsters_present.append(MonsterSighting(name="happy guardsman", kill_type=2))
    assert eng.decide(gs) is None


def test_backstab_targets_hostile_over_npc():
    eng = _engine()
    gs = GameState(); gs.set_hp(100, 100)
    gs.monsters_present.append(MonsterSighting(name="happy guardsman", kill_type=2))
    gs.monsters_present.append(MonsterSighting(name="kobold thief", kill_type=4))
    assert eng.decide(gs) == "hide"   # there IS an attackable target -> proceed
    eng.on_line("You slip into the shadows.")
    eng.decide(gs)
    eng.on_line("You move silently.")
    assert eng.decide(gs) == "bs kobold thief"


def test_disabled_returns_none():
    eng = BackstabEngine(CombatConfig(backstab=False), StealthConfig())
    assert eng.decide(_state_with_target()) is None


def test_in_combat_returns_none():
    eng = _engine()
    gs = _state_with_target()
    gs.set_combat(True)
    assert eng.decide(gs) is None


def test_no_stale_stealth_once_combat_starts():
    # Live bug: backstab opened (hide), got stuck mid-sequence while the fight raged
    # (the spell engine preempted it for ~15s), then emitted a STALE "sneak" on a later
    # *Combat Off* flicker — "You may not sneak right now!" mid-combat. Once we've been
    # in combat this encounter, backstab must stay silent until the encounter ends.
    eng = _engine()
    gs = _state_with_target()
    gs.set_combat(False)
    assert eng.decide(gs) == "hide"          # opening (IDLE -> HIDING)
    eng.on_line("You slip into the shadows.")  # -> HIDDEN (mid-sequence)
    gs.set_combat(True)                        # the fight started
    assert eng.decide(gs) is None              # latch engaged
    gs.set_combat(False)                       # *Combat Off* flicker, orc still here
    assert eng.decide(gs) is None              # HIDDEN stage but latched -> NO stale sneak
    assert eng.decide(gs) is None
    # encounter ends (monster dead / room clears) -> latch clears, re-armed next fight
    gs.monsters_present.clear()
    assert eng.decide(gs) is None            # empty room -> reset (clears the latch)
    gs.monsters_present.append(MonsterSighting(name="rat"))
    assert eng.decide(gs) == "hide"


def test_hide_failure_not_a_false_positive_success():
    # "You don't think you are hidden." must read as a FAIL, not a success (it contains
    # the substring "you are hidden").
    eng = _engine()
    gs = _state_with_target()
    assert eng.decide(gs) == "hide"
    eng.on_line("Attempting to hide... You don't think you are hidden.")
    assert eng.decide(gs) != "sneak"         # not wrongly "hidden" -> no sneak


def test_hide_failure_retries_then_gives_up():
    eng = _engine()
    gs = _state_with_target()
    assert eng.decide(gs) == "hide"
    eng.on_line("You fail to hide!")
    assert eng.decide(gs) == "hide"          # one retry
    eng.on_line("You fail to hide!")
    assert eng.decide(gs) is None            # give up -> melee combat proceeds


def test_bs_failure_runs_if_configured():
    eng = _engine(run_if_bs_fails=True)
    gs = _state_with_target()
    eng.decide(gs); eng.on_line("You slip into the shadows.")
    eng.decide(gs); eng.on_line("You move silently.")
    assert eng.decide(gs) == "bs orc"
    eng.on_line("Your backstab attempt fails!")
    assert eng.decide(gs) == "flee"
    assert gs.task.type is TaskType.RUNNING


def test_resets_on_room_change():
    eng = _engine()
    gs = _state_with_target()
    eng.decide(gs)
    eng.reset()
    assert eng.decide(gs) == "hide"          # starts over
