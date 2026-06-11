# Phase 2: Conditions, Cures, and Panic Safety — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect status conditions (poisoned/diseased/held/stunned/blind/confused), auto-cure them, interrupt running tasks, hang up on death or danger, and auto-reconnect — the "don't die, don't get stuck" layer.

**Architecture:** A regex trigger table (`conditions.py`) maps server lines to condition onset/recovery; `GameState.conditions` holds the active set. A `CureDecider` registered at `PRIO_CURE` (above combat) issues configured cure commands as `CASTING` tasks — the Phase 1 task-pinning prevents re-spamming while a cure is pending, and the 10s task timeout retries if no recovery line arrives. A `SafetyMonitor` watches every line for death/danger and requests hangup; `MudBot.run()` honors it and optionally reconnects.

**Tech Stack:** Python 3.11+, stdlib `re`. Depends on Phase 1 (DecisionEngine, TaskState, FakeConnection harness).

**Prerequisite:** Phase 1 complete (`src/mmud/automation/decision.py` exists, `pytest -q` green).

---

## File Map

```
src/mmud/
  state/conditions.py       NEW — Condition enum + onset/recovery regex tables
  state/game_state.py       MODIFY — conditions set
  automation/cures.py       NEW — CureDecider (PRIO_CURE slot)
  automation/safety.py      NEW — SafetyMonitor (hangup triggers)
  config/schema.py          MODIFY — HealthConfig, SafetyConfig
  config/loader.py          MODIFY — parse [health], [safety]
  events.py                 MODIFY — ConditionChanged, HangupTriggered
  bot.py                    MODIFY — wire conditions/cures/safety, reconnect loop
tests/
  test_conditions.py        NEW
  test_cures.py             NEW
  test_safety.py            NEW
  test_bot.py               MODIFY — end-to-end transcript tests
  test_config.py            MODIFY — new section parsing
characters/example.toml     MODIFY — document new sections
```

---

### Task 1: Condition enum + trigger tables

**Files:**
- Create: `src/mmud/state/conditions.py`
- Test: `tests/test_conditions.py`

> NOTE: The regex literals below are educated reconstructions of MajorMud's wording (from megamud.exe's `condition_onset_parse` trigger concept — the original's exact strings live in MESSAGES.MD which varies per server). They are deliberately broad. The in-person testing plan (`docs/testing-plan.md`) records the real server's wording; tune there.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_conditions.py
from mmud.state.conditions import Condition, scan_onset, scan_recovery


def test_poison_onset():
    assert scan_onset("You have been poisoned!") is Condition.POISONED


def test_blind_onset():
    assert scan_onset("You are blind!") is Condition.BLIND
    assert scan_onset("You cannot see a thing!") is Condition.BLIND


def test_held_onset():
    assert scan_onset("You have been paralyzed!") is Condition.HELD
    assert scan_onset("You cannot move!") is Condition.HELD


def test_disease_onset():
    assert scan_onset("You feel very ill.") is Condition.DISEASED


def test_normal_line_is_not_a_condition():
    assert scan_onset("You notice 2 orcs here.") is None
    assert scan_onset("[HP=100/100]:") is None
    assert scan_onset("") is None


def test_poison_recovery():
    assert scan_recovery("The poison has worn off.") is Condition.POISONED


def test_blind_recovery():
    assert scan_recovery("You can see again!") is Condition.BLIND


def test_recovery_does_not_match_onset_lines():
    assert scan_recovery("You have been poisoned!") is None
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_conditions.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `src/mmud/state/conditions.py`**

