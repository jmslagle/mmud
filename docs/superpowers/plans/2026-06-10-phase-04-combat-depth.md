# Phase 4: Combat Depth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring combat to parity with megamud.exe: monster-DB-aware sightings, run rules (too many / too strong → run), target priority & ordering, attack-spell cast limits with weapon swap, the backstab workflow, and PvP reaction.

**Architecture:** A `MonsterDB` (name-indexed wrapper over the rewritten `load_monsters()`) upgrades `GameState.monsters_present` from `list[str]` to `list[MonsterSighting]` (name + count + DB record). A `RunDecider` at `PRIO_FLEE` enqueues escape moves as a `RUNNING` task. `CombatEngine` gains priority targeting/ordering and a polite-attacks gate. `SpellEngine` gains a per-encounter cast counter with weapon-swap commands. Backstab and PvP are line-driven monitors (the `SafetyMonitor` pattern: bot feeds them cleaned lines) plus deciders.

**Tech Stack:** Python 3.11+, stdlib only. Transcript-tested via `make_transcript_bot` (tests/conftest.py).

**Prerequisites:**
1. MDB2 parser rewrite complete (`docs/superpowers/plans/2026-06-10-mdb2-parser-rewrite.md`) — `load_monsters()` returns 788 records.
2. `pytest -q` green.

---

## File Map

```
src/mmud/
  data/monster_db.py        NEW — MonsterDB name-indexed lookup
  state/game_state.py       MODIFY — MonsterSighting, monsters_present upgrade, players_present, move_history
  parser/room_parser.py     MODIFY — extract_sightings (with counts), extract_players
  combat/combat.py          MODIFY — targeting, attack_order, polite_attacks
  combat/backstab.py        NEW — track→hide→sneak→backstab state machine
  combat/pvp.py             NEW — PvP monitor + reaction
  automation/run_rules.py   NEW — RunDecider (PRIO_FLEE)
  automation/spells.py      MODIFY — cast-count limit + weapon swap
  config/schema.py          MODIFY — combat/spells additions, PvpConfig
  config/loader.py          MODIFY — parse new fields, [pvp]
  bot.py                    MODIFY — wire MonsterDB, sightings, run/backstab/pvp
tests/
  test_monster_db.py        NEW
  test_room_parser.py       MODIFY — sighting/player extraction
  test_game_state.py        MODIFY — sighting helpers
  test_run_rules.py         NEW
  test_combat.py            MODIFY — targeting tests
  test_spells.py            MODIFY — cast-limit tests
  test_backstab.py          NEW
  test_pvp.py               NEW
  test_config.py            MODIFY
characters/example.toml     MODIFY
```

---

### Task 1: MonsterDB

**Files:**
- Create: `src/mmud/data/monster_db.py`
- Test: `tests/test_monster_db.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_monster_db.py
from mmud.data.monster_db import MonsterDB


def _db(data_dir):
    return MonsterDB.from_file(data_dir / "MONSTERS.MD")


def test_lookup_exact(data_dir):
    db = _db(data_dir)
    m = db.find("giant rat")
    assert m is not None and m.name == "giant rat"


def test_lookup_strips_article_and_case(data_dir):
    db = _db(data_dir)
    assert db.find("A Giant Rat").name == "giant rat"
    assert db.find("the giant rat").name == "giant rat"


def test_lookup_depluralizes(data_dir):
    db = _db(data_dir)
    # "2 orc warriors" room text yields plural name
    m = db.find("orc warriors")
    assert m is not None


def test_unknown_returns_none(data_dir):
    assert _db(data_dir).find("zzz frobnitz") is None


def test_exp_lookup(data_dir):
    db = _db(data_dir)
    assert db.exp_value("giant rat") > 0
    assert db.exp_value("zzz frobnitz") == 0
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_monster_db.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `src/mmud/data/monster_db.py`**

```python
from __future__ import annotations
import pathlib
import re
from mmud.data.binary import Monster, load_monsters

_ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)


def normalize(name: str) -> str:
    """Lowercase, strip leading article and whitespace."""
    return _ARTICLE_RE.sub("", name.strip().lower())


