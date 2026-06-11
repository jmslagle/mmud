# Phase 1: Decision Engine Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `MudBot._next_command()`'s flat queue→spells→combat fallthrough with the original MegaMud "DoSomething" architecture: a priority-ordered chain of decider slots plus a task state machine with timeouts.

**Architecture:** A `DecisionEngine` holds `(priority, name, decider)` slots and returns the first non-None command per incoming line. A `TaskState` on `GameState` represents a multi-step activity in progress (Resting, Casting, …); while a task is active, slots at or below the task's priority are skipped, and any higher-priority decider that acts preempts (aborts) the task. The existing `CombatEngine` and `SpellEngine` already match the `decide(state) -> str | None` protocol, so they register unchanged — **Phase 1 changes no observable bot behavior**; it builds the scaffolding Phases 2–11 plug into.

**Tech Stack:** Python 3.11+, stdlib only (enum, dataclasses, typing.Protocol). Tests: pytest + pytest-asyncio (already in use).

**Behavior invariant:** All 139 existing tests must pass unmodified.

---

## File Map

```
src/mmud/
  state/tasks.py            NEW — TaskType enum + TaskState dataclass
  state/game_state.py       MODIFY — task field + begin/complete/abort_task
  automation/decision.py    NEW — Decider protocol, priorities, QueueDecider, DecisionEngine
  events.py                 MODIFY — add TaskChanged
  bot.py                    MODIFY — build engine, delegate _next_command, ticker timeout check
tests/
  test_tasks.py             NEW
  test_decision.py          NEW
  test_game_state.py        MODIFY — task lifecycle tests
  test_events.py            MODIFY — TaskChanged test
  test_bot.py               MODIFY — transcript harness smoke test + timeout test
  conftest.py               MODIFY — FakeConnection + make_transcript_bot fixture
```

---

### Task 1: TaskType and TaskState

**Files:**
- Create: `src/mmud/state/tasks.py`
- Test: `tests/test_tasks.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tasks.py
from mmud.state.tasks import TaskType, TaskState


def test_default_task_is_idle():
    t = TaskState()
    assert t.type is TaskType.IDLE
    assert not t.is_active


def test_active_task():
    t = TaskState(type=TaskType.RESTING, priority=50)
    assert t.is_active


def test_expired_with_deadline():
    t = TaskState(type=TaskType.RESTING, priority=50, deadline=100.0)
    assert not t.expired(now=99.0)
    assert t.expired(now=100.0)


def test_no_deadline_never_expires():
    t = TaskState(type=TaskType.RESTING, priority=50)
    assert not t.expired(now=1e9)


def test_idle_task_never_expires():
    t = TaskState(deadline=1.0)
    assert not t.expired(now=100.0)


def test_all_original_task_types_exist():
    # The 13 task names from megamud.exe's task state machine
    for name in ("GETTING", "DROPPING", "STASHING", "EQUIPPING", "SEARCHING",
                 "RUNNING", "BLESSING", "CASTING", "RESTING", "WAITING",
                 "RELOGGING", "HANGING", "TRAINING"):
        assert hasattr(TaskType, name)
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_tasks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mmud.state.tasks'`

- [ ] **Step 3: Create `src/mmud/state/tasks.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto


class TaskType(Enum):
    """Multi-step activities, mirroring megamud.exe's task state machine."""
    IDLE = auto()
    GETTING = auto()
    DROPPING = auto()
    STASHING = auto()
    EQUIPPING = auto()
    SEARCHING = auto()
    RUNNING = auto()
    BLESSING = auto()
    CASTING = auto()
    RESTING = auto()
    WAITING = auto()
    RELOGGING = auto()
    HANGING = auto()
    TRAINING = auto()


@dataclass
class TaskState:
    type: TaskType = TaskType.IDLE
    priority: int = 0          # decision-chain slot that owns this task
    deadline: float = 0.0      # monotonic seconds; 0.0 = no deadline
    payload: dict = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.type is not TaskType.IDLE

    def expired(self, now: float) -> bool:
        return self.is_active and self.deadline > 0.0 and now >= self.deadline
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tasks.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/mmud/state/tasks.py tests/test_tasks.py
git commit -m "feat: TaskType enum and TaskState — task state machine core"
```

---

### Task 2: GameState task lifecycle + TaskChanged event