```python
from __future__ import annotations
import re
from enum import Enum, auto


class Condition(Enum):
    POISONED = auto()
    DISEASED = auto()
    HELD = auto()        # held / paralyzed
    STUNNED = auto()
    BLIND = auto()
    CONFUSED = auto()


# Server wording varies; these are broad. Tune against the live server and
# record actual lines in docs/testing-plan.md.
ONSET_PATTERNS: list[tuple[re.Pattern, Condition]] = [
    (re.compile(r"you (?:are|have been|feel) .*poison", re.IGNORECASE), Condition.POISONED),
    (re.compile(r"you (?:are|have been) diseased|you feel very ill", re.IGNORECASE), Condition.DISEASED),
    (re.compile(r"you (?:are|have been) (?:held|paralyzed)|you cannot move", re.IGNORECASE), Condition.HELD),
    (re.compile(r"you (?:are|have been) stunned|you see stars", re.IGNORECASE), Condition.STUNNED),
    (re.compile(r"you (?:are|have been|go) blind|you cannot see", re.IGNORECASE), Condition.BLIND),
    (re.compile(r"you (?:are|feel) confused|your head spins", re.IGNORECASE), Condition.CONFUSED),
]

RECOVERY_PATTERNS: list[tuple[re.Pattern, Condition]] = [
    (re.compile(r"poison has worn off|poison leaves? your", re.IGNORECASE), Condition.POISONED),
    (re.compile(r"you feel healthy again|disease has been cured", re.IGNORECASE), Condition.DISEASED),
    (re.compile(r"you can move again|no longer (?:held|paralyzed)", re.IGNORECASE), Condition.HELD),
    (re.compile(r"no longer stunned|your head clears", re.IGNORECASE), Condition.STUNNED),
    (re.compile(r"you can see again|your (?:sight|vision) returns", re.IGNORECASE), Condition.BLIND),
    (re.compile(r"no longer confused|your mind clears", re.IGNORECASE), Condition.CONFUSED),
]


def scan_onset(line: str) -> Condition | None:
    for pattern, condition in ONSET_PATTERNS:
        if pattern.search(line):
            return condition
    return None


def scan_recovery(line: str) -> Condition | None:
    for pattern, condition in RECOVERY_PATTERNS:
        if pattern.search(line):
            return condition
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_conditions.py -v`
Expected: 8 passed

- [ ] **Step 5: Add `conditions` to GameState**

In `src/mmud/state/game_state.py` `__init__`, after `self.active_effects: set[str] = set()`:

```python
        self.conditions: set = set()   # set[Condition] — active status conditions
```

- [ ] **Step 6: Commit**

```bash
git add src/mmud/state/conditions.py src/mmud/state/game_state.py tests/test_conditions.py
git commit -m "feat: condition trigger tables — poisoned/diseased/held/stunned/blind/confused"
```

---

### Task 2: HealthConfig + SafetyConfig schema and loader

**Files:**
- Modify: `src/mmud/config/schema.py`, `src/mmud/config/loader.py`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_health_and_safety_sections(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        """
[health]
blind_cmd = "cast purify vision"
poison_cmd = "cast neutralize poison"

[safety]
hangup_on_death = true
hangup_players = ["BadGuy", "Killer"]
panic_cmd = "recall"
reconnect = true
max_redials = 5
"""
    )
    cfg = load_config(p)
    assert cfg.health.blind_cmd == "cast purify vision"
    assert cfg.health.poison_cmd == "cast neutralize poison"
    assert cfg.health.disease_cmd == ""
    assert cfg.safety.hangup_on_death is True
    assert cfg.safety.hangup_players == ["BadGuy", "Killer"]
    assert cfg.safety.panic_cmd == "recall"
    assert cfg.safety.reconnect is True
    assert cfg.safety.max_redials == 5


def test_health_and_safety_defaults():
    cfg = load_config(None)
    assert cfg.health.blind_cmd == ""
    assert cfg.safety.hangup_on_death is True
    assert cfg.safety.reconnect is False
    assert cfg.safety.max_redials == 3
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_config.py -v -k "health"`
Expected: FAIL (`AttributeError: 'MudConfig' object has no attribute 'health'`)

- [ ] **Step 3: Add to `src/mmud/config/schema.py`** (after `AfkConfig`):

```python
@dataclass
class HealthConfig:
    blind_cmd: str = ""      # cure blindness, e.g. "cast purify vision"
    poison_cmd: str = ""     # cure poison
    disease_cmd: str = ""    # cure disease
    freedom_cmd: str = ""    # break hold/paralysis