class MonsterDB:
    """Name-indexed monster lookup over MONSTERS.MD records."""

    def __init__(self, monsters: list[Monster]) -> None:
        self._by_name: dict[str, Monster] = {}
        for m in monsters:
            for candidate in (m.name, m.short_name1, m.short_name2):
                key = normalize(candidate)
                if key and key not in self._by_name:
                    self._by_name[key] = m

    @classmethod
    def from_file(cls, path: pathlib.Path) -> "MonsterDB":
        return cls(load_monsters(path))

    def find(self, name: str) -> Monster | None:
        key = normalize(name)
        if key in self._by_name:
            return self._by_name[key]
        # naive de-pluralize: "orc warriors" -> "orc warrior"
        if key.endswith("s") and key[:-1] in self._by_name:
            return self._by_name[key[:-1]]
        return None

    def exp_value(self, name: str) -> int:
        m = self.find(name)
        return m.exp_value if m else 0
```

- [ ] **Step 4: Run tests** — `pytest tests/test_monster_db.py -v` → 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/mmud/data/monster_db.py tests/test_monster_db.py
git commit -m "feat: MonsterDB — name-indexed monster lookup over MONSTERS.MD"
```

---

### Task 2: MonsterSighting + room-parser quantities + players_present

**Files:**
- Modify: `src/mmud/state/game_state.py`, `src/mmud/parser/room_parser.py`, `src/mmud/bot.py`
- Test: `tests/test_room_parser.py`, `tests/test_game_state.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_room_parser.py`:

```python
def test_extract_sightings_with_counts():
    p = RoomParser({})
    s = p.extract_sightings("Also here: a dark elf, 2 orc warriors.")
    assert ("dark elf", 1) in s
    assert ("orc warriors", 2) in s


def test_extract_sightings_single():
    p = RoomParser({})
    assert p.extract_sightings("A huge dragon is here.") == [("huge dragon", 1)]


def test_extract_players_capitalized_names():
    p = RoomParser({})
    # Player names: capitalized, no article, not a known count pattern
    assert p.extract_players("Also here: Krang Moan, a dark elf.") == ["Krang Moan"]


def test_extract_players_none():
    p = RoomParser({})
    assert p.extract_players("Also here: a dark elf, 2 orc warriors.") == []
```

Append to `tests/test_game_state.py`:

```python
from mmud.state.game_state import GameState, MonsterSighting


def test_sightings_and_names():
    gs = GameState()
    gs.monsters_present.append(MonsterSighting(name="orc", count=2, exp_each=100))
    gs.monsters_present.append(MonsterSighting(name="rat", count=1, exp_each=20))
    assert gs.monster_names() == ["orc", "rat"]
    assert gs.monster_count() == 3
    assert gs.monster_exp_total() == 220
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_room_parser.py tests/test_game_state.py -v -k "sighting or extract_players"`
Expected: FAIL (no `extract_sightings`, no `MonsterSighting`)

- [ ] **Step 3: Add `MonsterSighting` to `src/mmud/state/game_state.py`**

After the `Effect` dataclass:

```python
@dataclass
class MonsterSighting:
    name: str
    count: int = 1
    exp_each: int = 0       # from MonsterDB; 0 if unknown
    record_id: int = -1     # MONSTERS.MD record id; -1 if unknown
```

