# Phase 6: Multi-hop Pathfinding, Resync, Doors, Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single-hop path lookup and bulk-enqueue looping with a real room graph (stitched from the 1,198-file `.MP` corpus + live-learned exits), BFS multi-hop navigation with error codes, a step-cursor `TravelDecider` that issues one move per arrival and **resyncs from history** instead of restarting, door handling, and hidden-exit search/roam.

**Architecture:** `RoomGraph` holds multi-destination adjacency (`from_hex → command → {to_hex,…}`) built directly from the `.MP` corpus at startup (text sources are never imported into the store) plus learned exits from the Phase 7 `GameStore`. `find_path` BFS returns a `RouteStep` list (command + expected-destination set). `TravelDecider` at `PRIO_TRAVEL` executes routes one step per arrival signal ("Obvious exits:" line), validating each arrival against the step's expected set and resyncing the cursor when reality disagrees. `LoopRunner` becomes a thin adapter that arms looping routes. Doors and search/roam are line-driven helpers in the established monitor/decider patterns.

**Tech Stack:** Python 3.11+, stdlib only. Transcript-tested via `make_transcript_bot`.

**Prerequisites:**
1. Phase 7 (Game DB Store) complete — `GameStore.add_exit/exits` exist.
2. `pytest -q` green.

**Validated facts (probed against the real corpus — pin these, do not re-derive):**
- Edge rule: `step[i].hex_id --command--> step[i+1].hex_id` for consecutive steps (confirmed: first-step hex == from-room hex in 298/299 paths), **plus the final edge** `last_step.hex_id --cmd--> rooms[to_code].hex_id`. Without final edges the graph fragments (481-node islands); with them it is **one component**.
- Pinned graph numbers (1,198 `.MP` files + ROOMS.MD): **4,510 nodes, 14,035 distinct (from,cmd,to) triples, 9,002 (from,cmd) pairs of which 2,482 have MULTIPLE destinations**, single undirected component, **4,501 nodes directed-reachable from AALY hex `CAB00180`**.
- Multi-destination pairs are real data (e.g. `B4300014 e → 6 different hexes`) — adjacency must be set-valued and arrival checks must accept ANY recorded destination, with resync as fallback.
- Command quirks in the corpus: `go path` (21×, send literally) and bracket annotations `w[search w]` (20×) = "do the bracketed command first, then move" — expand at execution time, store raw in the graph.
- ROOMS.MD: 543 rooms / 553 hex ids; `Room.hex_id`/`hex_id2` map code↔hex (`src/mmud/data/rooms.py`). Only ~12% of graph nodes are named rooms — **arrival in unnamed rooms is signaled by the "Obvious exits:" line**, not by room-name detection.

---

## File Map

```
src/mmud/
  navigation/graph.py        NEW — RoomGraph, NavStatus, RouteStep, find_path
  parser/exits_parser.py     NEW — "Obvious exits:" → command list
  automation/travel.py       NEW — TravelDecider (PRIO_TRAVEL) + annotation expansion
  automation/doors.py        NEW — DoorMonitor (open/bash/pick)
  automation/search.py       NEW — SearchDecider (PRIO_SEARCH) + roam
  automation/loop_runner.py  REWRITE — thin adapter over TravelDecider
  state/game_state.py        MODIFY — current_hex, last_exits
  config/schema.py           MODIFY — NavigationConfig additions
  config/loader.py           MODIFY
  events.py                  MODIFY — TravelResynced, TravelEnded
  bot.py                     MODIFY — graph, travel wiring, exits/door hooks, @goto multi-hop
tests/
  test_graph.py              NEW
  test_exits_parser.py       NEW
  test_travel.py             NEW
  test_doors.py              NEW
  test_search.py             NEW
  test_loop_runner.py        REWRITE
  test_config.py             MODIFY
  test_bot.py                MODIFY — multi-hop e2e
characters/example.toml      MODIFY
```

---

### Task 1: RoomGraph

**Files:**
- Create: `src/mmud/navigation/graph.py`
- Test: `tests/test_graph.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_graph.py
import pytest
from mmud.data.paths import load_mp_file, GamePath, PathStep
from mmud.data.rooms import load_rooms, Room
from mmud.navigation.graph import RoomGraph, NavStatus


@pytest.fixture(scope="module")
def corpus_graph(data_dir):
    rooms = load_rooms(data_dir / "ROOMS.MD")
    paths = [p for p in (load_mp_file(f) for f in sorted(data_dir.glob("*.MP")))
             if p and p.steps]
    return RoomGraph.from_paths(paths, rooms)


def test_corpus_graph_pinned_shape(corpus_graph):
    assert corpus_graph.node_count() == 4510
    assert corpus_graph.edge_count() == 14035          # distinct (from,cmd,to)
    assert corpus_graph.multi_dest_pairs() == 2482     # (from,cmd) with >1 dest


def test_corpus_reachability_from_aaly(corpus_graph):
    assert len(corpus_graph.reachable("CAB00180")) == 4501


def test_find_path_on_corpus(corpus_graph, data_dir):
    rooms = load_rooms(data_dir / "ROOMS.MD")
    src = rooms["AALY"].hex_id.upper()
    # pick any other named, reachable room
    dst = next(r.hex_id.upper() for c, r in sorted(rooms.items())
               if c != "AALY" and r.hex_id.upper() in corpus_graph.reachable(src))
    result = corpus_graph.find_path(src, dst)
    assert result.status is NavStatus.OK
    assert len(result.steps) >= 1
    assert all(s.command for s in result.steps)
    # every step's expected set is non-empty and the last step can land on dst
    assert dst in result.steps[-1].expect


def test_unknown_start_and_dest():
    g = RoomGraph()
    g.add_edge("AAAA0001", "n", "BBBB0002")
    assert g.find_path("ZZZZ9999", "BBBB0002").status is NavStatus.UNKNOWN_START
    assert g.find_path("AAAA0001", "ZZZZ9999").status is NavStatus.UNKNOWN_DEST


def test_no_path_in_disconnected_graph():
    g = RoomGraph()
    g.add_edge("AAAA0001", "n", "BBBB0002")
    g.add_edge("CCCC0003", "s", "DDDD0004")   # separate island
    assert g.find_path("AAAA0001", "DDDD0004").status is NavStatus.NO_PATH


def test_learned_exit_bridges_islands():
    g = RoomGraph()
    g.add_edge("AAAA0001", "n", "BBBB0002")
    g.add_edge("CCCC0003", "s", "DDDD0004")
    g.add_edge("BBBB0002", "e", "CCCC0003")   # e.g. from store.exits()
    r = g.find_path("AAAA0001", "DDDD0004")
    assert r.status is NavStatus.OK
    assert [s.command for s in r.steps] == ["n", "e", "s"]
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_graph.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `src/mmud/navigation/graph.py`**

```python
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from mmud.data.paths import GamePath
from mmud.data.rooms import Room