@dataclass
class SafetyConfig:
    hangup_on_death: bool = True
    hangup_players: list[str] = field(default_factory=list)  # disconnect if seen in room
    panic_cmd: str = ""      # sent before a panic hangup (e.g. "recall")
    reconnect: bool = False  # auto-reconnect on connection loss
    max_redials: int = 3
```

Add to `MudConfig` (after `afk`):

```python
    health: HealthConfig = field(default_factory=HealthConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
```

- [ ] **Step 4: Add to `src/mmud/config/loader.py`**

Add `HealthConfig, SafetyConfig` to the schema import list, then after the `afk` block:

```python
    if h := data.get("health"):
        cfg.health = HealthConfig(
            blind_cmd=h.get("blind_cmd", ""),
            poison_cmd=h.get("poison_cmd", ""),
            disease_cmd=h.get("disease_cmd", ""),
            freedom_cmd=h.get("freedom_cmd", ""),
        )
    if sf := data.get("safety"):
        cfg.safety = SafetyConfig(
            hangup_on_death=sf.get("hangup_on_death", True),
            hangup_players=sf.get("hangup_players", []),
            panic_cmd=sf.get("panic_cmd", ""),
            reconnect=sf.get("reconnect", False),
            max_redials=sf.get("max_redials", 3),
        )
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_config.py -v`
Expected: all pass

- [ ] **Step 6: Document in `characters/example.toml`** (append):

```toml
[health]
# Cure commands sent automatically when the condition is detected (blank = don't cure)
blind_cmd = ""       # e.g. "cast purify vision"
poison_cmd = ""      # e.g. "cast neutralize poison"
disease_cmd = ""
freedom_cmd = ""     # break hold/paralysis

[safety]
hangup_on_death = true
hangup_players = []  # disconnect immediately if any of these appear in the room
panic_cmd = ""       # sent before a panic hangup
reconnect = false    # auto-reconnect on connection loss
max_redials = 3
```

- [ ] **Step 7: Commit**

```bash
git add src/mmud/config/schema.py src/mmud/config/loader.py tests/test_config.py characters/example.toml
git commit -m "feat: [health] and [safety] config sections"
```

---

### Task 3: CureDecider

**Files:**
- Create: `src/mmud/automation/cures.py`
- Test: `tests/test_cures.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cures.py
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
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_cures.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `src/mmud/automation/cures.py`**

```python
from __future__ import annotations
import time
from typing import Callable
from mmud.automation.decision import PRIO_CURE
from mmud.config.schema import HealthConfig
from mmud.state.conditions import Condition
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType

# Retry window: if no recovery line arrives, the task times out and we re-cast.
CURE_TIMEOUT_S = 10.0

# (condition, config attribute) in cure-priority order — blind first.
_CURE_ORDER: list[tuple[Condition, str]] = [
    (Condition.BLIND, "blind_cmd"),
    (Condition.HELD, "freedom_cmd"),
    (Condition.POISONED, "poison_cmd"),
    (Condition.DISEASED, "disease_cmd"),
]


class CureDecider:
    """PRIO_CURE slot: cast configured cure commands for active conditions.

    Issuing a cure begins a CASTING task at PRIO_CURE, which pins the decision
    chain (including this decider) until the recovery line completes the task
    or the timeout aborts it — no re-spamming while the cure is in flight.
    """

    def __init__(self, config: HealthConfig, now: Callable[[], float] = time.monotonic) -> None:
        self._cfg = config
        self._now = now

    def decide(self, state: GameState) -> str | None:
        for condition, attr in _CURE_ORDER:
            cmd = getattr(self._cfg, attr)
            if cmd and condition in state.conditions:
                state.begin_task(
                    TaskType.CASTING,
                    priority=PRIO_CURE,
                    timeout_s=CURE_TIMEOUT_S,
                    payload={"condition": condition.name},
                    now=self._now(),
                )
                return cmd
        return None
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_cures.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/mmud/automation/cures.py tests/test_cures.py
git commit -m "feat: CureDecider — auto-cure conditions as CASTING tasks with retry timeout"
```

---

### Task 4: SafetyMonitor

**Files:**
- Create: `src/mmud/automation/safety.py`
- Test: `tests/test_safety.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_safety.py
from mmud.automation.safety import SafetyMonitor
from mmud.config.schema import SafetyConfig


def test_death_triggers_hangup():
    m = SafetyMonitor(SafetyConfig(hangup_on_death=True))
    m.process_line("You have died!")
    assert m.hangup_requested
    assert "death" in m.reason


def test_death_hangup_can_be_disabled():
    m = SafetyMonitor(SafetyConfig(hangup_on_death=False))
    m.process_line("You have died!")
    assert not m.hangup_requested


def test_hangup_player_seen_in_room():
    m = SafetyMonitor(SafetyConfig(hangup_players=["BadGuy"]))
    m.process_line("Also here: BadGuy, an orc warrior.")
    assert m.hangup_requested
    assert "BadGuy" in m.reason


def test_hangup_player_in_conversation_is_ignored():
    # Only room-presence lines count — a tell mentioning the name must not hang up
    m = SafetyMonitor(SafetyConfig(hangup_players=["BadGuy"]))
    m.process_line("[Friend tells you] watch out for BadGuy")
    assert not m.hangup_requested


def test_normal_lines_do_nothing():
    m = SafetyMonitor(SafetyConfig())
    m.process_line("You notice 2 orcs here.")
    m.process_line("[HP=100/100]:")
    assert not m.hangup_requested


def test_manual_request():
    m = SafetyMonitor(SafetyConfig())
    m.request_hangup("remote @hangup from Friend")
    assert m.hangup_requested
    assert m.reason == "remote @hangup from Friend"
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_safety.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `src/mmud/automation/safety.py`**

```python
from __future__ import annotations
import re
from mmud.config.schema import SafetyConfig

_DEATH_RE = re.compile(
    r"you have died|you are dead|your lifeless body|death has come", re.IGNORECASE
)
# Hangup-player matching is restricted to room-presence lines to avoid
# false positives from conversations mentioning the name.
_ROOM_PRESENCE_RE = re.compile(r"^\s*also here:|\benters? the room\b", re.IGNORECASE)


class SafetyMonitor:
    """Watches server output for danger and requests a disconnect."""

    def __init__(self, config: SafetyConfig) -> None:
        self._cfg = config
        self.hangup_requested = False
        self.reason = ""

    def process_line(self, line: str) -> None:
        if self.hangup_requested:
            return
        if self._cfg.hangup_on_death and _DEATH_RE.search(line):
            self.request_hangup("death detected")
            return
        if self._cfg.hangup_players and _ROOM_PRESENCE_RE.search(line):
            for name in self._cfg.hangup_players:
                if name and re.search(rf"\b{re.escape(name)}\b", line, re.IGNORECASE):
                    self.request_hangup(f"hangup player seen: {name}")
                    return

    def request_hangup(self, reason: str) -> None:
        self.hangup_requested = True
        self.reason = reason

    def reset(self) -> None:
        self.hangup_requested = False
        self.reason = ""
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_safety.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/mmud/automation/safety.py tests/test_safety.py
git commit -m "feat: SafetyMonitor — hangup on death or hangup-player sighting"
```

---

### Task 5: Wire conditions, cures, and safety into MudBot

**Files:**
- Modify: `src/mmud/bot.py`, `src/mmud/events.py`
- Test: `tests/test_bot.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bot.py`:

```python
from mmud.config.schema import HealthConfig, SafetyConfig
from mmud.events import ConditionChanged, HangupTriggered
from mmud.state.conditions import Condition


@pytest.mark.asyncio
async def test_condition_onset_tracked_and_cured():
    config = MudConfig()
    config.health = HealthConfig(poison_cmd="cast neutralize")
    bot = make_transcript_bot(
        ["You have been poisoned!\n", "[HP=100/100]:\n"], config=config
    )
    await bot.run()
    assert Condition.POISONED in bot._state.conditions
    assert "cast neutralize" in bot._conn.sent


@pytest.mark.asyncio
async def test_condition_recovery_clears_and_completes_task():
    config = MudConfig()
    config.health = HealthConfig(poison_cmd="cast neutralize")
    bot = make_transcript_bot(
        ["You have been poisoned!\n", "The poison has worn off.\n"], config=config
    )
    await bot.run()
    assert Condition.POISONED not in bot._state.conditions
    assert not bot._state.task.is_active


@pytest.mark.asyncio
async def test_condition_events_emitted():
    received = []
    bus = GameEventBus()
    bus.subscribe(ConditionChanged, received.append)
    bot = make_transcript_bot(
        ["You have been poisoned!\n", "The poison has worn off.\n"], event_bus=bus
    )
    await bot.run()
    assert any(e.name == "POISONED" and e.active for e in received)
    assert any(e.name == "POISONED" and not e.active for e in received)


@pytest.mark.asyncio
async def test_death_hangs_up_and_stops_processing():
    received = []
    bus = GameEventBus()
    bus.subscribe(HangupTriggered, received.append)
    config = MudConfig()
    config.safety = SafetyConfig(hangup_on_death=True, reconnect=False)
    bot = make_transcript_bot(
        ["You have died!\n", "[HP=100/100]:\n"], config=config, event_bus=bus
    )
    await bot.run()
    assert any("death" in e.reason for e in received)


@pytest.mark.asyncio
async def test_blind_onset_stops_loop():
    from mmud.automation.loop_runner import LoopRunner
    from mmud.config.schema import NavigationConfig, StealthConfig
    bot = make_transcript_bot(["You are blind!\n"])
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), StealthConfig(),
                        [], bot._state, GameEventBus())
    runner.start()
    bot._loop_runner = runner
    await bot.run()
    assert not runner.running
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_bot.py -v -k "condition or death or blind"`
Expected: FAIL (`ImportError: cannot import name 'ConditionChanged'`)

- [ ] **Step 3: Add events to `src/mmud/events.py`** (before `GameEventBus`):

```python
@dataclass
class ConditionChanged:
    name: str      # Condition name, e.g. "POISONED"
    active: bool   # True = onset, False = recovered


