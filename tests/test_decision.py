from mmud.automation.decision import (
    DecisionEngine, QueueDecider,
    PRIO_QUEUE, PRIO_CURE, PRIO_SPELLS, PRIO_COMBAT, PRIO_TRAVEL,
)
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType


class StubDecider:
    def __init__(self, cmd):
        self.cmd = cmd
        self.calls = 0

    def decide(self, state):
        self.calls += 1
        return self.cmd


def test_first_non_none_wins_in_priority_order():
    engine = DecisionEngine()
    low = StubDecider("low")
    high = StubDecider("high")
    engine.register("low", low, priority=PRIO_TRAVEL)
    engine.register("high", high, priority=PRIO_CURE)  # registered second, tried first
    assert engine.next_command(GameState()) == "high"
    assert low.calls == 0


def test_none_falls_through_to_next_slot():
    engine = DecisionEngine()
    engine.register("a", StubDecider(None), priority=PRIO_CURE)
    engine.register("b", StubDecider("b-cmd"), priority=PRIO_COMBAT)
    assert engine.next_command(GameState()) == "b-cmd"


def test_active_task_pins_slots_at_or_below_its_priority():
    engine = DecisionEngine()
    pinned = StubDecider("pinned")
    engine.register("pinned", pinned, priority=PRIO_COMBAT)
    gs = GameState()
    gs.begin_task(TaskType.RESTING, priority=PRIO_COMBAT)
    assert engine.next_command(gs) is None
    assert pinned.calls == 0
    assert gs.task.is_active  # nothing preempted it


def test_higher_priority_decider_preempts_and_aborts_task():
    engine = DecisionEngine()
    engine.register("cure", StubDecider("cast heal"), priority=PRIO_CURE)
    gs = GameState()
    gs.begin_task(TaskType.RESTING, priority=PRIO_COMBAT)
    assert engine.next_command(gs) == "cast heal"
    assert not gs.task.is_active  # preemption aborted the task


def test_empty_engine_returns_none():
    assert DecisionEngine().next_command(GameState()) is None


def test_queue_decider_drains_state_queue():
    gs = GameState()
    gs.enqueue("n")
    gs.enqueue("e")
    qd = QueueDecider()
    assert qd.decide(gs) == "n"
    assert qd.decide(gs) == "e"
    assert qd.decide(gs) is None


def test_priority_constants_are_strictly_ordered():
    from mmud.automation import decision
    names = ["PRIO_QUEUE", "PRIO_CURE", "PRIO_FLEE", "PRIO_SPELLS", "PRIO_COMBAT",
             "PRIO_REST", "PRIO_REFRESH", "PRIO_BLESS", "PRIO_EQUIP", "PRIO_ITEMS",
             "PRIO_COMMERCE", "PRIO_PARTY", "PRIO_TRAVEL", "PRIO_SEARCH"]
    values = [getattr(decision, n) for n in names]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


class TaskBeginningDecider:
    """Begins a task at its own priority AND returns a command, like CureDecider."""
    def __init__(self, cmd, priority):
        self.cmd = cmd
        self.priority = priority

    def decide(self, state):
        state.begin_task(TaskType.CASTING, priority=self.priority)
        return self.cmd


def test_decider_setting_own_task_is_not_self_aborted():
    # Regression: a decider that begins a task at its own priority and returns a
    # command must keep that task active (engine only aborts strictly-lower tasks).
    engine = DecisionEngine()
    engine.register("cure", TaskBeginningDecider("cast heal", PRIO_CURE), PRIO_CURE)
    gs = GameState()
    assert engine.next_command(gs) == "cast heal"
    assert gs.task.is_active
    assert gs.task.priority == PRIO_CURE
