from mmud.combat.backstab import BackstabEngine
from mmud.config.schema import CombatConfig, StealthConfig
from mmud.state.game_state import GameState, MonsterSighting
from mmud.state.tasks import TaskType


def _engine(**combat):
    return BackstabEngine(
        CombatConfig(backstab=True, **combat),
        StealthConfig(hide_cmd="hide", sneak_cmd="sneak"),
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
    assert eng.decide(gs) == "backstab orc"
    eng.on_line("You plant your weapon in the orc's back!")
    assert eng.decide(gs) is None            # done; melee takes over


def test_disabled_returns_none():
    eng = BackstabEngine(CombatConfig(backstab=False), StealthConfig())
    assert eng.decide(_state_with_target()) is None


def test_in_combat_returns_none():
    eng = _engine()
    gs = _state_with_target()
    gs.set_combat(True)
    assert eng.decide(gs) is None


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
    assert eng.decide(gs) == "backstab orc"
    eng.on_line("Your backstab attempt fails!")
    assert eng.decide(gs) == "flee"
    assert gs.task.type is TaskType.RUNNING


def test_resets_on_room_change():
    eng = _engine()
    gs = _state_with_target()
    eng.decide(gs)
    eng.reset()
    assert eng.decide(gs) == "hide"          # starts over