class NavStatus(Enum):
    OK = auto()
    UNKNOWN_START = auto()
    UNKNOWN_DEST = auto()
    NO_PATH = auto()


@dataclass
class RouteStep:
    command: str              # raw command (may carry a [bracket] annotation)
    expect: frozenset[str]    # ALL recorded destinations of (from, command)
    chosen: str               # the destination BFS planned through


@dataclass
class NavResult:
    status: NavStatus
    steps: list[RouteStep]


class RoomGraph:
    """Directed room graph over .MP hex ids. Adjacency is multi-destination:
    the corpus records the same (room, command) landing in different hexes
    (2,482 of 9,002 pairs) — arrival validation must accept any of them."""

    def __init__(self) -> None:
        self._adj: dict[str, dict[str, set[str]]] = {}

    # ---- construction ------------------------------------------------------

    def add_edge(self, from_hex: str, command: str, to_hex: str) -> None:
        a, c, b = from_hex.upper(), command.lower(), to_hex.upper()
        self._adj.setdefault(a, {}).setdefault(c, set()).add(b)
        self._adj.setdefault(b, {})   # destination is a node even if no exits

    @classmethod
    def from_paths(cls, paths: list[GamePath], rooms: dict[str, Room]) -> "RoomGraph":
        g = cls()
        for p in paths:
            hexes = [s.hex_id.upper() for s in p.steps]
            for i, step in enumerate(p.steps):
                if i + 1 < len(p.steps):
                    g.add_edge(hexes[i], step.command, hexes[i + 1])
                else:
                    # final edge: last command leads to the destination room
                    room = rooms.get(p.to_code.upper())
                    if room and room.hex_id:
                        g.add_edge(hexes[i], step.command, room.hex_id)
        return g

    def add_learned(self, exits: list[tuple[str, str, str]]) -> None:
        for from_hex, cmd, to_hex in exits:
            self.add_edge(from_hex, cmd, to_hex)

    # ---- introspection (pinned in tests) ------------------------------------

    def node_count(self) -> int:
        return len(self._adj)

    def edge_count(self) -> int:
        return sum(len(dests) for cmds in self._adj.values()
                   for dests in cmds.values())

    def multi_dest_pairs(self) -> int:
        return sum(1 for cmds in self._adj.values()
                   for dests in cmds.values() if len(dests) > 1)

    def reachable(self, start_hex: str) -> set[str]:
        start = start_hex.upper()
        if start not in self._adj:
            return set()
        seen = {start}
        frontier = deque([start])
        while frontier:
            node = frontier.popleft()
            for dests in self._adj[node].values():
                for nxt in dests:
                    if nxt not in seen:
                        seen.add(nxt)
                        frontier.append(nxt)
        return seen

    # ---- pathfinding ---------------------------------------------------------

    def find_path(self, from_hex: str, to_hex: str) -> NavResult:
        src, dst = from_hex.upper(), to_hex.upper()
        if src not in self._adj:
            return NavResult(NavStatus.UNKNOWN_START, [])
        if dst not in self._adj:
            return NavResult(NavStatus.UNKNOWN_DEST, [])
        # BFS; parent[node] = (prev_node, command)
        parent: dict[str, tuple[str, str]] = {src: ("", "")}
        frontier = deque([src])
        while frontier:
            node = frontier.popleft()
            if node == dst:
                break
            for cmd, dests in self._adj[node].items():
                for nxt in dests:
                    if nxt not in parent:
                        parent[nxt] = (node, cmd)
                        frontier.append(nxt)
        if dst not in parent:
            return NavResult(NavStatus.NO_PATH, [])
        # reconstruct
        steps: list[RouteStep] = []
        node = dst
        while node != src:
            prev, cmd = parent[node]
            steps.append(RouteStep(command=cmd,
                                   expect=frozenset(self._adj[prev][cmd]),
                                   chosen=node))
            node = prev
        steps.reverse()
        return NavResult(NavStatus.OK, steps)
```

- [ ] **Step 4: Run tests** — `pytest tests/test_graph.py -v` → 6 passed
(corpus fixture parses 1,198 files once per module — ~1s).

- [ ] **Step 5: Commit**

```bash
git add src/mmud/navigation/graph.py tests/test_graph.py
git commit -m "feat: RoomGraph — multi-destination room graph from .MP corpus, BFS with error codes"
```

---

### Task 2: Exits parser

**Files:**
- Create: `src/mmud/parser/exits_parser.py`
- Test: `tests/test_exits_parser.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_exits_parser.py
from mmud.parser.exits_parser import parse_exits


def test_basic_exits():
    assert parse_exits("Obvious exits: north, east") == ["n", "e"]


def test_diagonals_and_vertical():
    assert parse_exits("Obvious exits: northeast, southwest, up, down") == \
        ["ne", "sw", "u", "d"]


def test_none():
    assert parse_exits("Obvious exits: none") == []


def test_non_exit_line_returns_none():
    assert parse_exits("You notice a rusty sword here.") is None
    assert parse_exits("") is None