@dataclass
class HangupTriggered:
    reason: str
```

- [ ] **Step 4: Modify `src/mmud/bot.py`**

Imports:

```python
from mmud.automation.cures import CureDecider
from mmud.automation.safety import SafetyMonitor
from mmud.automation.decision import PRIO_CURE   # extend the existing decision import
from mmud.state.conditions import scan_onset, scan_recovery
from mmud.events import ConditionChanged, HangupTriggered   # extend events import
```

In `__init__`, after the engine registrations from Phase 1:

```python
        self._safety = SafetyMonitor(self._config.safety)
        self._engine.register("cures", CureDecider(self._config.health), PRIO_CURE)
```

In `_process_line`, after `self._parse_vitals(clean)`, add:

```python
        self._parse_conditions(clean)
        self._safety.process_line(clean)
```

New method:

```python
    def _parse_conditions(self, line: str) -> None:
        if cond := scan_onset(line):
            if cond not in self._state.conditions:
                self._state.conditions.add(cond)
                self._emit(ConditionChanged(name=cond.name, active=True))
                # Conditions interrupt whatever the bot was doing
                if self._state.task.is_active:
                    self._state.abort_task()
                # Blind blocks movement: stop any running loop
                if cond.name == "BLIND" and self._loop_runner and self._loop_runner.running:
                    self.stop_all()
        if cond := scan_recovery(line):
            self._state.conditions.discard(cond)
            self._emit(ConditionChanged(name=cond.name, active=False))
            # Complete the pending cure task for this condition
            if (self._state.task.is_active
                    and self._state.task.payload.get("condition") == cond.name):
                self._state.complete_task()
