# Phase 5: Inventory, Loot, Cash — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the bot an inventory model (parsed from `inv` output), auto-loot after kills (items + per-denomination coins), auto-equip from the item DB, and encumbrance-gated travel — wiring the long-dormant `items.*` config.

**Architecture:** A stateful `InventoryParser` accumulates multi-line `inv` output into an `Inventory` snapshot stored on `GameState` with a `dirty` flag; a `RefreshDecider` at `PRIO_REFRESH` issues `inv` whenever dirty. A `LootMonitor` (SafetyMonitor pattern) tracks gettable things seen on the ground; `GetDecider` at `PRIO_ITEMS` picks them up per config. `ItemDB` wraps the rewritten `load_items()` for equip slots; `EquipDecider` at `PRIO_EQUIP` wears/wields better gear. Encumbrance gates `LoopRunner` stepping.

**Tech Stack:** Python 3.11+, stdlib only. Transcript-tested via `make_transcript_bot`.

**Prerequisites:**
1. MDB2 parser rewrite complete (`load_items()` returns 667 active items).
2. Phase 4 complete (uses `MonsterSighting`, `players_present`; `PRIO_*` slots as registered there).
3. `pytest -q` green.

> **Server-wording caveat:** the `inv` output and ground-item line formats below
> are educated reconstructions. Record the real wording in docs/testing-plan.md
> during live testing and tune the regexes — same procedure as Phase 2.

---

## File Map

```
src/mmud/
  parser/inventory_parser.py  NEW — multi-line inv parser
  state/inventory.py          NEW — Inventory snapshot + wealth math
  state/game_state.py         MODIFY — inventory field + dirty flag
  data/item_db.py             NEW — ItemDB over load_items()
  automation/items.py         NEW — LootMonitor + GetDecider + coin rules
  automation/equip.py         NEW — EquipDecider
  automation/loop_runner.py   MODIFY — encumbrance gate
  config/schema.py            MODIFY — ItemsConfig additions
  config/loader.py            MODIFY — parse new fields
  bot.py                      MODIFY — wire parser/deciders/@wealth
tests/
  test_inventory_parser.py    NEW
  test_inventory.py           NEW
  test_item_db.py             NEW
  test_items_automation.py    NEW
  test_equip.py               NEW
  test_loop_runner.py         MODIFY — encumbrance gate
  test_config.py              MODIFY
characters/example.toml       MODIFY
```

---

### Task 1: InventoryParser

**Files:**
- Create: `src/mmud/parser/inventory_parser.py`
- Test: `tests/test_inventory_parser.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_inventory_parser.py
from mmud.parser.inventory_parser import InventoryParser

INV_LINES = [
    "You are carrying a torch, a brass key, 2 iron rations.",
    "You are wearing chainmail armour, a leather helm.",
    "Wealth: 153 copper farthings",
    "Encumbrance: 45/120 - Light [37%]",
]


def _parse(lines):
    p = InventoryParser()
    result = None
    for line in lines:
        result = p.feed(line) or result
    return result


def test_full_inv_block():
    inv = _parse(INV_LINES)
    assert inv is not None
    assert "torch" in inv.carried
    assert ("iron rations", 2) in [(i, c) for i, c in inv.carried_counts.items()]
    assert "chainmail armour" in inv.worn
    assert inv.coins["copper"] == 153
    assert inv.encumbrance_pct == 37
    assert inv.encumbrance_level == "light"


def test_incomplete_block_returns_none():
    p = InventoryParser()
    assert p.feed("You are carrying a torch.") is None   # no encumbrance line yet


def test_multiline_carrying_wrap():
    inv = _parse([
        "You are carrying a torch, a brass key,",
        "  2 iron rations, a healing potion.",
        "Encumbrance: 10/120 - None [8%]",
    ])
    assert "healing potion" in inv.carried


def test_no_wealth_line():
    inv = _parse(["You are carrying a torch.",
                  "Encumbrance: 10/120 - None [8%]"])
    assert inv.coins == {}


def test_unrelated_lines_ignored():
    p = InventoryParser()
    assert p.feed("[HP=100/100]:") is None
    assert p.feed("An orc swings at you!") is None
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_inventory_parser.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `src/mmud/parser/inventory_parser.py`**

```python
from __future__ import annotations
import re
from mmud.state.inventory import Inventory