def test_case_and_trailing_period():
    assert parse_exits("obvious exits: West, South.") == ["w", "s"]
```

- [ ] **Step 2: Run to confirm failure** — ModuleNotFoundError

- [ ] **Step 3: Create `src/mmud/parser/exits_parser.py`**

```python
from __future__ import annotations
import re

_EXITS_RE = re.compile(r"^Obvious exits:\s*(.+?)\.?$", re.IGNORECASE)

_DIRECTIONS = {
    "north": "n", "south": "s", "east": "e", "west": "w",
    "northeast": "ne", "northwest": "nw", "southeast": "se", "southwest": "sw",
    "up": "u", "down": "d",
    # already-short forms pass through
    "n": "n", "s": "s", "e": "e", "w": "w",
    "ne": "ne", "nw": "nw", "se": "se", "sw": "sw", "u": "u", "d": "d",
}


def parse_exits(line: str) -> list[str] | None:
    """Parse an 'Obvious exits:' line into short movement commands.

    Returns None when the line is not an exits line; [] for 'none'.
    This line doubles as the ARRIVAL signal for unnamed rooms (88% of the
    graph) — TravelDecider advances on it.
    """
    m = _EXITS_RE.match(line.strip())
    if not m:
        return None
    body = m.group(1).strip().lower()
    if body == "none":
        return []
    out = []
    for raw in re.split(r",\s*|\s+and\s+", body):
        cmd = _DIRECTIONS.get(raw.strip())
        if cmd:
            out.append(cmd)
    return out
```

- [ ] **Step 4: Run** — `pytest tests/test_exits_parser.py -v` → 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/mmud/parser/exits_parser.py tests/test_exits_parser.py
git commit -m "feat: exits parser — Obvious exits line to movement commands"
```

---

### Task 3: GameState position fields + config additions