**Files:**
- Modify: `src/mmud/state/game_state.py`
- Modify: `src/mmud/events.py`
- Test: `tests/test_game_state.py` (append), `tests/test_events.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_game_state.py`:

```python
from mmud.state.tasks import TaskType


def test_game_state_starts_idle():
    gs = GameState()
    assert not gs.task.is_active


def test_begin_and_complete_task():
    gs = GameState()
    gs.begin_task(TaskType.RESTING, priority=50, timeout_s=30.0, now=100.0)
    assert gs.task.is_active
    assert gs.task.type is TaskType.RESTING
    assert gs.task.priority == 50
    assert gs.task.deadline == 130.0
    gs.complete_task()
    assert not gs.task.is_active


def test_begin_task_without_timeout_has_no_deadline():
    gs = GameState()
    gs.begin_task(TaskType.CASTING, priority=10, now=100.0)
    assert gs.task.deadline == 0.0


def test_abort_task():
    gs = GameState()
    gs.begin_task(TaskType.CASTING, priority=10, payload={"condition": "BLIND"})
    assert gs.task.payload == {"condition": "BLIND"}
    gs.abort_task()
    assert not gs.task.is_active
    assert gs.task.payload == {}
```

Append to `tests/test_events.py`:

```python
from mmud.events import TaskChanged


def test_task_changed_constructible():
    e = TaskChanged(task_type="RESTING", status="timeout")
    assert e.task_type == "RESTING"
    assert e.status == "timeout"
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_game_state.py tests/test_events.py -v`
Expected: new tests FAIL (`AttributeError: 'GameState' object has no attribute 'task'`, `ImportError: cannot import name 'TaskChanged'`)

- [ ] **Step 3: Modify `src/mmud/state/game_state.py`**

Add the import at the top (after the existing `from mmud.parser.matcher import MatchResult`):

```python
from mmud.state.tasks import TaskState, TaskType
```

Add to `__init__` (after `self._command_queue: deque[str] = deque()`):

```python
        self.task: TaskState = TaskState()
```

Add these methods (after `dequeue()` at the end of the class):

```python
    def begin_task(
        self,
        task_type: TaskType,
        priority: int,
        timeout_s: float = 0.0,
        payload: dict | None = None,
        now: float = 0.0,
    ) -> None:
        self.task = TaskState(
            type=task_type,
            priority=priority,
            deadline=(now + timeout_s) if timeout_s > 0.0 else 0.0,
            payload=payload or {},
        )

    def complete_task(self) -> None:
        self.task = TaskState()

    def abort_task(self) -> None:
        self.task = TaskState()
```

- [ ] **Step 4: Add `TaskChanged` to `src/mmud/events.py`**

Insert before the `GameEventBus` class:

```python
@dataclass
class TaskChanged:
    task_type: str   # TaskType name, e.g. "RESTING"
    status: str      # "started" | "completed" | "aborted" | "timeout"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_game_state.py tests/test_events.py -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/mmud/state/game_state.py src/mmud/events.py tests/test_game_state.py tests/test_events.py
git commit -m "feat: GameState task lifecycle (begin/complete/abort) + TaskChanged event"
```

---

### Task 3: DecisionEngine with priority slots and task pinning

**Files:**
- Create: `src/mmud/automation/decision.py`
- Test: `tests/test_decision.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_decision.py
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
             "PRIO_PARTY", "PRIO_TRAVEL", "PRIO_SEARCH"]
    values = [getattr(decision, n) for n in names]
    assert values == sorted(values)
    assert len(set(values)) == len(values)
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_decision.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mmud.automation.decision'`

- [ ] **Step 3: Create `src/mmud/automation/decision.py`**