_CARRYING_RE = re.compile(r"^You are carrying\s+(.*)$", re.IGNORECASE)
_WEARING_RE = re.compile(r"^You are wearing\s+(.*)$", re.IGNORECASE)
_WEALTH_RE = re.compile(
    r"^Wealth:\s+(\d+)\s+(copper|silver|gold|platinum|runic)", re.IGNORECASE)
_ENCUMBRANCE_RE = re.compile(
    r"^Encumbrance:\s+(\d+)/(\d+)\s*-\s*(\w+)\s*\[(\d+)%\]", re.IGNORECASE)
_COUNT_ITEM_RE = re.compile(r"^(\d+)\s+(.*)$")
_ARTICLE_RE = re.compile(r"^(?:a|an|the|some)\s+", re.IGNORECASE)
_COIN_RE = re.compile(
    r"^(\d+)\s+(copper|silver|gold|platinum|runic)\b", re.IGNORECASE)


def _split_items(text: str) -> list[str]:
    return [part.strip() for part in re.split(r",\s*|\s+and\s+", text.rstrip(". "))
            if part.strip()]


class InventoryParser:
    """Accumulates the multi-line `inv` response; returns the completed
    Inventory when the Encumbrance line arrives, else None."""

    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._carried: dict[str, int] = {}
        self._worn: list[str] = []
        self._coins: dict[str, int] = {}
        self._section: str | None = None   # "carrying" | "wearing" | None

    def feed(self, line: str) -> Inventory | None:
        line = line.rstrip()
        if m := _CARRYING_RE.match(line):
            self._section = "carrying"
            self._add_items(m.group(1))
            return None
        if m := _WEARING_RE.match(line):
            self._section = "wearing"
            self._worn.extend(_ARTICLE_RE.sub("", i).lower()
                              for i in _split_items(m.group(1)))
            return None
        if m := _WEALTH_RE.match(line):
            self._coins[m.group(2).lower()] = int(m.group(1))
            self._section = None
            return None
        if m := _ENCUMBRANCE_RE.match(line):
            inv = Inventory(
                carried_counts=dict(self._carried),
                worn=list(self._worn),
                coins=dict(self._coins),
                encumbrance_pct=int(m.group(4)),
                encumbrance_level=m.group(3).lower(),
            )
            self._reset()
            return inv
        # continuation of a wrapped carrying/wearing list (starts with spaces)
        if self._section and line.startswith(" "):
            if self._section == "carrying":
                self._add_items(line)
            else:
                self._worn.extend(_ARTICLE_RE.sub("", i).lower()
                                  for i in _split_items(line))
            return None
        self._section = None
        return None

    def _add_items(self, text: str) -> None:
        for raw in _split_items(text):
            if cm := _COIN_RE.match(raw):
                self._coins[cm.group(2).lower()] = int(cm.group(1))
                continue
            count = 1
            if m := _COUNT_ITEM_RE.match(raw):
                count, raw = int(m.group(1)), m.group(2)
            name = _ARTICLE_RE.sub("", raw).strip().lower()
            if name:
                self._carried[name] = self._carried.get(name, 0) + count
```

- [ ] **Step 4: Tests need `Inventory` first** — Task 2 defines it; to keep this
task self-contained, create `src/mmud/state/inventory.py` now with just the
dataclass (Task 2 adds the rest):

```python
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Inventory:
    carried_counts: dict[str, int] = field(default_factory=dict)
    worn: list[str] = field(default_factory=list)
    coins: dict[str, int] = field(default_factory=dict)   # denomination -> count
    encumbrance_pct: int = 0
    encumbrance_level: str = "none"   # none|light|medium|heavy

    @property
    def carried(self) -> list[str]:
        return list(self.carried_counts)
```

- [ ] **Step 5: Run** — `pytest tests/test_inventory_parser.py -v` → 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/mmud/parser/inventory_parser.py src/mmud/state/inventory.py tests/test_inventory_parser.py
git commit -m "feat: InventoryParser — multi-line inv output to Inventory snapshot"
```

