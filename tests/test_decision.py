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


def test_prio_backstab_sits_just_above_combat():
    from mmud.automation.decision import PRIO_BACKSTAB, PRIO_COMBAT
    assert PRIO_BACKSTAB == PRIO_COMBAT - 1


def test_equal_priority_decider_does_not_preempt_its_own_active_task():
    # A slot at the SAME priority as the active task is pinned (priority >= task
    # priority), so it must not run and must not abort the task — even though it
    # would otherwise return a command.
    engine = DecisionEngine()
    same = StubDecider("would-fire")
    engine.register("same", same, priority=PRIO_COMBAT)
    gs = GameState()
    gs.begin_task(TaskType.RESTING, priority=PRIO_COMBAT)
    assert engine.next_command(gs) is None
    assert same.calls == 0
    assert gs.task.is_active
    assert gs.task.type is TaskType.RESTING


def test_self_starting_task_command_is_not_aborted_by_its_own_slot():
    # A decider that begins its OWN task at its own priority and returns a command
    # in the same call must keep that task (engine only aborts strictly-lower tasks).
    engine = DecisionEngine()
    engine.register("self", TaskBeginningDecider("cast bless", PRIO_SPELLS), PRIO_SPELLS)
    gs = GameState()
    assert engine.next_command(gs) == "cast bless"
    assert gs.task.is_active
    assert gs.task.type is TaskType.CASTING
    assert gs.task.priority == PRIO_SPELLS


def test_lower_number_slot_preempts_and_aborts_higher_number_task():
    # PRIO_CURE (10) < PRIO_TRAVEL (110): the cure slot preempts a travel task.
    engine = DecisionEngine()
    cure = StubDecider("cure cmd")
    engine.register("cure", cure, priority=PRIO_CURE)
    gs = GameState()
    gs.begin_task(TaskType.RUNNING, priority=PRIO_TRAVEL)
    assert engine.next_command(gs) == "cure cmd"
    assert cure.calls == 1
    assert not gs.task.is_active  # the higher-number task was aborted


def test_pinned_task_blocks_lower_priority_but_higher_priority_still_runs():
    # Task owns PRIO_COMBAT. A lower-priority (higher-number) slot below it is
    # pinned/skipped, but a higher-priority (lower-number) slot above it preempts.
    engine = DecisionEngine()
    above = StubDecider("above-cmd")   # PRIO_CURE  (10) — runs/preempts
    below = StubDecider("below-cmd")   # PRIO_TRAVEL(110) — pinned, never reached
    engine.register("above", above, priority=PRIO_CURE)
    engine.register("below", below, priority=PRIO_TRAVEL)
    gs = GameState()
    gs.begin_task(TaskType.RESTING, priority=PRIO_COMBAT)
    assert engine.next_command(gs) == "above-cmd"
    assert above.calls == 1
    assert below.calls == 0
    assert not gs.task.is_active

    # Now with no higher slot: the same pinned task blocks the lower slot entirely.
    engine2 = DecisionEngine()
    below2 = StubDecider("below-cmd")
    engine2.register("below", below2, priority=PRIO_TRAVEL)
    gs2 = GameState()
    gs2.begin_task(TaskType.RESTING, priority=PRIO_COMBAT)
    assert engine2.next_command(gs2) is None
    assert below2.calls == 0
    assert gs2.task.is_active