```python
from __future__ import annotations
from typing import Protocol
from mmud.state.game_state import GameState

# Priority slots mirroring megamud.exe's DoSomething order (lower = tried first).
# Phases 2-11 register deciders into these slots; unused slots simply have no decider.
PRIO_QUEUE = 0      # queued commands (login, path steps, user/remote commands)
PRIO_CURE = 10      # condition cures + panic            (Phase 2)
PRIO_FLEE = 20      # flee/run rules                     (Phase 4)
PRIO_SPELLS = 30    # heal/mana/attack/pre-attack/bless  (current SpellEngine)
PRIO_COMBAT = 40    # melee attack/rest                  (current CombatEngine)
PRIO_REST = 50      # rest task management               (Phase 4)
PRIO_REFRESH = 60   # stats/inventory refresh            (Phase 5)
PRIO_BLESS = 70     # bless scheduling split-out         (Phase 4)
PRIO_EQUIP = 80     # auto-equip                         (Phase 5)
PRIO_ITEMS = 90     # get/drop/stash/cash                (Phase 5)
PRIO_PARTY = 100    # party heal/wait/share              (Phase 10)
PRIO_TRAVEL = 110   # path following / goto              (Phase 6)
PRIO_SEARCH = 120   # hidden-exit searching              (Phase 6)


class Decider(Protocol):
    """One slot in the decision chain: return a command to send, or None to pass."""

    def decide(self, state: GameState) -> str | None: ...


class QueueDecider:
    """Slot 0 — drains GameState's command queue (login, path steps, user commands)."""

    def decide(self, state: GameState) -> str | None:
        return state.dequeue()


class DecisionEngine:
    """Priority-ordered decider chain with task pinning, after megamud's DoSomething.

    While a task is active, slots at or below the task's priority are skipped
    (the bot is busy at that level). A higher-priority decider that returns a
    command preempts: the task is aborted before the command is issued.
    """

    def __init__(self) -> None:
        self._slots: list[tuple[int, str, Decider]] = []

    def register(self, name: str, decider: Decider, priority: int) -> None:
        self._slots.append((priority, name, decider))
        self._slots.sort(key=lambda slot: slot[0])

    def next_command(self, state: GameState) -> str | None:
        for priority, _name, decider in self._slots:
            if state.task.is_active and priority >= state.task.priority:
                return None
            cmd = decider.decide(state)
            if cmd is not None:
                if state.task.is_active:
                    state.abort_task()
                return cmd
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_decision.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/mmud/automation/decision.py tests/test_decision.py
git commit -m "feat: DecisionEngine — priority decider chain with task pinning/preemption"
```

---

### Task 4: Transcript test harness (FakeConnection)

Every later phase tests as "server transcript in → command sequence out". This task builds that fixture and proves it against current behavior.

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/test_bot.py` (append)

- [ ] **Step 1: Add the harness to `tests/conftest.py`**

Append:

```python
class FakeConnection:
    """Replays a scripted server transcript; records every command sent.

    Drop-in for MudConnection in MudBot: bot._conn = FakeConnection(lines).
    """

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.sent: list[str] = []

    async def connect(self) -> None:
        pass

    async def send(self, command: str) -> None:
        self.sent.append(command)

    async def readlines(self):
        for line in self._lines:
            yield line

    async def close(self) -> None:
        pass


def make_transcript_bot(lines: list[str], **bot_kwargs):
    """MudBot wired to a FakeConnection. await bot.run(), then assert on bot._conn.sent."""
    from mmud.bot import MudBot
    bot = MudBot("transcript", 0, patterns=bot_kwargs.pop("patterns", []), **bot_kwargs)
    bot._conn = FakeConnection(lines)
    return bot
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_bot.py`:

```python
from conftest import make_transcript_bot


@pytest.mark.asyncio
async def test_transcript_bot_rests_on_low_hp():
    # HP 10/100 out of combat -> CombatEngine rest_threshold (0.40) says "rest"
    bot = make_transcript_bot(["[HP=10/100]:\n"])
    await bot.run()
    assert "rest" in bot._conn.sent


@pytest.mark.asyncio
async def test_transcript_bot_sends_nothing_when_healthy():
    bot = make_transcript_bot(["[HP=100/100]:\n"])
    await bot.run()
    assert bot._conn.sent == []
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_bot.py -v -k transcript`
Expected: 2 passed (this validates the harness against CURRENT behavior — if these fail, the harness is wrong, not the bot; check that `bot.run()` reads via `self._conn.readlines()`)

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: all pass (141 total)

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_bot.py
git commit -m "test: FakeConnection transcript harness — transcript in, commands out"
```

---

### Task 5: Wire DecisionEngine into MudBot

**Files:**
- Modify: `src/mmud/bot.py`
- Test: `tests/test_bot.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bot.py`:

```python
from mmud.automation.decision import PRIO_COMBAT
from mmud.state.tasks import TaskType
from mmud.events import TaskChanged


@pytest.mark.asyncio
async def test_active_task_suppresses_combat_decider(unused_tcp_port):
    # Low HP would normally produce "rest", but an active task at PRIO_COMBAT pins it
    bot = make_transcript_bot(["[HP=10/100]:\n"])
    bot._state.begin_task(TaskType.RESTING, priority=PRIO_COMBAT)
    await bot.run()
    assert "rest" not in bot._conn.sent


def test_task_timeout_aborts_and_emits(unused_tcp_port):
    from mmud.events import GameEventBus
    received = []
    bus = GameEventBus()
    bus.subscribe(TaskChanged, received.append)
    bot = make_transcript_bot([], event_bus=bus)
    bot._state.begin_task(TaskType.CASTING, priority=10, timeout_s=5.0, now=100.0)
    bot._check_task_timeout(now=106.0)
    assert not bot._state.task.is_active
    assert any(e.status == "timeout" and e.task_type == "CASTING" for e in received)


def test_task_not_expired_is_untouched(unused_tcp_port):
    bot = make_transcript_bot([])
    bot._state.begin_task(TaskType.CASTING, priority=10, timeout_s=5.0, now=100.0)
    bot._check_task_timeout(now=104.0)
    assert bot._state.task.is_active
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_bot.py -v -k "task"`
Expected: FAIL (`AttributeError: 'MudBot' object has no attribute '_check_task_timeout'`; the suppression test fails because `_next_command` ignores tasks)

- [ ] **Step 3: Modify `src/mmud/bot.py`**

Add to the imports:

```python
from mmud.automation.decision import (
    DecisionEngine, QueueDecider, PRIO_QUEUE, PRIO_SPELLS, PRIO_COMBAT,
)
from mmud.events import TaskChanged   # add to the existing events import list
```

In `__init__`, after `self._spell_engine = SpellEngine(self._config.spells)`, add:

```python
        self._engine = DecisionEngine()
        self._engine.register("queue", QueueDecider(), PRIO_QUEUE)
        self._engine.register("spells", self._spell_engine, PRIO_SPELLS)
        self._engine.register("combat", self._combat, PRIO_COMBAT)
```

Replace the body of `_next_command`:

```python
    def _next_command(self) -> str | None:
        return self._engine.next_command(self._state)
```

In `_ticker()`, after `self._check_afk()`, add a timeout check; and add the new method:

```python
            self._check_task_timeout(time.monotonic())
```

```python
    def _check_task_timeout(self, now: float) -> None:
        if self._state.task.expired(now):
            task_name = self._state.task.type.name
            self._state.abort_task()
            self._emit(TaskChanged(task_type=task_name, status="timeout"))
```

- [ ] **Step 4: Run the new tests**

Run: `pytest tests/test_bot.py -v -k "task"`
Expected: 3 passed

- [ ] **Step 5: Run the full suite — behavior invariant check**

Run: `pytest -q`
Expected: ALL pass. The chain (queue=0, spells=30, combat=40) reproduces the old queue→spells→combat order exactly; any failure here means the wiring changed behavior — stop and fix before committing.

- [ ] **Step 6: Commit**

```bash
git add src/mmud/bot.py tests/test_bot.py
git commit -m "feat: MudBot delegates to DecisionEngine; task timeouts abort via ticker"
```

---

### Task 6: Self-review + docs touch-up

- [ ] **Step 1: Verify the full suite and grep for leftovers**

Run: `pytest -q` → all pass.
Run: `grep -rn "spell_engine.decide\|_combat.decide" src/mmud/bot.py` → expect NO direct calls left in `bot.py` (both go through the engine now).

- [ ] **Step 2: Update README architecture section**

In `README.md`, find the architecture description of the command decision (queue → spells → combat) and replace it with one sentence: commands are decided by a priority decider chain (`src/mmud/automation/decision.py`) with a task state machine (`src/mmud/state/tasks.py`), mirroring the original MegaMud "DoSomething" loop; current slots are queue (0), spells (30), combat (40), with reserved slots for cures, flee, items, party, travel, and search.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: decision-engine architecture in README"
```

---

## Verification

- `pytest -q` — full suite green (139 pre-existing + ~20 new).
- Manual smoke: `python -m mmud.tui --host <bbs> --port <port>` — connect, confirm rest/heal/attack behavior is unchanged from commit 37b69ea.
- Hand-off check for Phase 2: `DecisionEngine.register("cures", CureDecider(...), PRIO_CURE)` is the only integration point Phase 2 needs.