---

### Task 2: Inventory on GameState + RefreshDecider

**Files:**
- Modify: `src/mmud/state/inventory.py`, `src/mmud/state/game_state.py`, `src/mmud/bot.py`
- Test: `tests/test_inventory.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_inventory.py
from mmud.state.inventory import Inventory, RefreshDecider, WEALTH_RATES
from mmud.automation.decision import PRIO_REFRESH
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType


def test_wealth_total_copper_equivalent():
    inv = Inventory(coins={"copper": 50, "silver": 2, "gold": 1})
    # 50 + 2*10 + 1*100
    assert inv.wealth_total() == 170


def test_wealth_rates_cover_all_denominations():
    assert set(WEALTH_RATES) == {"copper", "silver", "gold", "platinum", "runic"}


def test_gamestate_has_dirty_inventory():
    gs = GameState()
    assert gs.inventory_dirty is True        # unknown at start -> refresh
    assert isinstance(gs.inventory, Inventory)


def test_refresh_decider_issues_inv_when_dirty():
    gs = GameState()
    d = RefreshDecider(now=lambda: 10.0)
    assert d.decide(gs) == "inv"
    assert gs.task.type is TaskType.WAITING
    assert gs.task.priority == PRIO_REFRESH


def test_refresh_decider_quiet_when_clean():
    gs = GameState()
    gs.inventory_dirty = False
    assert RefreshDecider(now=lambda: 10.0).decide(gs) is None


def test_refresh_decider_quiet_in_combat():
    gs = GameState()
    gs.set_combat(True)
    assert RefreshDecider(now=lambda: 10.0).decide(gs) is None
```

- [ ] **Step 2: Run to confirm failure** — `pytest tests/test_inventory.py -v` → ImportError

- [ ] **Step 3: Extend `src/mmud/state/inventory.py`**

Append:

```python
import time
from typing import Callable
from mmud.automation.decision import PRIO_REFRESH
from mmud.state.tasks import TaskType

# Copper-equivalent exchange rates. VERIFY against the live server
# (MajorMUD: 10 copper = 1 silver, 10 silver = 1 gold, 10 gold = 1 platinum,
# 10 platinum = 1 runic) and record in docs/testing-plan.md.
WEALTH_RATES = {"copper": 1, "silver": 10, "gold": 100,
                "platinum": 1000, "runic": 10000}

REFRESH_TIMEOUT_S = 5.0


def _wealth_total(self) -> int:
    return sum(WEALTH_RATES.get(d, 0) * n for d, n in self.coins.items())

Inventory.wealth_total = _wealth_total


class RefreshDecider:
    """PRIO_REFRESH slot: issue `inv` when the inventory snapshot is stale.

    Begins a WAITING task so the chain below is pinned until the parsed
    response arrives (bot completes the task) or the timeout aborts it.
    """

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now

    def decide(self, state) -> str | None:
        if state.in_combat or not state.inventory_dirty:
            return None
        state.begin_task(TaskType.WAITING, priority=PRIO_REFRESH,
                         timeout_s=REFRESH_TIMEOUT_S, now=self._now())
        return "inv"
```

(Define `wealth_total` as a normal method on the dataclass instead of the
assignment trick if you prefer — either passes; the method form is cleaner:
move it inside the `Inventory` class body.)

- [ ] **Step 4: GameState fields** — in `GameState.__init__`:

```python
        from mmud.state.inventory import Inventory
        self.inventory: Inventory = Inventory()
        self.inventory_dirty: bool = True
```

- [ ] **Step 5: Wire into bot** — `MudBot.__init__`:

```python
        from mmud.parser.inventory_parser import InventoryParser
        from mmud.state.inventory import RefreshDecider
        self._inv_parser = InventoryParser()
        self._engine.register("refresh", RefreshDecider(), PRIO_REFRESH)
```

In `_process_line` (after `self._parse_vitals(clean)`):

```python
        if inv := self._inv_parser.feed(clean):
            self._state.inventory = inv
            self._state.inventory_dirty = False
            if self._state.task.type is TaskType.WAITING:
                self._state.complete_task()
```

