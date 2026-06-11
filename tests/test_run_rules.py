from mmud.automation.run_rules import RunDecider, RUN_TIMEOUT_S
from mmud.automation.decision import PRIO_FLEE
from mmud.config.schema import CombatConfig, NavigationConfig
from mmud.state.game_state import GameState, MonsterSighting
from mmud.state.tasks import TaskType


def _state(*sightings):
    gs = GameState()
    gs.monsters_present.extend(sightings)
    return gs


def _decider(**combat):
    return RunDecider(CombatConfig(**combat), NavigationConfig(flee_rooms=2),
                      now=lambda: 50.0)


def test_too_many_monsters_triggers_run():
    gs = _state(MonsterSighting(name="orc", count=3))
    d = _decider(max_monsters=2)
    assert d.decide(gs) == "flee"
    assert gs.task.type is TaskType.RUNNING
    assert gs.task.priority == PRIO_FLEE
    assert gs.task.deadline == 50.0 + RUN_TIMEOUT_S
    assert gs.dequeue() == "flee"        # flee_rooms=2 -> 1 returned + 1 queued


def test_too_much_exp_triggers_run():
    gs = _state(MonsterSighting(name="dragon", count=1, exp_each=99999))
    assert _decider(max_monster_exp=5000).decide(gs) == "flee"


def test_under_limits_no_run():
    gs = _state(MonsterSighting(name="rat", count=1, exp_each=20))
    assert _decider(max_monsters=2, max_monster_exp=5000).decide(gs) is None
    assert not gs.task.is_active


def test_no_limits_configured_never_runs():
    gs = _state(MonsterSighting(name="orc", count=99))
    assert _decider().decide(gs) is None


def test_run_backwards_uses_move_history():
    gs = _state(MonsterSighting(name="orc", count=3))
    gs.move_history.extend(["n", "e", "u"])
    d = _decider(max_monsters=2, run_backwards=True)
    assert d.decide(gs) == "d"           # inverse of last move first
    assert gs.dequeue() == "w"
    assert gs.task.is_active


def test_no_retrigger_while_running():
    gs = _state(MonsterSighting(name="orc", count=3))
    d = _decider(max_monsters=2)
    d.decide(gs)
    assert gs.task.type is TaskType.RUNNING