Change `monsters_present` in `__init__` and add `players_present` + `move_history` (used by Task 4's run-backwards):

```python
        self.monsters_present: list[MonsterSighting] = []
        self.players_present: list[str] = []
        self.move_history: deque[str] = deque(maxlen=20)  # recent movement cmds
```

Add helper methods after `set_combat`:

```python
    def monster_names(self) -> list[str]:
        return [s.name for s in self.monsters_present]

    def monster_count(self) -> int:
        return sum(s.count for s in self.monsters_present)

    def monster_exp_total(self) -> int:
        return sum(s.count * s.exp_each for s in self.monsters_present)
```

- [ ] **Step 4: Add `extract_sightings` / `extract_players` to `src/mmud/parser/room_parser.py`**

Add a count-prefix regex at module level:

```python
_COUNT_PREFIX_RE = re.compile(r"^(\d+)\s+(.*)$")
_PLAYER_NAME_RE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?$")
```

Add to `RoomParser` (reusing the existing `extract_monsters` split logic — refactor
its comma/and splitting into a private `_split_entities(line) -> list[str]` used
by both; entities keep their original casing for player detection):

```python
    def extract_sightings(self, line: str) -> list[tuple[str, int]]:
        """Monster names with counts: '2 orc warriors' -> ('orc warriors', 2)."""
        out = []
        for name in self.extract_monsters(line):   # lowercased, article-stripped
            m = _COUNT_PREFIX_RE.match(name)
            if m:
                out.append((m.group(2), int(m.group(1))))
            else:
                out.append((name, 1))
        return out

    def extract_players(self, line: str) -> list[str]:
        """Capitalized non-article entities in room-presence lines = players."""
        m = _ALSO_HERE_RE.match(line)
        if not m:
            return []
        out = []
        for raw in re.split(r",\s*|\s+and\s+", m.group(1).rstrip(".")):
            raw = raw.strip()
            if raw and _PLAYER_NAME_RE.match(raw):
                out.append(raw)
        return out
```

NOTE: if `extract_monsters` currently strips digit counts before returning,
move the stripping into `extract_sightings` (capture count first) and keep
`extract_monsters` returning names-only by delegating:
`return [name for name, _ in self.extract_sightings(line)]`. Existing
room-parser tests must stay green — they define the contract.

- [ ] **Step 5: Wire into `src/mmud/bot.py` `_parse_room`**

`MudBot.__init__` gains a MonsterDB (after `self._room_parser = ...`):

```python
        from mmud.data.monster_db import MonsterDB
        monsters_md = (data_dir / "MONSTERS.MD") if data_dir else None
        self._monster_db = (MonsterDB.from_file(monsters_md)
                            if monsters_md and monsters_md.exists() else MonsterDB([]))
```

Replace the monster-extend branch of `_parse_room` with:

```python
        else:
            sightings = self._room_parser.extract_sightings(line)
            if sightings:
                for name, count in sightings:
                    rec = self._monster_db.find(name)
                    self._state.monsters_present.append(MonsterSighting(
                        name=name, count=count,
                        exp_each=rec.exp_value if rec else 0,
                        record_id=rec.record_id if rec else -1,
                    ))
                self._emit(MonstersSeen(monsters=[n for n, _ in sightings]))
            players = self._room_parser.extract_players(line)
            if players:
                self._state.players_present = players
```

Also clear `players_present` next to the existing `monsters_present.clear()` on
room change. Fix the one consumer of the old `list[str]` shape:
`combat.py:30` becomes `state.monster_names()[0] if state.monsters_present else ""`
(full targeting comes in Task 5). Check TUI usages:
`grep -rn "monsters_present" src/mmud/tui/` and switch any to `monster_names()`.

- [ ] **Step 6: Run the whole suite** — `pytest -q` → green (fix any straggler
usages the grep finds; the contract is `monsters_present: list[MonsterSighting]`).

- [ ] **Step 7: Commit**

```bash
git add src/mmud/state/game_state.py src/mmud/parser/room_parser.py src/mmud/bot.py src/mmud/combat/combat.py tests/
git commit -m "feat: MonsterSighting with counts + DB exp; players_present tracking"
```

---

### Task 3: Config — combat/spells additions + [pvp]

**Files:**
- Modify: `src/mmud/config/schema.py`, `src/mmud/config/loader.py`, `characters/example.toml`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_phase4_combat_config(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        """
[combat]
max_monsters = 3
max_monster_exp = 5000
run_backwards = true
run_if_bs_fails = true
monster_priority = ["ancient dragon", "orc chieftain"]

[spells]
max_cast_count = 4
cast_weapon_cmd = "arm staff"
melee_weapon_cmd = "arm warhammer"

[pvp]
action = "flee"
spell = ""
flee_rooms = 2
hangup_delay_s = 10
"""
    )
    cfg = load_config(p)
    assert cfg.combat.max_monsters == 3
    assert cfg.combat.max_monster_exp == 5000
    assert cfg.combat.run_backwards is True
    assert cfg.combat.monster_priority == ["ancient dragon", "orc chieftain"]
    assert cfg.spells.max_cast_count == 4
    assert cfg.spells.melee_weapon_cmd == "arm warhammer"
    assert cfg.pvp.action == "flee"
    assert cfg.pvp.hangup_delay_s == 10


def test_phase4_defaults():
    cfg = load_config(None)
    assert cfg.combat.max_monsters == 0          # 0 = no limit
    assert cfg.combat.max_monster_exp == 0       # 0 = no limit
    assert cfg.spells.max_cast_count == 0        # 0 = unlimited
    assert cfg.pvp.action == ""                  # "" = ignore players
```

- [ ] **Step 2: Run to confirm failure** — `pytest tests/test_config.py -v -k phase4` → AttributeError

- [ ] **Step 3: Schema additions** (`src/mmud/config/schema.py`)

Append to `CombatConfig`:

```python
    max_monsters: int = 0          # run if more monsters than this (0 = no limit)
    max_monster_exp: int = 0       # run if summed exp exceeds this (0 = no limit)
    run_backwards: bool = False    # retrace recent moves instead of 'flee'
    run_if_bs_fails: bool = False  # run away when a backstab attempt fails
    monster_priority: list[str] = field(default_factory=list)  # attack these first
```

Append to `SpellsConfig`:

```python
    max_cast_count: int = 0        # attack-spell casts per encounter (0 = unlimited)
    cast_weapon_cmd: str = ""      # full command to switch to the casting weapon
    melee_weapon_cmd: str = ""     # full command to switch to the melee weapon
```

New dataclass after `RemoteConfig`:

```python
@dataclass
class PvpConfig:
    action: str = ""               # "" ignore | "attack" | "flee" | "hangup" | command string
    spell: str = ""                # cast at the player when action == "attack"
    flee_rooms: int = 2
    hangup_delay_s: int = 0        # delay before hangup when action == "hangup"
```

Add to `MudConfig` after `remote`: `pvp: PvpConfig = field(default_factory=PvpConfig)`

- [ ] **Step 4: Loader** — extend the `combat`/`spells` blocks with the new keys
(same `c.get(...)`/`sp.get(...)` pattern, defaults as in the schema) and add:

```python
    if pv := data.get("pvp"):
        cfg.pvp = PvpConfig(
            action=pv.get("action", ""),
            spell=pv.get("spell", ""),
            flee_rooms=pv.get("flee_rooms", 2),
            hangup_delay_s=pv.get("hangup_delay_s", 0),
        )
```

(Remember to add `PvpConfig` to the loader's schema import list.)

- [ ] **Step 5: Run tests, document in example.toml, commit**

Run: `pytest tests/test_config.py -v` → all pass. Append the three sections to
`characters/example.toml` with the same comments as the schema. Then:

```bash
git add src/mmud/config/schema.py src/mmud/config/loader.py tests/test_config.py characters/example.toml
git commit -m "feat: phase-4 combat/spells config + [pvp] section"
```

---

### Task 4: RunDecider (PRIO_FLEE)

**Files:**
- Create: `src/mmud/automation/run_rules.py`
- Modify: `src/mmud/bot.py`
- Test: `tests/test_run_rules.py`

The decider triggers when the room is too dangerous, enqueues the whole escape
(queue drains one command per server line at PRIO_QUEUE), and pins the chain
with a `RUNNING` task so combat/spells don't fire mid-run. The bot completes
the task on the next room change with no monsters; the 15s timeout aborts it
otherwise.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_run_rules.py
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
    # engine would skip the slot while RUNNING pins it; decide() itself must
    # also be idempotent if called again
    assert gs.task.type is TaskType.RUNNING
```

- [ ] **Step 2: Run to confirm failure** — `pytest tests/test_run_rules.py -v` → ModuleNotFoundError

- [ ] **Step 3: Create `src/mmud/automation/run_rules.py`**

```python
from __future__ import annotations
import time
from typing import Callable
from mmud.automation.decision import PRIO_FLEE
from mmud.config.schema import CombatConfig, NavigationConfig
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType

RUN_TIMEOUT_S = 15.0

_INVERSE = {"n": "s", "s": "n", "e": "w", "w": "e",
            "ne": "sw", "sw": "ne", "nw": "se", "se": "nw",
            "u": "d", "d": "u"}


class RunDecider:
    """PRIO_FLEE slot: leave the room when it is too dangerous.

    Triggers when monster count exceeds combat.max_monsters or summed exp
    exceeds combat.max_monster_exp (0 = limit disabled). Enqueues
    navigation.flee_rooms escape moves and begins a RUNNING task that pins
    combat/spells until the bot observes a safe room (or the timeout aborts).
    """

    def __init__(self, combat: CombatConfig, nav: NavigationConfig,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._combat = combat
        self._nav = nav
        self._now = now

    def decide(self, state: GameState) -> str | None:
        if state.task.is_active:
            return None
        if not self._dangerous(state):
            return None
        moves = self._escape_moves(state)
        if not moves:
            return None
        state.begin_task(TaskType.RUNNING, priority=PRIO_FLEE,
                         timeout_s=RUN_TIMEOUT_S, now=self._now())
        first, rest = moves[0], moves[1:]
        for cmd in rest:
            state.enqueue(cmd)
        return first

    def _dangerous(self, state: GameState) -> bool:
        if self._combat.max_monsters and state.monster_count() > self._combat.max_monsters:
            return True
        if self._combat.max_monster_exp and state.monster_exp_total() > self._combat.max_monster_exp:
            return True
        return False

    def _escape_moves(self, state: GameState) -> list[str]:
        n = max(1, self._nav.flee_rooms)
        if self._combat.run_backwards:
            recent = list(state.move_history)[-n:]
            inv = [_INVERSE.get(m) for m in reversed(recent)]
            moves = [m for m in inv if m]
            if moves:
                return moves
        return ["flee"] * n
```

- [ ] **Step 4: Wire into bot** — in `MudBot.__init__` after the cures registration:

```python
        from mmud.automation.run_rules import RunDecider
        self._engine.register("run", RunDecider(self._config.combat,
                                                self._config.navigation), PRIO_FLEE)
```

Track movement history: in `run()`'s send path (both places a command is sent),
after `await self._conn.send(cmd)` add:

```python
                    if cmd in ("n","s","e","w","ne","nw","se","sw","u","d"):
                        self._state.move_history.append(cmd)
```

Complete the RUNNING task on safe arrival — in `_parse_room`, inside the
`if code := ...` branch after `monsters_present.clear()`:

```python
            if self._state.task.type is TaskType.RUNNING:
                self._state.complete_task()
```

(import `TaskType` at top of bot.py).

- [ ] **Step 5: Run** — `pytest tests/test_run_rules.py -v` then `pytest -q` → green

- [ ] **Step 6: Commit**

```bash
git add src/mmud/automation/run_rules.py src/mmud/bot.py tests/test_run_rules.py
git commit -m "feat: RunDecider — flee when room exceeds monster count/exp limits"
```

---

### Task 5: CombatEngine targeting — priority, order, politeness

**Files:**
- Modify: `src/mmud/combat/combat.py`
- Test: `tests/test_combat.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
from mmud.state.game_state import MonsterSighting


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
```

- [ ] **Step 2: Run to confirm failure** — `pytest tests/test_combat.py -v -k "priority or order or polite"` → FAIL

- [ ] **Step 3: Implement in `src/mmud/combat/combat.py`**

In `__init__` capture the new fields:

```python
        self.attack_order = cfg.attack_order
        self.polite_attacks = cfg.polite_attacks
        self.monster_priority = [p.lower() for p in cfg.monster_priority]
```

Replace the target line in `decide` (currently `target = state.monsters_present[0]...`):

```python
            if self.polite_attacks and state.players_present:
                return None
            target = self._pick_target(state)
            return f"{self.attack_cmd} {target}".strip()
```

Add the method:

```python
    def _pick_target(self, state: GameState) -> str:
        names = state.monster_names()
        if not names:
            return ""
        for wanted in self.monster_priority:
            for name in names:
                if wanted in name.lower():
                    return name
        if self.attack_order == "last":
            return names[-1]
        if self.attack_order == "reverse":
            return names[::-1][0]
        return names[0]
```

- [ ] **Step 4: Run** — `pytest tests/test_combat.py -v` then `pytest -q` → green

- [ ] **Step 5: Commit**

```bash
git add src/mmud/combat/combat.py tests/test_combat.py
git commit -m "feat: combat targeting — monster_priority, attack_order, polite_attacks"
```

---

### Task 6: SpellEngine cast-count limit + weapon swap

**Files:**
- Modify: `src/mmud/automation/spells.py`
- Test: `tests/test_spells.py` (append)

Semantics (after the original): with `max_cast_count = N > 0`, the attack spell
is cast at most N times per encounter. On the (N+1)th opportunity the engine
issues `melee_weapon_cmd` once and stops offering the attack spell (melee at
PRIO_COMBAT takes over). When combat ends, the counter resets and
`cast_weapon_cmd` is issued once before the next encounter's first cast.

- [ ] **Step 1: Write the failing tests**

```python
from mmud.state.game_state import MonsterSighting


def _combat_state():
    gs = GameState()
    gs.set_hp(100, 100); gs.set_mana(100, 100); gs.set_combat(True)
    gs.monsters_present.append(MonsterSighting(name="orc"))
    return gs


def test_cast_count_limit_then_weapon_swap():
    cfg = SpellsConfig(attack="cast zap", max_cast_count=2,
                       melee_weapon_cmd="arm warhammer")
    eng = SpellEngine(cfg)
    gs = _combat_state()
    assert eng.decide(gs) == "cast zap"
    assert eng.decide(gs) == "cast zap"
    assert eng.decide(gs) == "arm warhammer"
    assert eng.decide(gs) is None          # melee decider's turn now


def test_counter_resets_and_swaps_back_after_combat():
    cfg = SpellsConfig(attack="cast zap", max_cast_count=1,
                       cast_weapon_cmd="arm staff", melee_weapon_cmd="arm warhammer")
    eng = SpellEngine(cfg)
    gs = _combat_state()
    assert eng.decide(gs) == "cast zap"
    assert eng.decide(gs) == "arm warhammer"
    gs.set_combat(False); gs.monsters_present.clear()
    assert eng.decide(gs) == "arm staff"   # swap back once, out of combat
    assert eng.decide(gs) is None


def test_unlimited_when_zero():
    cfg = SpellsConfig(attack="cast zap", max_cast_count=0)
    eng = SpellEngine(cfg)
    gs = _combat_state()
    for _ in range(10):
        assert eng.decide(gs) == "cast zap"
```

- [ ] **Step 2: Run to confirm failure** — `pytest tests/test_spells.py -v -k "cast_count or swaps_back or unlimited"` → FAIL

- [ ] **Step 3: Implement in `src/mmud/automation/spells.py`**

In `__init__` add:

```python
        self._attack_casts = 0
        self._swapped_to_melee = False
        self._needs_cast_weapon = False
```

Replace the attack-spell block of `decide`:

```python
        # Attack spell (in combat, takes priority over bless) — with cast limit
        if state.in_combat and self._cfg.attack and state.monsters_present:
            limit = self._cfg.max_cast_count
            if limit <= 0 or self._attack_casts < limit:
                self._attack_casts += 1
                return self._cfg.attack
            if not self._swapped_to_melee and self._cfg.melee_weapon_cmd:
                self._swapped_to_melee = True
                return self._cfg.melee_weapon_cmd
            return None
```

At the start of the out-of-combat path (right before the mana-heal block works
too — put it first in `decide` after the pct computations):

```python
        if not state.in_combat:
            if self._swapped_to_melee:
                self._swapped_to_melee = False
                self._attack_casts = 0
                if self._cfg.cast_weapon_cmd:
                    return self._cfg.cast_weapon_cmd
            self._attack_casts = 0
```

- [ ] **Step 4: Run** — `pytest tests/test_spells.py -v` then `pytest -q` → green

- [ ] **Step 5: Commit**

```bash
git add src/mmud/automation/spells.py tests/test_spells.py
git commit -m "feat: attack-spell cast limit with melee/cast weapon swap"
```

---

### Task 7: Backstab workflow

**Files:**
- Create: `src/mmud/combat/backstab.py`
- Modify: `src/mmud/bot.py`
- Test: `tests/test_backstab.py`

Design: `BackstabEngine` is both a line-monitor (bot feeds it cleaned lines,
like `SafetyMonitor`) and a decider registered at `PRIO_COMBAT - 1` (just above
melee, value 39). Out of combat with a target present it walks
hide → sneak → backstab, one command per stage; stage success/failure is
advanced by server lines. On backstab failure with `run_if_bs_fails`, it asks
the state to run (begins a RUNNING task and returns "flee").

> NOTE: the success/failure regexes below are educated reconstructions —
> record the real server wording in docs/testing-plan.md during live testing,
> same procedure as the Phase 2 condition regexes.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backstab.py
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
```

- [ ] **Step 2: Run to confirm failure** — `pytest tests/test_backstab.py -v` → ModuleNotFoundError

- [ ] **Step 3: Create `src/mmud/combat/backstab.py`**

```python
from __future__ import annotations
import re
from enum import Enum, auto
from mmud.automation.decision import PRIO_FLEE
from mmud.config.schema import CombatConfig, StealthConfig
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType

# Tune against the live server; record real wording in docs/testing-plan.md.
_HIDE_OK_RE = re.compile(r"slip into the shadows|you are hidden", re.IGNORECASE)
_HIDE_FAIL_RE = re.compile(r"fail to hide|can'?t hide", re.IGNORECASE)
_SNEAK_OK_RE = re.compile(r"move silently|begin to sneak", re.IGNORECASE)
_SNEAK_FAIL_RE = re.compile(r"fail to sneak|make a noise", re.IGNORECASE)
_BS_OK_RE = re.compile(r"plant your weapon|backstab.*for \d+", re.IGNORECASE)
_BS_FAIL_RE = re.compile(r"backstab attempt fails|fails? to find an opening", re.IGNORECASE)

_MAX_HIDE_TRIES = 2


class _Stage(Enum):
    IDLE = auto()
    HIDING = auto()      # hide sent, awaiting result
    HIDDEN = auto()
    SNEAKING = auto()
    SNUCK = auto()
    STABBING = auto()
    DONE = auto()        # success/failure handled; melee takes over
    RUN = auto()         # bs failed and run_if_bs_fails


class BackstabEngine:
    """track→hide→sneak→backstab, one command per decide(), line-driven."""

    def __init__(self, combat: CombatConfig, stealth: StealthConfig) -> None:
        self._enabled = combat.backstab
        self._run_if_fails = combat.run_if_bs_fails
        self._hide_cmd = stealth.hide_cmd
        self._sneak_cmd = stealth.sneak_cmd
        self._stage = _Stage.IDLE
        self._hide_tries = 0

    def reset(self) -> None:
        self._stage = _Stage.IDLE
        self._hide_tries = 0

    def on_line(self, line: str) -> None:
        if self._stage is _Stage.HIDING:
            if _HIDE_OK_RE.search(line):
                self._stage = _Stage.HIDDEN
            elif _HIDE_FAIL_RE.search(line):
                self._hide_tries += 1
                self._stage = (_Stage.IDLE if self._hide_tries < _MAX_HIDE_TRIES
                               else _Stage.DONE)
        elif self._stage is _Stage.SNEAKING:
            if _SNEAK_OK_RE.search(line):
                self._stage = _Stage.SNUCK
            elif _SNEAK_FAIL_RE.search(line):
                self._stage = _Stage.DONE
        elif self._stage is _Stage.STABBING:
            if _BS_OK_RE.search(line):
                self._stage = _Stage.DONE
            elif _BS_FAIL_RE.search(line):
                self._stage = _Stage.RUN if self._run_if_fails else _Stage.DONE

    def decide(self, state: GameState) -> str | None:
        if not self._enabled or state.in_combat or not state.monsters_present:
            if not state.monsters_present and not state.in_combat:
                self.reset()        # room cleared: new encounter next time
            return None
        if self._stage is _Stage.IDLE:
            self._stage = _Stage.HIDING
            return self._hide_cmd
        if self._stage is _Stage.HIDDEN:
            self._stage = _Stage.SNEAKING
            return self._sneak_cmd
        if self._stage is _Stage.SNUCK:
            self._stage = _Stage.STABBING
            return f"backstab {state.monster_names()[0]}"
        if self._stage is _Stage.RUN:
            self._stage = _Stage.DONE
            state.begin_task(TaskType.RUNNING, priority=PRIO_FLEE, timeout_s=15.0)
            return "flee"
        return None
```

- [ ] **Step 4: Wire into bot** — `MudBot.__init__` (after the run registration):

```python
        from mmud.combat.backstab import BackstabEngine
        self._backstab = BackstabEngine(self._config.combat, self._config.stealth)
        self._engine.register("backstab", self._backstab, PRIO_COMBAT - 1)
```

In `_process_line` after `self._safety.process_line(clean)` add
`self._backstab.on_line(clean)`. In `_parse_room`'s room-change branch add
`self._backstab.reset()`.

- [ ] **Step 5: Run** — `pytest tests/test_backstab.py -v` then `pytest -q` → green

- [ ] **Step 6: Commit**

```bash
git add src/mmud/combat/backstab.py src/mmud/bot.py tests/test_backstab.py
git commit -m "feat: backstab workflow — hide/sneak/backstab state machine"
```

---

### Task 8: PvP reaction

**Files:**
- Create: `src/mmud/combat/pvp.py`
- Modify: `src/mmud/bot.py`
- Test: `tests/test_pvp.py`

Design: `PvpEngine.check(state)` is called by the bot after room parsing (not a
decider — reaction must outrank everything, and hangup goes through
`SafetyMonitor`). Friends (config.players with `friend=True`) are exempt.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pvp.py
from mmud.combat.pvp import PvpEngine
from mmud.automation.safety import SafetyMonitor
from mmud.config.schema import PvpConfig, PlayerRule, SafetyConfig
from mmud.state.game_state import GameState


def _engine(action="", spell="", friends=()):
    rules = [PlayerRule(name=f, friend=True) for f in friends]
    return PvpEngine(PvpConfig(action=action, spell=spell, flee_rooms=2),
                     rules, SafetyMonitor(SafetyConfig()))


def _state_with(*players):
    gs = GameState()
    gs.players_present = list(players)
    return gs


def test_no_action_configured_ignores():
    eng = _engine()
    assert eng.check(_state_with("Krang")) is None


def test_friend_is_exempt():
    eng = _engine(action="flee", friends=("Krang",))
    assert eng.check(_state_with("Krang")) is None


def test_flee_action():
    eng = _engine(action="flee")
    gs = _state_with("Krang")
    assert eng.check(gs) == "flee"
    assert gs.dequeue() == "flee"      # flee_rooms=2 -> 1 returned + 1 queued


def test_attack_action_with_spell():
    eng = _engine(action="attack", spell="cast zap")
    assert eng.check(_state_with("Krang")) == "cast zap Krang"


def test_hangup_action():
    eng = _engine(action="hangup")
    assert eng.check(_state_with("Krang")) is None
    assert eng._safety.hangup_requested


def test_custom_command_action():
    eng = _engine(action="say please leave")
    assert eng.check(_state_with("Krang")) == "say please leave"


def test_reacts_once_per_player():
    eng = _engine(action="flee")
    gs = _state_with("Krang")
    assert eng.check(gs) == "flee"
    assert eng.check(gs) is None       # same player, no spam
```

- [ ] **Step 2: Run to confirm failure** — `pytest tests/test_pvp.py -v` → ModuleNotFoundError

- [ ] **Step 3: Create `src/mmud/combat/pvp.py`**

```python
from __future__ import annotations
from mmud.automation.safety import SafetyMonitor
from mmud.config.schema import PlayerRule, PvpConfig
from mmud.state.game_state import GameState


class PvpEngine:
    """React to non-friend players in the room per [pvp] config.

    Actions: "" ignore | "flee" | "attack" (cast pvp.spell at them) |
    "hangup" (via SafetyMonitor) | any other string = literal command.
    Reacts once per player name until they leave sight.
    """

    def __init__(self, config: PvpConfig, rules: list[PlayerRule],
                 safety: SafetyMonitor) -> None:
        self._cfg = config
        self._friends = {r.name.lower() for r in rules if r.friend}
        self._safety = safety
        self._reacted: set[str] = set()

    def check(self, state: GameState) -> str | None:
        if not self._cfg.action:
            return None
        present = {p for p in state.players_present
                   if p.lower() not in self._friends}
        self._reacted &= {p.lower() for p in state.players_present}
        for player in sorted(present):
            if player.lower() in self._reacted:
                continue
            self._reacted.add(player.lower())
            return self._react(state, player)
        return None

    def _react(self, state: GameState, player: str) -> str | None:
        action = self._cfg.action
        if action == "flee":
            n = max(1, self._cfg.flee_rooms)
            for _ in range(n - 1):
                state.enqueue("flee")
            return "flee"
        if action == "attack":
            return (f"{self._cfg.spell} {player}".strip()
                    if self._cfg.spell else f"attack {player}")
        if action == "hangup":
            self._safety.request_hangup(f"pvp: {player} in room")
            return None
        return action
```

- [ ] **Step 4: Wire into bot** — `MudBot.__init__` after `self._remote = ...`:

```python
        from mmud.combat.pvp import PvpEngine
        self._pvp = PvpEngine(self._config.pvp, self._config.players, self._safety)
```

In `_parse_room`, after the `players_present` assignment from Task 2:

```python
            if players:
                if cmd := self._pvp.check(self._state):
                    self._state.enqueue(cmd)
```

(Enqueue rather than send directly — the queue decider issues it next line, and
hangup is honored by the existing `run()` check.)

- [ ] **Step 5: Run** — `pytest tests/test_pvp.py -v` then `pytest -q` → green

- [ ] **Step 6: Commit**

```bash
git add src/mmud/combat/pvp.py src/mmud/bot.py tests/test_pvp.py
git commit -m "feat: PvP reaction — flee/attack/hangup/custom on player sighting"
```

---

## Verification

- `pytest -q` — full suite green after every task.
- End-to-end transcript test (append to `tests/test_bot.py` as a final check):
  a transcript with "Also here: 4 orc warriors." and `max_monsters = 3` must
  produce a flee command and a `RUNNING` task; same transcript with
  `max_monsters = 0` must produce an attack.
- Live smoke test (user, per docs/testing-plan.md): verify run rules in a busy
  room; verify backstab stage wording and tune the regexes in
  `src/mmud/combat/backstab.py`; verify `extract_players` against real "Also
  here:" lines (player-name heuristic is the weakest assumption in this phase);
  confirm weapon-swap commands (`arm`/`wield` syntax) for your server.