Mark dirty on combat end — in `_parse_combat_exit` inside the branch:
`self._state.inventory_dirty = True` (loot may have dropped). Also mark dirty
in remote/get/drop paths added by Task 4.

- [ ] **Step 6: Run** — `pytest tests/test_inventory.py -v` then `pytest -q` → green

- [ ] **Step 7: Commit**

```bash
git add src/mmud/state/inventory.py src/mmud/state/game_state.py src/mmud/bot.py tests/test_inventory.py
git commit -m "feat: Inventory on GameState + RefreshDecider issuing inv when dirty"
```

---

### Task 3: ItemDB

**Files:**
- Create: `src/mmud/data/item_db.py`
- Test: `tests/test_item_db.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_item_db.py
from mmud.data.item_db import ItemDB


def _db(data_dir):
    return ItemDB.from_file(data_dir / "ITEMS.MD")


def test_find_known_item(data_dir):
    db = _db(data_dir)
    item = db.find("a statue of a bard")
    assert item is not None


def test_find_strips_article_and_case(data_dir):
    db = _db(data_dir)
    a = db.find("A Statue Of A Bard".lower())
    b = db.find("statue of a bard")
    assert a is not None and b is not None and a.record_id == b.record_id


def test_unknown_returns_none(data_dir):
    assert _db(data_dir).find("zzz frobnitz") is None


def test_equip_slot_exposed(data_dir):
    db = _db(data_dir)
    item = db.find("a statue of a bard")
    assert isinstance(item.equip_slot, int)
```

- [ ] **Step 2: Run to confirm failure** — `pytest tests/test_item_db.py -v` → ModuleNotFoundError

- [ ] **Step 3: Create `src/mmud/data/item_db.py`**

```python
from __future__ import annotations
import pathlib
from mmud.data.binary import Item, load_items
from mmud.data.monster_db import normalize


class ItemDB:
    """Name-indexed item lookup over ITEMS.MD records."""

    def __init__(self, items: list[Item]) -> None:
        self._by_name: dict[str, Item] = {}
        for it in items:
            key = normalize(it.name)
            if key and key not in self._by_name:
                self._by_name[key] = it

    @classmethod
    def from_file(cls, path: pathlib.Path) -> "ItemDB":
        return cls(load_items(path))

    def find(self, name: str) -> Item | None:
        key = normalize(name)
        if key in self._by_name:
            return self._by_name[key]
        if key.endswith("s") and key[:-1] in self._by_name:
            return self._by_name[key[:-1]]
        return None
```