**Files:**
- Modify: `src/mmud/state/game_state.py`, `src/mmud/config/schema.py`,
  `src/mmud/config/loader.py`, `characters/example.toml`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_phase6_navigation_config(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[navigation]
auto_search = true
search_max = 2
roam = true
bash_doors = true
""")
    cfg = load_config(p)
    assert cfg.navigation.auto_search is True
    assert cfg.navigation.search_max == 2
    assert cfg.navigation.roam is True
    assert cfg.navigation.bash_doors is True


def test_phase6_navigation_defaults():
    cfg = load_config(None)
    assert cfg.navigation.auto_search is False
    assert cfg.navigation.search_max == 3
    assert cfg.navigation.roam is False
    assert cfg.navigation.bash_doors is False
```

- [ ] **Step 2: Run to confirm failure** — AttributeError

- [ ] **Step 3: Implement**

`GameState.__init__` (after `move_history`):

```python
        self.current_hex: str = ""        # room hex id when known
        self.last_exits: list[str] = []   # commands from the last exits line
```

`NavigationConfig` additions (schema.py):

```python
    auto_search: bool = False   # search for hidden exits in each new room
    search_max: int = 3         # search attempts per room
    roam: bool = False          # wander random exits when idle
    bash_doors: bool = False    # bash closed doors when open fails
```

Loader `navigation` block gains the four `n.get(...)` lines with those defaults.
`example.toml` `[navigation]` block gains the four keys with the schema comments.

- [ ] **Step 4: Run + commit**

Run: `pytest tests/test_config.py -v` → green

```bash
git add src/mmud/state/game_state.py src/mmud/config/ characters/example.toml tests/test_config.py
git commit -m "feat: phase-6 navigation config + hex position fields"
```

---

### Task 4: TravelDecider — step cursor, arrival, resync

**Files:**
- Create: `src/mmud/automation/travel.py`
- Modify: `src/mmud/events.py`
- Test: `tests/test_travel.py`

Semantics:
- `decide()` issues ONE step when a route is armed and no move is in flight;
  bracket annotations expand (`w[search w]` → send `search w`, queue `w`);
  `stealth.auto_sneak` prepends the sneak command the same way.
- The bot signals arrival on every exits line via `on_arrival(state, seen_hex)`
  where `seen_hex` is the named-room hex observed since the move ("" for the
  88% unnamed rooms).
- Arrival with `seen_hex` in the current step's `expect` set (or unknown "") →
  cursor advances, `current_hex` becomes `seen_hex or step.chosen`.
- Arrival with a hex NOT in `expect` → **resync**: scan the whole route for a
  step whose `expect` contains it; found → cursor jumps past that step and a
  `TravelResynced` event is emitted; not found → route ends (`TravelEnded("lost")`).
- `on_move_failed()` (nav-failure line) retries the same step up to 2 times,
  then ends the route (`TravelEnded("blocked")`).
- Loop mode restarts the cursor and increments `lap`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_travel.py
from mmud.automation.travel import TravelDecider, expand_annotated
from mmud.config.schema import ItemsConfig, StealthConfig
from mmud.events import GameEventBus, TravelResynced, TravelEnded
from mmud.navigation.graph import RouteStep
from mmud.state.game_state import GameState


def _step(cmd, *expect):
    return RouteStep(command=cmd, expect=frozenset(expect), chosen=expect[0])


def _decider(bus=None):
    return TravelDecider(ItemsConfig(), StealthConfig(),
                         bus or GameEventBus())


def test_expand_annotated():
    assert expand_annotated("n") == ["n"]
    assert expand_annotated("w[search w]") == ["search w", "w"]
    assert expand_annotated("go path") == ["go path"]


def test_one_step_per_arrival():
    d = _decider()
    gs = GameState()
    d.set_route([_step("n", "BBBB0002"), _step("e", "CCCC0003")])
    assert d.decide(gs) == "n"
    assert d.decide(gs) is None              # in flight: wait for arrival
    d.on_arrival(gs, "")                     # unnamed room: trust expectation
    assert gs.current_hex == "BBBB0002"
    assert d.decide(gs) == "e"
    d.on_arrival(gs, "CCCC0003")
    assert not d.active                      # route complete
    assert gs.current_hex == "CCCC0003"


def test_annotation_queues_move_after_search():
    d = _decider()
    gs = GameState()
    d.set_route([_step("w[search w]", "BBBB0002")])
    assert d.decide(gs) == "search w"
    assert gs.dequeue() == "w"               # queued for the next line


def test_sneak_prefix():
    d = TravelDecider(ItemsConfig(), StealthConfig(auto_sneak=True, sneak_cmd="sneak"),
                      GameEventBus())
    gs = GameState()
    d.set_route([_step("n", "BBBB0002")])
    assert d.decide(gs) == "sneak"
    assert gs.dequeue() == "n"


def test_resync_jumps_cursor():
    received = []
    bus = GameEventBus()
    bus.subscribe(TravelResynced, received.append)
    d = _decider(bus)
    gs = GameState()
    d.set_route([_step("n", "BBBB0002"), _step("e", "CCCC0003"),
                 _step("s", "DDDD0004")])
    d.decide(gs)
    d.on_arrival(gs, "CCCC0003")             # overshot: landed after step 2
    assert received and received[0].to_step == 2
    assert d.decide(gs) == "s"               # cursor resumed at step 3


def test_lost_ends_route():
    received = []
    bus = GameEventBus()
    bus.subscribe(TravelEnded, received.append)
    d = _decider(bus)
    gs = GameState()
    d.set_route([_step("n", "BBBB0002")])
    d.decide(gs)
    d.on_arrival(gs, "ZZZZ9999")             # nowhere on the route
    assert not d.active
    assert received[0].reason == "lost"


def test_move_failed_retries_then_ends():
    received = []
    bus = GameEventBus()
    bus.subscribe(TravelEnded, received.append)
    d = _decider(bus)
    gs = GameState()
    d.set_route([_step("n", "BBBB0002")])
    assert d.decide(gs) == "n"
    d.on_move_failed()
    assert d.decide(gs) == "n"               # retry 1
    d.on_move_failed()
    assert d.decide(gs) == "n"               # retry 2
    d.on_move_failed()
    assert not d.active
    assert received[0].reason == "blocked"


def test_loop_mode_restarts_and_counts_laps():
    d = _decider()
    gs = GameState()
    d.set_route([_step("n", "BBBB0002")], loop=True)
    d.decide(gs); d.on_arrival(gs, "")
    assert d.lap == 1
    assert d.decide(gs) == "n"               # restarted


def test_encumbrance_gate():
    from mmud.state.inventory import Inventory
    d = TravelDecider(ItemsConfig(dont_go_heavy=True), StealthConfig(),
                      GameEventBus())
    gs = GameState()
    gs.inventory = Inventory(encumbrance_level="heavy")
    d.set_route([_step("n", "BBBB0002")])
    assert d.decide(gs) is None              # halted while heavy
```

- [ ] **Step 2: Run to confirm failure** — ModuleNotFoundError

- [ ] **Step 3: Add events** (`events.py`, before `GameEventBus`):

```python
@dataclass
class TravelResynced:
    from_step: int
    to_step: int

@dataclass
class TravelEnded:
    reason: str   # "arrived" | "lost" | "blocked" | "stopped"
```

- [ ] **Step 4: Create `src/mmud/automation/travel.py`**

```python
from __future__ import annotations
import re
from mmud.config.schema import ItemsConfig, StealthConfig
from mmud.events import GameEventBus, TravelResynced, TravelEnded
from mmud.navigation.graph import RouteStep
from mmud.state.game_state import GameState

_ANNOTATION_RE = re.compile(r"^(.*?)\[(.+)\]$")
_MAX_RETRIES = 2


def expand_annotated(command: str) -> list[str]:
    """'w[search w]' -> ['search w', 'w']; plain commands pass through."""
    m = _ANNOTATION_RE.match(command.strip())
    if m and m.group(1).strip():
        return [m.group(2).strip(), m.group(1).strip()]
    return [command.strip()]


class TravelDecider:
    """PRIO_TRAVEL slot: execute a Route one step per arrival, with resync.

    Replaces bulk-enqueue path following. The bot feeds arrival signals
    (exits lines) via on_arrival() and movement failures via on_move_failed().
    """

    def __init__(self, items: ItemsConfig, stealth: StealthConfig,
                 bus: GameEventBus) -> None:
        self._items = items
        self._stealth = stealth
        self._bus = bus
        self._steps: list[RouteStep] = []
        self._cursor = 0
        self._in_flight = False
        self._retries = 0
        self._loop = False
        self.lap = 0

    # ---- route control ------------------------------------------------------

    @property
    def active(self) -> bool:
        return bool(self._steps)

    def set_route(self, steps: list[RouteStep], loop: bool = False) -> None:
        self._steps = list(steps)
        self._cursor = 0
        self._in_flight = False
        self._retries = 0
        self._loop = loop
        self.lap = 0

    def clear(self, reason: str = "stopped") -> None:
        if self._steps:
            self._bus.post(TravelEnded(reason=reason))
        self._steps = []
        self._in_flight = False

    # ---- decider ------------------------------------------------------------

    def decide(self, state: GameState) -> str | None:
        if not self._steps or self._in_flight:
            return None
        level = state.inventory.encumbrance_level
        if ((self._items.dont_go_heavy and level == "heavy")
                or (self._items.dont_go_medium and level in ("medium", "heavy"))):
            return None
        step = self._steps[self._cursor]
        cmds = expand_annotated(step.command)
        if self._stealth.auto_sneak:
            cmds = [self._stealth.sneak_cmd] + cmds
        for extra in cmds[1:]:
            state.enqueue(extra)
        self._in_flight = True
        return cmds[0]

    # ---- signals from the bot -------------------------------------------------

    def on_arrival(self, state: GameState, seen_hex: str = "") -> None:
        if not self._steps or not self._in_flight:
            return
        self._in_flight = False
        self._retries = 0
        step = self._steps[self._cursor]
        seen = seen_hex.upper()
        if seen and seen not in step.expect:
            # reality disagrees: resync against the whole route
            for idx, other in enumerate(self._steps):
                if seen in other.expect:
                    self._bus.post(TravelResynced(from_step=self._cursor + 1,
                                                  to_step=idx + 1))
                    state.current_hex = seen
                    self._cursor = idx + 1
                    self._finish_if_done()
                    return
            state.current_hex = seen
            self.clear(reason="lost")
            return
        state.current_hex = seen or step.chosen
        self._cursor += 1
        self._finish_if_done()

    def on_move_failed(self) -> None:
        if not self._steps:
            return
        self._in_flight = False
        self._retries += 1
        if self._retries > _MAX_RETRIES:
            self.clear(reason="blocked")

    def retry_current(self) -> None:
        """A door handler cleared the obstacle: re-send the same step free."""
        self._in_flight = False
        self._retries = 0

    def _finish_if_done(self) -> None:
        if self._cursor < len(self._steps):
            return
        if self._loop:
            self._cursor = 0
            self.lap += 1
        else:
            self._bus.post(TravelEnded(reason="arrived"))
            self._steps = []
```

- [ ] **Step 5: Run** — `pytest tests/test_travel.py -v` → 9 passed

- [ ] **Step 6: Commit**

```bash
git add src/mmud/automation/travel.py src/mmud/events.py tests/test_travel.py
git commit -m "feat: TravelDecider — step-cursor route execution with history resync"
```

---

### Task 5: LoopRunner rewrite as adapter + bot travel wiring

**Files:**
- Rewrite: `src/mmud/automation/loop_runner.py`
- Rewrite: `tests/test_loop_runner.py`
- Modify: `src/mmud/bot.py`

The bulk-enqueue contract is GONE: `start()` arms a looping route on the shared
`TravelDecider`; one move is issued per arrival by the engine. The old
`on_nav_failure` clear-and-restart is replaced by `travel.on_move_failed()`.

- [ ] **Step 1: Rewrite `tests/test_loop_runner.py`** (full replacement —
the old enqueue-contract tests no longer describe the system):

```python
# tests/test_loop_runner.py
from mmud.automation.loop_runner import LoopRunner, route_for_path
from mmud.automation.travel import TravelDecider
from mmud.config.schema import ItemsConfig, NavigationConfig, StealthConfig
from mmud.data.paths import GamePath, PathStep
from mmud.data.rooms import Room
from mmud.events import GameEventBus
from mmud.state.game_state import GameState


def _loop(code: str, hexes_cmds: list[tuple[str, str]]) -> GamePath:
    steps = [PathStep(hex_id=h, command=c) for h, c in hexes_cmds]
    return GamePath(from_code=code, from_region="", from_name="",
                    to_code=code, to_region="", to_name="", npc="", steps=steps)


ROOMS = {"HOME": Room(code="HOME", hex_id="AAAA0001", hex_id2="",
                      flags=(0, 0, 0), region="", name="The Home Room")}


def _runner(path, gs=None):
    gs = gs or GameState()
    travel = TravelDecider(ItemsConfig(), StealthConfig(), GameEventBus())
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), [path], ROOMS, travel)
    return runner, travel, gs


def test_route_for_path_expectations():
    path = _loop("HOME", [("AAAA0001", "n"), ("BBBB0002", "s")])
    steps = route_for_path(path, ROOMS)
    assert [s.command for s in steps] == ["n", "s"]
    assert steps[0].expect == frozenset({"BBBB0002"})
    assert steps[1].expect == frozenset({"AAAA0001"})   # final edge -> home


def test_start_arms_looping_route():
    path = _loop("HOME", [("AAAA0001", "n"), ("BBBB0002", "s")])
    runner, travel, gs = _runner(path)
    runner.start()
    assert runner.running
    assert travel.decide(gs) == "n"          # one step, not a bulk enqueue
    assert gs.dequeue() is None
    travel.on_arrival(gs, "")
    assert travel.decide(gs) == "s"
    travel.on_arrival(gs, "")
    assert runner.lap == 1                   # looped
    assert travel.decide(gs) == "n"


def test_stop_clears_route():
    path = _loop("HOME", [("AAAA0001", "n")])
    runner, travel, gs = _runner(path)
    runner.start()
    runner.stop()
    assert not runner.running
    assert travel.decide(gs) is None


def test_missing_path_does_not_arm():
    travel = TravelDecider(ItemsConfig(), StealthConfig(), GameEventBus())
    runner = LoopRunner(NavigationConfig(loop_path="XXXX"), [], ROOMS, travel)
    runner.start()
    assert runner._path is None
    assert not travel.active
```

- [ ] **Step 2: Run to confirm failure** — imports fail (`route_for_path` missing)

- [ ] **Step 3: Rewrite `src/mmud/automation/loop_runner.py`**

```python
from __future__ import annotations
from mmud.automation.travel import TravelDecider
from mmud.config.schema import NavigationConfig
from mmud.data.paths import GamePath
from mmud.data.rooms import Room
from mmud.navigation.graph import RouteStep


def route_for_path(path: GamePath, rooms: dict[str, Room]) -> list[RouteStep]:
    """A recorded .MP path -> RouteSteps. Expected hex after step i is
    step[i+1].hex_id; the final step lands on the destination room's hex."""
    steps: list[RouteStep] = []
    hexes = [s.hex_id.upper() for s in path.steps]
    for i, s in enumerate(path.steps):
        if i + 1 < len(path.steps):
            dest = hexes[i + 1]
        else:
            room = rooms.get(path.to_code.upper())
            dest = room.hex_id.upper() if room and room.hex_id else ""
        expect = frozenset({dest}) if dest else frozenset()
        steps.append(RouteStep(command=s.command, expect=expect, chosen=dest))
    return steps


class LoopRunner:
    """Thin adapter: arms a looping route on the shared TravelDecider."""

    def __init__(self, nav_config: NavigationConfig, paths: list[GamePath],
                 rooms: dict[str, Room], travel: TravelDecider) -> None:
        self._nav = nav_config
        self._rooms = rooms
        self._travel = travel
        self._running = False
        self._path = self._find_path(paths)

    def _find_path(self, paths: list[GamePath]) -> GamePath | None:
        name = self._nav.loop_path.upper()
        if not name:
            return None
        for p in paths:
            if p.from_code.upper() == name and p.to_code.upper() == name:
                return p
        if len(name) == 8:
            fc, tc = name[:4], name[4:]
            for p in paths:
                if p.from_code.upper() == fc and p.to_code.upper() == tc:
                    return p
        return None

    def start(self) -> None:
        if self._path is None:
            return
        self._travel.set_route(route_for_path(self._path, self._rooms), loop=True)
        self._running = True

    def stop(self) -> None:
        self._running = False
        self._travel.clear(reason="stopped")

    def on_nav_failure(self) -> None:
        self._travel.on_move_failed()

    @property
    def running(self) -> bool:
        return self._running and self._travel.active

    @property
    def lap(self) -> int:
        return self._travel.lap
```

(Encumbrance gating and sneak-prefixing now live in `TravelDecider` — the
`items_config`/`stealth_config` constructor params are gone.)

- [ ] **Step 4: Bot wiring** (`bot.py`):

1. `__init__`: store rooms + travel, register the decider, build the graph lazily:

```python
        self._rooms = rooms or {}
        from mmud.automation.travel import TravelDecider
        self._travel = TravelDecider(self._config.items, self._config.stealth,
                                     event_bus or GameEventBus())
        self._engine.register("travel", self._travel, PRIO_TRAVEL)
        self._graph = None        # built on first use (corpus parse ~1s)
        self._last_seen_hex = ""
```

(import `PRIO_TRAVEL`; NOTE: pass the same bus object used for `self._bus` — do
this AFTER `self._bus = event_bus` or reuse the variable.)

2. Graph accessor + learned exits:

```python
    def _room_graph(self):
        if self._graph is None:
            from mmud.navigation.graph import RoomGraph
            paths = list(self._navigator._paths.values())
            self._graph = RoomGraph.from_paths(paths, self._rooms)
            if self._store is not None:
                self._graph.add_learned(self._store.exits())
        return self._graph
```

3. `_parse_room`: when a named room is detected, record its hex:

```python
            self._state.set_room(code)
            room = self._rooms.get(code)
            self._last_seen_hex = room.hex_id.upper() if room and room.hex_id else ""
            self._state.current_hex = self._last_seen_hex or self._state.current_hex
```

4. New `_parse_exits` called from `_process_line` (after `_parse_room`):

```python
    def _parse_exits(self, line: str) -> None:
        from mmud.parser.exits_parser import parse_exits
        exits = parse_exits(line)
        if exits is None:
            return
        self._state.last_exits = exits
        self._travel.on_arrival(self._state, self._last_seen_hex)
        self._last_seen_hex = ""
```

5. `_parse_nav_failure` routes to travel (keep loop_runner call for compat):

```python
    def _parse_nav_failure(self, line: str) -> None:
        if _NAV_FAIL_RE.search(line):
            if self._travel.active:
                self._travel.on_move_failed()
            elif self._loop_runner and self._loop_runner.running:
                self._loop_runner.on_nav_failure()
```

6. `toggle_loop`/`start_loop` construct the new adapter:
`LoopRunner(self._config.navigation, paths, self._rooms, self._travel)`
(drop the stealth/items/state/bus args; `stop_all()` additionally calls
`self._travel.clear()`).

- [ ] **Step 5: Run** — `pytest -q` → green. Existing bot tests that asserted
loop behavior through the queue may need the same one-step-per-arrival shape —
fix them per the new contract (the engine drains travel one command per line).

- [ ] **Step 6: Commit**

```bash
git add src/mmud/automation/loop_runner.py src/mmud/bot.py tests/
git commit -m "feat: step-cursor travel wiring — LoopRunner adapter over TravelDecider"
```

---

### Task 6: Multi-hop @goto + learned-exit recording

**Files:**
- Modify: `src/mmud/bot.py`
- Test: `tests/test_bot.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bot.py`:

```python
from mmud.data.rooms import Room as _Room
from mmud.data.paths import GamePath as _GamePath, PathStep as _PathStep

_NAV_ROOMS = {
    "HOME": _Room(code="HOME", hex_id="AAAA0001", hex_id2="", flags=(0, 0, 0),
                  region="", name="The Home Room"),
    "FARR": _Room(code="FARR", hex_id="CCCC0003", hex_id2="", flags=(0, 0, 0),
                  region="", name="The Far Room"),
}
_NAV_PATH = _GamePath(from_code="HOME", from_region="", from_name="",
                      to_code="FARR", to_region="", to_name="", npc="",
                      steps=[_PathStep(hex_id="AAAA0001", command="n"),
                             _PathStep(hex_id="BBBB0002", command="e")])


@pytest.mark.asyncio
async def test_multihop_goto_walks_route():
    bot = make_transcript_bot(
        ["Obvious exits: north\n",          # arrival signal -> first move
         "Obvious exits: east\n",           # unnamed middle room -> second move
         "The Far Room\n",                  # named arrival
         "Obvious exits: west\n"],
        rooms=_NAV_ROOMS)
    bot._navigator._paths[("HOME", "FARR")] = _NAV_PATH
    bot._state.set_room("HOME")
    bot._state.current_hex = "AAAA0001"
    msg = bot.navigate_to_room("FARR")
    assert "2 steps" in msg
    await bot.run()
    assert bot._conn.sent == ["n", "e"]
    assert bot._state.current_hex == "CCCC0003"
    assert not bot._travel.active            # arrived


def test_goto_unknown_destination():
    bot = make_transcript_bot([], rooms=_NAV_ROOMS)
    bot._state.set_room("HOME")
    bot._state.current_hex = "AAAA0001"
    assert "unknown" in bot.navigate_to_room("ZZZZ").lower()


@pytest.mark.asyncio
async def test_observed_movement_learns_exit(tmp_path):
    config = MudConfig()
    config.learning.enabled = True
    config.learning.store_path = str(tmp_path / "g.json")
    bot = make_transcript_bot(
        ["The Home Room\n", "Obvious exits: north\n"], config=config,
        rooms=_NAV_ROOMS)
    from mmud.data.store import GameStore
    bot._store = GameStore(tmp_path / "g.json")
    # a manual move was sent before this room appeared
    bot._state.current_hex = "BBBB0002"
    bot._pending_move = "s"
    await bot.run()
    assert ("BBBB0002", "s", "AAAA0001") in bot._store.exits()
```

- [ ] **Step 2: Run to confirm failure** — `navigate_to_room` still single-hop;
`_pending_move` missing.

- [ ] **Step 3: Rewrite `navigate_to_room` in `bot.py`**

```python
    def navigate_to_room(self, to_code: str) -> str:
        """Multi-hop navigate to a 4-letter room code via the room graph."""
        from mmud.navigation.graph import NavStatus
        dest = self._rooms.get(to_code.upper())
        if dest is None or not dest.hex_id:
            return f"Unknown destination room: {to_code.upper()}"
        src_hex = self._state.current_hex
        if not src_hex and self._state.current_room:
            room = self._rooms.get(self._state.current_room)
            src_hex = room.hex_id.upper() if room and room.hex_id else ""
        if not src_hex:
            return "Current room unknown — move around first to establish position"
        result = self._room_graph().find_path(src_hex, dest.hex_id)
        if result.status is NavStatus.UNKNOWN_START:
            return f"Current room {src_hex} not in the path corpus"
        if result.status is NavStatus.UNKNOWN_DEST:
            return f"Unknown destination room: {to_code.upper()}"
        if result.status is NavStatus.NO_PATH:
            return f"No known route to {to_code.upper()}"
        while self._state.dequeue() is not None:
            pass
        self._travel.set_route(result.steps)
        return f"Navigating to {to_code.upper()} ({len(result.steps)} steps)"
```

- [ ] **Step 4: Learned-exit recording** — track the last *manual* movement:
in `run()`'s send path, where `move_history` is appended, also set
`self._pending_move = cmd` (initialize `self._pending_move = ""` in `__init__`).
In `_parse_room`'s named-room branch, after `current_hex` is updated:

```python
            if (self._store is not None and self._pending_move
                    and self._state.current_hex
                    and prev_hex and prev_hex != self._state.current_hex):
                self._store.add_exit(prev_hex, self._pending_move,
                                     self._state.current_hex)
            self._pending_move = ""
```

where `prev_hex` is captured at the top of the branch
(`prev_hex = self._state.current_hex` before overwriting). Learned exits feed
`_room_graph()` on next build and persist via the Phase 7 store.

- [ ] **Step 5: Run** — `pytest -q` → green

- [ ] **Step 6: Commit**

```bash
git add src/mmud/bot.py tests/test_bot.py
git commit -m "feat: multi-hop @goto via room graph; observed-movement exit learning"
```

---

### Task 7: Doors

**Files:**
- Create: `src/mmud/automation/doors.py`
- Modify: `src/mmud/bot.py`
- Test: `tests/test_doors.py`

> Door message wording is reconstructed — tune against the live server and
> record in docs/testing-plan.md (same procedure as Phase 2).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_doors.py
from mmud.automation.doors import DoorMonitor
from mmud.config.schema import NavigationConfig


def test_closed_door_opens():
    m = DoorMonitor(NavigationConfig())
    cmds = m.handle("The door is closed.", last_move="w")
    assert cmds == ["open w"]


def test_locked_door_picks_when_able():
    m = DoorMonitor(NavigationConfig(can_pick_locks=True))
    assert m.handle("The door is locked.", last_move="n") == ["pick n"]


def test_locked_door_bashes_when_configured():
    m = DoorMonitor(NavigationConfig(bash_doors=True))
    assert m.handle("The door is locked.", last_move="n") == ["bash n"]


def test_locked_door_no_capability_gives_up():
    m = DoorMonitor(NavigationConfig())
    assert m.handle("The door is locked.", last_move="n") == []


def test_non_door_line_returns_none():
    m = DoorMonitor(NavigationConfig())
    assert m.handle("You can't go that way!", last_move="n") is None
```

- [ ] **Step 2: Run to confirm failure** — ModuleNotFoundError

- [ ] **Step 3: Create `src/mmud/automation/doors.py`**

```python
from __future__ import annotations
import re
from mmud.config.schema import NavigationConfig

# Tune against the live server; record real wording in docs/testing-plan.md.
_CLOSED_RE = re.compile(r"(?:the )?door is closed|it'?s closed", re.IGNORECASE)
_LOCKED_RE = re.compile(r"(?:the )?door is locked|it'?s locked", re.IGNORECASE)


class DoorMonitor:
    """Turns door-blocked lines into open/pick/bash commands for the last move.

    Returns: list of commands to send (may be empty = give up), or None when
    the line is not door-related.
    """

    def __init__(self, config: NavigationConfig) -> None:
        self._cfg = config

    def handle(self, line: str, last_move: str) -> list[str] | None:
        if not last_move:
            return None
        if _LOCKED_RE.search(line):
            if self._cfg.can_pick_locks:
                return [f"pick {last_move}"]
            if self._cfg.bash_doors:
                return [f"bash {last_move}"]
            return []
        if _CLOSED_RE.search(line):
            return [f"open {last_move}"]
        return None
```

- [ ] **Step 4: Bot wiring** — in `__init__`:
`from mmud.automation.doors import DoorMonitor` /
`self._doors = DoorMonitor(self._config.navigation)`. In `_process_line`
(before `_parse_nav_failure`):

```python
        if self._travel.active or (self._loop_runner and self._loop_runner.running):
            door_cmds = self._doors.handle(clean, self._pending_move)
            if door_cmds is not None:
                for c in door_cmds:
                    self._state.enqueue(c)
                if door_cmds:
                    self._travel.retry_current()   # re-send the move after opening
                else:
                    self._travel.on_move_failed()  # can't open: normal failure path
```

- [ ] **Step 5: Run** — `pytest tests/test_doors.py -v` then `pytest -q` → green

- [ ] **Step 6: Commit**

```bash
git add src/mmud/automation/doors.py src/mmud/bot.py tests/test_doors.py
git commit -m "feat: door handling — open/pick/bash blocked moves during travel"
```

---

### Task 8: Search + roam decider

**Files:**
- Create: `src/mmud/automation/search.py`
- Modify: `src/mmud/bot.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_search.py
from mmud.automation.search import SearchDecider
from mmud.automation.decision import PRIO_SEARCH
from mmud.config.schema import NavigationConfig
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType


def _state(hex_id="AAAA0001", exits=("n", "e")):
    gs = GameState()
    gs.current_hex = hex_id
    gs.last_exits = list(exits)
    return gs


def test_auto_search_searches_new_room():
    d = SearchDecider(NavigationConfig(auto_search=True, search_max=2),
                      now=lambda: 5.0)
    gs = _state()
    assert d.decide(gs) == "search"
    assert gs.task.type is TaskType.SEARCHING
    assert gs.task.priority == PRIO_SEARCH


def test_search_max_per_room():
    d = SearchDecider(NavigationConfig(auto_search=True, search_max=2),
                      now=lambda: 5.0)
    gs = _state()
    for _ in range(2):
        assert d.decide(gs) == "search"
        gs.complete_task()
    assert d.decide(gs) is None              # exhausted for this room
    gs.current_hex = "BBBB0002"
    assert d.decide(gs) == "search"          # fresh room, fresh budget


def test_roam_cycles_exits():
    d = SearchDecider(NavigationConfig(roam=True), now=lambda: 5.0)
    gs = _state(exits=("n", "e"))
    assert d.decide(gs) == "n"
    assert d.decide(gs) == "e"
    assert d.decide(gs) == "n"               # round-robin, no randomness


def test_disabled_does_nothing():
    d = SearchDecider(NavigationConfig(), now=lambda: 5.0)
    assert d.decide(_state()) is None


def test_quiet_in_combat():
    d = SearchDecider(NavigationConfig(auto_search=True), now=lambda: 5.0)
    gs = _state()
    gs.set_combat(True)
    assert d.decide(gs) is None
```

- [ ] **Step 2: Run to confirm failure** — ModuleNotFoundError

- [ ] **Step 3: Create `src/mmud/automation/search.py`**

```python
from __future__ import annotations
import time
from typing import Callable
from mmud.automation.decision import PRIO_SEARCH
from mmud.config.schema import NavigationConfig
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType

SEARCH_TIMEOUT_S = 10.0


class SearchDecider:
    """PRIO_SEARCH slot (bottom of the chain): hidden-exit search and roaming.

    Only reached when every higher slot (combat, travel, …) passed — i.e. the
    bot is otherwise idle in a room.
    """

    def __init__(self, config: NavigationConfig,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._cfg = config
        self._now = now
        self._searched: dict[str, int] = {}   # hex -> attempts
        self._roam_idx = 0

    def decide(self, state: GameState) -> str | None:
        if state.in_combat or not state.current_hex:
            return None
        if self._cfg.auto_search:
            done = self._searched.get(state.current_hex, 0)
            if done < self._cfg.search_max:
                self._searched[state.current_hex] = done + 1
                state.begin_task(TaskType.SEARCHING, priority=PRIO_SEARCH,
                                 timeout_s=SEARCH_TIMEOUT_S, now=self._now())
                return "search"
        if self._cfg.roam and state.last_exits:
            cmd = state.last_exits[self._roam_idx % len(state.last_exits)]
            self._roam_idx += 1
            return cmd
        return None
```

- [ ] **Step 4: Bot wiring** — in `__init__` (after the travel registration):

```python
        from mmud.automation.search import SearchDecider
        self._engine.register("search", SearchDecider(self._config.navigation),
                              PRIO_SEARCH)
```

(import `PRIO_SEARCH`). Complete the `SEARCHING` task in `_parse_exits` — a new
exits line after a search means the search round-tripped:

```python
        if self._state.task.type is TaskType.SEARCHING:
            self._state.complete_task()
```

- [ ] **Step 5: Run** — `pytest -q` → green. NOTE: `SearchDecider` is gated off
by default config (`auto_search=False`, `roam=False`) so existing transcript
tests stay silent.

- [ ] **Step 6: Commit**

```bash
git add src/mmud/automation/search.py src/mmud/bot.py tests/test_search.py
git commit -m "feat: hidden-exit search + roam decider at PRIO_SEARCH"
```

---

## Verification

- `pytest -q` — full suite green after every task.
- Graph pins re-checkable any time:
  ```bash
  python3 -c "
  import pathlib
  from mmud.data.rooms import load_rooms
  from mmud.data.paths import load_mp_file
  from mmud.navigation.graph import RoomGraph
  d = pathlib.Path('extractions/mm103s.exe.extracted/45DAD/Default')
  g = RoomGraph.from_paths([p for p in (load_mp_file(f) for f in sorted(d.glob('*.MP'))) if p and p.steps], load_rooms(d/'ROOMS.MD'))
  print(g.node_count(), g.edge_count(), g.multi_dest_pairs(), len(g.reachable('CAB00180')))"
  ```
  → `4510 14035 2482 4501`.
- Live test (user, per docs/testing-plan.md): confirm the real "Obvious exits:"
  wording (THE arrival signal — the phase's most load-bearing regex), door
  closed/locked lines, `search` command response, and that `@goto` walks a
  short multi-hop route with at least one unnamed intermediate room. Watch a
  full loop lap for a resync event after a deliberate manual move mid-loop.
- Deliberately deferred: weighted/door-aware path costs, boat/level-gate edge
  attributes (the original's error codes for these need live observation of
  gated rooms — add as edge metadata when encountered), roam biasing.
