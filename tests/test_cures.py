from mmud.automation.cures import CureDecider, CURE_TIMEOUT_S
from mmud.automation.decision import PRIO_CURE
from mmud.config.schema import HealthConfig
from mmud.state.conditions import Condition
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType


def _decider(**cfg):
    return CureDecider(HealthConfig(**cfg), now=lambda: 100.0)


def test_cures_blindness():
    gs = GameState()
    gs.conditions.add(Condition.BLIND)
    d = _decider(blind_cmd="cast purify vision")
    assert d.decide(gs) == "cast purify vision"


def test_cure_starts_casting_task_with_timeout():
    gs = GameState()
    gs.conditions.add(Condition.POISONED)
    _decider(poison_cmd="cast neutralize").decide(gs)
    assert gs.task.type is TaskType.CASTING
    assert gs.task.priority == PRIO_CURE
    assert gs.task.deadline == 100.0 + CURE_TIMEOUT_S
    assert gs.task.payload == {"condition": "POISONED"}


def test_no_cure_configured_returns_none():
    gs = GameState()
    gs.conditions.add(Condition.BLIND)
    assert _decider().decide(gs) is None
    assert not gs.task.is_active


def test_no_conditions_returns_none():
    gs = GameState()
    assert _decider(blind_cmd="x", poison_cmd="y").decide(gs) is None


def test_blind_cured_before_poison():
    # Cure order: blind first (can't fight blind), then poison/disease/held
    gs = GameState()
    gs.conditions.add(Condition.POISONED)
    gs.conditions.add(Condition.BLIND)
    d = _decider(blind_cmd="cure-blind", poison_cmd="cure-poison")
    assert d.decide(gs) == "cure-blind"