- [ ] **Step 4: Run** — `pytest tests/test_item_db.py -v` → 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/mmud/data/item_db.py tests/test_item_db.py
git commit -m "feat: ItemDB — name-indexed item lookup over ITEMS.MD"
```

---

### Task 4: Loot — ground tracking, GetDecider, coin rules, config

**Files:**
- Create: `src/mmud/automation/items.py`
- Modify: `src/mmud/config/schema.py`, `src/mmud/config/loader.py`, `src/mmud/bot.py`, `characters/example.toml`
- Test: `tests/test_items_automation.py`, `tests/test_config.py` (append)

- [ ] **Step 1: Config first (failing test)**

Append to `tests/test_config.py`:

```python
def test_phase5_items_config(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[items]
max_coins = 500
max_wealth = 20000
min_wealth = 1000
""")
    cfg = load_config(p)
    assert cfg.items.max_coins == 500
    assert cfg.items.max_wealth == 20000
    assert cfg.items.min_wealth == 1000


def test_phase5_items_defaults():
    cfg = load_config(None)
    assert cfg.items.max_coins == 0      # 0 = no limit
    assert cfg.items.max_wealth == 0
    assert cfg.items.min_wealth == 0
```

Run: `pytest tests/test_config.py -v -k phase5` → AttributeError. Then append to
`ItemsConfig` in schema.py:

```python
    max_coins: int = 0     # drop loose coins above this per denomination (0 = off)
    max_wealth: int = 0    # bank when copper-equiv wealth exceeds (Phase 8 consumes)
    min_wealth: int = 0    # withdraw when below (Phase 8 consumes)
```

and the matching three `it.get(...)` lines in loader.py. Run again → pass.

- [ ] **Step 2: Write the failing automation tests**

```python
# tests/test_items_automation.py
from mmud.automation.items import LootMonitor, GetDecider
from mmud.automation.decision import PRIO_ITEMS
from mmud.config.schema import ItemsConfig
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType


def test_loot_monitor_sees_ground_items():
    m = LootMonitor()
    gs = GameState()
    m.process_line("You notice a rusty sword here.", gs)
    assert "rusty sword" in gs.ground_items


def test_loot_monitor_sees_coins():
    m = LootMonitor()
    gs = GameState()
    m.process_line("You notice 23 copper farthings here.", gs)
    assert ("copper", 23) in gs.ground_coins.items()


def test_loot_monitor_ignores_monsters():
    m = LootMonitor()
    gs = GameState()
    m.process_line("You notice an orc here.", gs)
    assert gs.ground_items == []


def test_get_decider_picks_up_item():
    gs = GameState()
    gs.ground_items.append("rusty sword")
    d = GetDecider(ItemsConfig(auto_get=True), now=lambda: 5.0)
    assert d.decide(gs) == "get rusty sword"
    assert gs.task.type is TaskType.GETTING
    assert gs.task.priority == PRIO_ITEMS
    assert "rusty sword" not in gs.ground_items   # claimed


def test_get_decider_respects_auto_get_off():
    gs = GameState()
    gs.ground_items.append("rusty sword")
    assert GetDecider(ItemsConfig(auto_get=False), now=lambda: 5.0).decide(gs) is None


def test_get_decider_collects_configured_coins():
    gs = GameState()
    gs.ground_coins["copper"] = 23
    d = GetDecider(ItemsConfig(auto_cash=True, collect_copper=True), now=lambda: 5.0)
    assert d.decide(gs) == "get copper"
    assert "copper" not in gs.ground_coins


def test_get_decider_skips_unwanted_denomination():
    gs = GameState()
    gs.ground_coins["runic"] = 1
    d = GetDecider(ItemsConfig(auto_cash=True, collect_runic=False), now=lambda: 5.0)
    assert d.decide(gs) is None


def test_get_decider_skips_in_combat():
    gs = GameState()
    gs.set_combat(True)
    gs.ground_items.append("rusty sword")
    assert GetDecider(ItemsConfig(auto_get=True), now=lambda: 5.0).decide(gs) is None


def test_ungettable_marking():
    gs = GameState()
    d = GetDecider(ItemsConfig(auto_get=True), now=lambda: 5.0)
    gs.ground_items.append("fountain")
    assert d.decide(gs) == "get fountain"
    d.mark_ungettable("fountain")
    gs.ground_items.append("fountain")
    assert d.decide(gs) is None
```

Run: `pytest tests/test_items_automation.py -v` → ModuleNotFoundError

- [ ] **Step 3: GameState ground fields** — in `GameState.__init__`:

```python
        self.ground_items: list[str] = []
        self.ground_coins: dict[str, int] = {}
```

Clear both next to `monsters_present.clear()` on room change in bot.py.

- [ ] **Step 4: Create `src/mmud/automation/items.py`**

```python
from __future__ import annotations
import re
import time
from typing import Callable
from mmud.automation.decision import PRIO_ITEMS
from mmud.config.schema import ItemsConfig
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType

GET_TIMEOUT_S = 5.0

# "You notice a rusty sword here." / "You notice 23 copper farthings here."
# Tune against the live server (docs/testing-plan.md).
_NOTICE_RE = re.compile(r"^You notice (.+?) here\.?$", re.IGNORECASE)
_COIN_RE = re.compile(
    r"^(\d+)\s+(copper|silver|gold|platinum|runic)\b", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"^(?:a|an|the|some)\s+", re.IGNORECASE)
# Monster-ish entries are excluded by a simple blocklist of leading articles
# plus the monster wordlist room_parser uses; ground items are usually
# inanimate. Heuristic: monsters are tracked by room_parser already, so only
# treat entries room_parser did NOT claim as monsters.
_CANT_GET_RE = re.compile(r"you can'?t (?:get|take|pick up)", re.IGNORECASE)


class LootMonitor:
    """Watches 'You notice ... here.' lines and records gettable things."""

    def __init__(self, is_monster: Callable[[str], bool] | None = None) -> None:
        # is_monster lets the bot pass room_parser knowledge in; default: none
        self._is_monster = is_monster or (lambda name: False)

    def process_line(self, line: str, state: GameState) -> None:
        m = _NOTICE_RE.match(line)
        if not m:
            return
        for raw in re.split(r",\s*|\s+and\s+", m.group(1)):
            raw = raw.strip()
            if not raw:
                continue
            if cm := _COIN_RE.match(raw):
                state.ground_coins[cm.group(2).lower()] = int(cm.group(1))
                continue
            name = _ARTICLE_RE.sub("", raw).lower()
            if name and not self._is_monster(name):
                state.ground_items.append(name)


class GetDecider:
    """PRIO_ITEMS slot: pick up coins then items, one GET per decide()."""

    def __init__(self, config: ItemsConfig,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._cfg = config
        self._now = now
        self._ungettable: set[str] = set()

    def mark_ungettable(self, name: str) -> None:
        self._ungettable.add(name.lower())

    def decide(self, state: GameState) -> str | None:
        if state.in_combat:
            return None
        if self._cfg.auto_cash:
            for denom in list(state.ground_coins):
                if getattr(self._cfg, f"collect_{denom}", False):
                    del state.ground_coins[denom]
                    self._begin(state)
                    return f"get {denom}"
                del state.ground_coins[denom]   # unwanted: forget it
        if self._cfg.auto_get:
            while state.ground_items:
                name = state.ground_items.pop(0)
                if name in self._ungettable:
                    continue
                self._begin(state)
                return f"get {name}"
        return None

    def _begin(self, state: GameState) -> None:
        state.begin_task(TaskType.GETTING, priority=PRIO_ITEMS,
                         timeout_s=GET_TIMEOUT_S, now=self._now())
        state.inventory_dirty = True
```

- [ ] **Step 5: Wire into bot** — `MudBot.__init__`:

```python
        from mmud.automation.items import LootMonitor, GetDecider, _CANT_GET_RE
        self._loot = LootMonitor(
            is_monster=lambda name: self._monster_db.find(name) is not None)
        self._get_decider = GetDecider(self._config.items)
        self._engine.register("items", self._get_decider, PRIO_ITEMS)
```

In `_process_line` after the backstab hook: `self._loot.process_line(clean, self._state)`.
Handle un-gettable + GETTING completion (new method, called from `_process_line`):

```python
    def _parse_get_results(self, line: str) -> None:
        if self._state.task.type is not TaskType.GETTING:
            return
        if _CANT_GET_RE.search(line):
            if last := self._state.task.payload.get("item"):
                self._get_decider.mark_ungettable(last)
            self._state.abort_task()
        elif line.lower().startswith("you took") or line.lower().startswith("you get"):
            self._state.complete_task()
```

(To make the payload available, change `GetDecider._begin` to accept the item
name: `payload={"item": name}` — update `_begin(state, name)` call sites and
the signature accordingly.)

- [ ] **Step 6: Run** — `pytest tests/test_items_automation.py -v` then `pytest -q` → green

- [ ] **Step 7: example.toml** — document `max_coins`/`max_wealth`/`min_wealth`
under the existing `[items]` block with the schema comments.

- [ ] **Step 8: Commit**

```bash
git add src/mmud/automation/items.py src/mmud/state/game_state.py src/mmud/config/ src/mmud/bot.py tests/ characters/example.toml
git commit -m "feat: loot tracking + GetDecider — auto-get items and configured coins"
```

---

### Task 5: EquipDecider

**Files:**
- Create: `src/mmud/automation/equip.py`
- Modify: `src/mmud/bot.py`
- Test: `tests/test_equip.py`

Scope (deliberately minimal — megamud's full slot-comparison needs live data):
equip carried items that the ItemDB marks as equippable (equip_slot > 0) and
that are not already worn. One command per decide; `EQUIPPING` task prevents
spam; bot completes on "You are now wearing/wielding" lines.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_equip.py
from mmud.automation.equip import EquipDecider
from mmud.automation.decision import PRIO_EQUIP
from mmud.data.item_db import ItemDB
from mmud.data.binary import Item
from mmud.state.game_state import GameState
from mmud.state.inventory import Inventory
from mmud.state.tasks import TaskType


def _item(name, slot):
    return Item(record_id=1, name=name, description="", suffix="",
                item_type=1, equip_slot=slot, ac_or_dmg=0, weight=0,
                value=0, extra_stat1=0, extra_stat2=0, flags=0x40000000)


def _decider(items, auto=True):
    return EquipDecider(ItemDB(items), enabled=auto, now=lambda: 7.0)


def test_equips_carried_equippable():
    gs = GameState()
    gs.inventory = Inventory(carried_counts={"leather helm": 1})
    d = _decider([_item("leather helm", slot=3)])
    assert d.decide(gs) == "equip leather helm"
    assert gs.task.type is TaskType.EQUIPPING
    assert gs.task.priority == PRIO_EQUIP


def test_skips_already_worn():
    gs = GameState()
    gs.inventory = Inventory(carried_counts={"leather helm": 1},
                             worn=["leather helm"])
    d = _decider([_item("leather helm", slot=3)])
    assert d.decide(gs) is None


def test_skips_non_equippable():
    gs = GameState()
    gs.inventory = Inventory(carried_counts={"iron rations": 2})
    d = _decider([_item("iron rations", slot=0)])
    assert d.decide(gs) is None


def test_disabled():
    gs = GameState()
    gs.inventory = Inventory(carried_counts={"leather helm": 1})
    d = _decider([_item("leather helm", slot=3)], auto=False)
    assert d.decide(gs) is None


def test_skips_in_combat():
    gs = GameState()
    gs.set_combat(True)
    gs.inventory = Inventory(carried_counts={"leather helm": 1})
    assert _decider([_item("leather helm", slot=3)]).decide(gs) is None
```

- [ ] **Step 2: Run to confirm failure** — `pytest tests/test_equip.py -v` → ModuleNotFoundError

- [ ] **Step 3: Create `src/mmud/automation/equip.py`**

```python
from __future__ import annotations
import time
from typing import Callable
from mmud.automation.decision import PRIO_EQUIP
from mmud.data.item_db import ItemDB
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType

EQUIP_TIMEOUT_S = 5.0


class EquipDecider:
    """PRIO_EQUIP slot: equip carried, equippable, not-yet-worn items."""

    def __init__(self, item_db: ItemDB, enabled: bool = True,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._db = item_db
        self._enabled = enabled
        self._now = now
        self._failed: set[str] = set()   # cursed/failed items: don't retry

    def mark_failed(self, name: str) -> None:
        self._failed.add(name.lower())

    def decide(self, state: GameState) -> str | None:
        if not self._enabled or state.in_combat:
            return None
        worn = set(state.inventory.worn)
        for name in state.inventory.carried:
            if name in worn or name in self._failed:
                continue
            rec = self._db.find(name)
            if rec is None or rec.equip_slot <= 0:
                continue
            state.begin_task(TaskType.EQUIPPING, priority=PRIO_EQUIP,
                             timeout_s=EQUIP_TIMEOUT_S,
                             payload={"item": name}, now=self._now())
            state.inventory_dirty = True
            return f"equip {name}"
        return None
```

- [ ] **Step 4: Wire into bot** — `MudBot.__init__` (item_db built like monster_db):

```python
        from mmud.data.item_db import ItemDB
        items_md = (data_dir / "ITEMS.MD") if data_dir else None
        self._item_db = (ItemDB.from_file(items_md)
                         if items_md and items_md.exists() else ItemDB([]))
        from mmud.automation.equip import EquipDecider
        self._equip_decider = EquipDecider(self._item_db,
                                           enabled=self._config.items.auto_get)
        self._engine.register("equip", self._equip_decider, PRIO_EQUIP)
```

Completion/failure handling in `_process_line` (same pattern as GETTING):
"You are now wearing/wielding/holding" → `complete_task()`; cursed/failed
("You can't remove", "is cursed") → `mark_failed(task.payload["item"])` + abort.

- [ ] **Step 5: Run** — `pytest tests/test_equip.py -v` then `pytest -q` → green

- [ ] **Step 6: Commit**

```bash
git add src/mmud/automation/equip.py src/mmud/bot.py tests/test_equip.py
git commit -m "feat: EquipDecider — auto-equip carried equippable items"
```

---

### Task 6: Encumbrance gate + @wealth verb

**Files:**
- Modify: `src/mmud/automation/loop_runner.py`, `src/mmud/bot.py`
- Test: `tests/test_loop_runner.py` (append), `tests/test_remote.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_loop_runner.py`:

```python
def test_encumbrance_blocks_stepping():
    from mmud.state.inventory import Inventory
    runner = _make_runner(loop_path="HOME")        # use this file's existing helper
    runner._state.inventory = Inventory(encumbrance_level="heavy")
    runner._items_config.dont_go_heavy = True
    runner.start()
    assert runner._state.dequeue() is None         # nothing enqueued while heavy
```

(Adapt the construction to this test file's existing fixture style — LoopRunner
gains an `items_config` constructor argument, default `ItemsConfig()`.)

Append to `tests/test_remote.py`:

```python
def test_wealth_verb():
    from mmud.state.inventory import Inventory
    bot = _bot(WILDCARD)
    bot._state.inventory = Inventory(coins={"gold": 3, "copper": 7})
    h = RemoteCommandHandler(bot)
    reply = h.handle("Friend", "@wealth")
    assert "307" in reply        # 3*100 + 7 copper-equivalent
```

- [ ] **Step 2: Run to confirm failure** — both new tests FAIL

- [ ] **Step 3: LoopRunner gate** — add `items_config: ItemsConfig` parameter
(default `ItemsConfig()`) stored as `self._items_config`; in `_enqueue_path`
prepend:

```python
        level = self._state.inventory.encumbrance_level
        if ((self._items_config.dont_go_heavy and level == "heavy")
                or (self._items_config.dont_go_medium and level in ("medium", "heavy"))):
            self._bus.post(PathStepped(command="(halted: encumbered)", lap=self.lap))
            return
```

Update bot.py's two LoopRunner constructions (`toggle_loop`, `start_loop`) to
pass `items_config=self._config.items`.

- [ ] **Step 4: @wealth verb** — in `RemoteCommandHandler._register_builtins`:

```python
        self.register("wealth", lambda s, a: (
            f"wealth {bot._state.inventory.wealth_total()} copper-equiv "
            f"({', '.join(f'{n} {d}' for d, n in bot._state.inventory.coins.items()) or 'no coins'})"
        ))
```

- [ ] **Step 5: Run** — `pytest -q` → green

- [ ] **Step 6: Commit**

```bash
git add src/mmud/automation/loop_runner.py src/mmud/automation/remote.py src/mmud/bot.py tests/
git commit -m "feat: encumbrance-gated travel + @wealth remote verb"
```

---

## Verification

- `pytest -q` — full suite green after every task.
- End-to-end transcript (append to tests/test_bot.py): transcript of an inv
  block → `bot._state.inventory.coins` populated and `inventory_dirty` False;
  transcript "You notice 23 copper farthings here." with `auto_cash=true` →
  "get copper" sent.
- Live test (user, per docs/testing-plan.md): run `inv` and capture the REAL
  output format — the carrying/wearing/wealth/encumbrance regexes in
  `inventory_parser.py` are the phase's biggest guess. Verify `get`/`equip`
  command syntax and the "You took/can't get" responses; tune `items.py` and
  the bot completion lines. Verify coin exchange rates for `WEALTH_RATES`.
- Deferred by design: deposit/withdraw vs max_wealth/min_wealth (Phase 8
  banking), drop/stash beyond un-gettable marking (original stashes at
  configured rooms — needs Phase 6 travel), coin upconversion command (verify
  whether the server has one during live testing; add to items.py then).