```

In `run()`, change the read loop to honor hangup — replace the body of the `async for` loop:

```python
            async for line in self._conn.readlines():
                await self._process_line(line)
                if self._safety.hangup_requested:
                    self._emit(HangupTriggered(reason=self._safety.reason))
                    break
                cmd = self._next_command()
                if cmd:
                    await self._conn.send(cmd)
                    self._last_activity = time.monotonic()
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_bot.py -v` then `pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/mmud/bot.py src/mmud/events.py tests/test_bot.py
git commit -m "feat: wire conditions/cures/safety into bot — interrupt tasks, hangup on death"
```

---

### Task 6: Auto-reconnect loop + AFK low-HP hangup

**Files:**
- Modify: `src/mmud/bot.py`
- Test: `tests/test_bot.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bot.py`:

```python
@pytest.mark.asyncio
async def test_reconnect_retries_on_connection_loss(unused_tcp_port):
    # Nothing listening on the port -> ConnectionRefusedError each attempt
    config = MudConfig()
    config.safety = SafetyConfig(reconnect=True, max_redials=2)
    bot = MudBot("127.0.0.1", unused_tcp_port, patterns=[], config=config)
    attempts = []
    original_connect = bot._conn.connect

    async def counting_connect():
        attempts.append(1)
        await original_connect()

    bot._conn.connect = counting_connect
    bot._redial_delay_s = 0.0   # don't sleep in tests
    await bot.run()
    assert len(attempts) == 3   # initial + 2 redials


@pytest.mark.asyncio
async def test_no_reconnect_by_default(unused_tcp_port):
    bot = MudBot("127.0.0.1", unused_tcp_port, patterns=[])
    await bot.run()   # must return (refused), not raise or loop


@pytest.mark.asyncio
async def test_afk_low_hp_hangup():
    config = MudConfig()
    config.afk.enabled = True
    config.afk.hangup_on_low_hp = True
    bot = make_transcript_bot(["[HP=5/100]:\n"], config=config)
    await bot.run()
    assert bot._safety.hangup_requested
    assert "low hp" in bot._safety.reason.lower()
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_bot.py -v -k "reconnect or afk_low"`
Expected: FAIL — `run()` currently raises `ConnectionRefusedError`, and no low-HP hangup exists

- [ ] **Step 3: Modify `src/mmud/bot.py`**

Add an attribute in `__init__`:

```python
        self._redial_delay_s = 5.0
```

Rename the current `run()` to `_run_session()` (unchanged body), and add a new `run()`:

```python
    async def run(self) -> None:
        redials = 0
        while True:
            try:
                await self._run_session()
            except (ConnectionError, OSError):
                pass
            if self._safety.hangup_requested:
                break   # deliberate disconnect — never auto-reconnect past it
            if (not self._config.safety.reconnect
                    or redials >= self._config.safety.max_redials):
                break
            redials += 1
            await asyncio.sleep(self._redial_delay_s)
```

In `_parse_vitals`, inside the HP branch after `self._emit(HpChanged(...))`, add:

```python
            if (self._config.afk.enabled and self._config.afk.hangup_on_low_hp
                    and max_hp > 0 and hp / max_hp <= self._config.combat.flee_threshold):
                self._safety.request_hangup(f"low HP while AFK ({hp}/{max_hp})")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_bot.py -v` then `pytest -q`
Expected: all pass. NOTE: `tests/test_bot.py` has pre-existing tests that call `bot.run()` against one-shot fake servers and expect it to return — verify none of them now loop (they use default config, `reconnect=False`, so they get exactly one session).

- [ ] **Step 5: Commit**

```bash
git add src/mmud/bot.py tests/test_bot.py
git commit -m "feat: auto-reconnect with max redials; AFK low-HP hangup"
```

---

## Verification

- `pytest -q` — full suite green.
- Live test (user): poison/blind your character (or wait for a monster to do it), confirm the cure casts and the `[bot]` doesn't spam it; type a death-message-like line cannot be simulated safely — verify hangup_players instead with a friend's character entering the room while their name is in `hangup_players`.
- Record the server's ACTUAL condition onset/recovery wording in `docs/testing-plan.md` and tune `src/mmud/state/conditions.py` regexes to match.
