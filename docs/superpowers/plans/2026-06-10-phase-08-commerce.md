# Phase 8: Shopping, Banking, Training — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire commerce as travel detours: bank when too rich (or too poor), sell/buy configured items at the shop, train when level-ready — then resume whatever loop was running.

**Architecture:** A `CommerceEngine` registered at a new `PRIO_COMMERCE = 95` slot (between items 90 and party 100) plus a line monitor (train-ready detection). It is a stage machine — `IDLE → DETOURING → WORKING` — that drives Phase 6's multi-hop travel through injected callables (`navigate`, `resume_loop`, `loop_running`, `travel_active`) so it unit-tests without a bot. Work commands are computed ONCE on arrival (the work queue), one command per `decide()`; inventory is marked dirty at the end so Phase 5's `RefreshDecider` re-syncs and the trigger can't re-fire on stale data.

**Tech Stack:** Python 3.11+, stdlib only. Transcript-tested via `make_transcript_bot`.

**Prerequisites:** Phases 5, 6, 7 complete (`pytest -q` green, 346).

**Verified API facts (no re-derivation needed):**
- `Inventory.wealth_total()` (copper-equiv via `WEALTH_RATES`), `inventory.coins` dict, `items.max_wealth`/`min_wealth` config — all exist (`src/mmud/state/inventory.py`, Phase 5).
- `bot.navigate_to_room(code)` returns `"Navigating to XXXX (N steps)"` on success, error text otherwise (Phase 6). Arrival at a NAMED room sets `state.current_room` — bank/shop/train rooms are named rooms, so `current_room == dest` is the arrival check.
- `RefreshDecider` (PRIO_REFRESH=60) auto-issues `inv` when `inventory_dirty` — commerce triggers must require `not state.inventory_dirty` so a completed detour can't re-trigger until fresh data arrives.
- `TaskType.TRAINING` exists unused.

> **Server-wording caveat:** the train-ready line, and `deposit/withdraw/sell/buy/train`
> command syntax are educated reconstructions. Record real wording in
> docs/testing-plan.md during live testing and tune (Phase 2 procedure).

---

## File Map

```
src/mmud/
  automation/commerce.py     NEW — CommerceEngine (decider + line monitor)
  automation/decision.py     MODIFY — PRIO_COMMERCE = 95
  config/schema.py           MODIFY — CommerceConfig
  config/loader.py           MODIFY — parse [commerce]
  bot.py                     MODIFY — wire engine + hook
tests/
  test_commerce.py           NEW
  test_config.py             MODIFY
  test_bot.py                MODIFY — bank-detour e2e
characters/example.toml      MODIFY
README.md                    MODIFY — [commerce] note
```

---

### Task 1: CommerceConfig + PRIO_COMMERCE

**Files:**
- Modify: `src/mmud/config/schema.py`, `src/mmud/config/loader.py`,
  `src/mmud/automation/decision.py`, `characters/example.toml`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_commerce_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[commerce]
bank_room = "BANK"
shop_room = "SHOP"
train_room = "TRNR"
sell_items = ["rusty sword"]
buy_items = ["torch"]
auto_train = true
""")
    cfg = load_config(p)
    assert cfg.commerce.bank_room == "BANK"
    assert cfg.commerce.shop_room == "SHOP"
    assert cfg.commerce.train_room == "TRNR"
    assert cfg.commerce.sell_items == ["rusty sword"]
    assert cfg.commerce.buy_items == ["torch"]
    assert cfg.commerce.auto_train is True


def test_commerce_defaults():
    cfg = load_config(None)
    assert cfg.commerce.bank_room == ""       # "" = banking disabled
    assert cfg.commerce.auto_train is False
    assert cfg.commerce.sell_items == []
```

- [ ] **Step 2: Run to confirm failure** — `pytest tests/test_config.py -v -k commerce` → AttributeError

- [ ] **Step 3: Implement**

`src/mmud/automation/decision.py` — change the slot table comment block, inserting
after `PRIO_ITEMS = 90`:

```python
PRIO_COMMERCE = 95  # bank/shop/train detours              (Phase 8)
```

(Also append `"PRIO_COMMERCE"` to the ordering test's name list in
`tests/test_decision.py::test_priority_constants_are_strictly_ordered`.)

`src/mmud/config/schema.py` — after `LearningConfig`:

```python
@dataclass
class CommerceConfig:
    bank_room: str = ""      # 4-letter room code; "" = banking disabled
    shop_room: str = ""      # "" = shopping disabled
    train_room: str = ""     # "" = training travel disabled
    sell_items: list[str] = field(default_factory=list)  # sell these when carried
    buy_items: list[str] = field(default_factory=list)   # keep these in inventory
    auto_train: bool = False
```

`MudConfig` gains `commerce: CommerceConfig = field(default_factory=CommerceConfig)`
(after `learning`). Loader block (after learning; add `CommerceConfig` to imports):

```python
    if co := data.get("commerce"):
        cfg.commerce = CommerceConfig(
            bank_room=co.get("bank_room", ""),
            shop_room=co.get("shop_room", ""),
            train_room=co.get("train_room", ""),
            sell_items=co.get("sell_items", []),
            buy_items=co.get("buy_items", []),
            auto_train=co.get("auto_train", False),
        )
```

`characters/example.toml` — append:

```toml
[commerce]
# Travel detours: bank when wealth > items.max_wealth (deposits down to
# items.min_wealth), withdraw when below min_wealth, sell/buy at the shop,
# train when level-ready. Rooms are 4-letter codes; "" disables that detour.
bank_room  = ""
shop_room  = ""
train_room = ""
sell_items = []      # e.g. ["rusty sword", "orc ear"]
buy_items  = []      # keep these stocked, e.g. ["torch"]
auto_train = false
```

- [ ] **Step 4: Run + commit**

Run: `pytest tests/test_config.py tests/test_decision.py -v` → green

```bash
git add src/mmud/config/ src/mmud/automation/decision.py characters/example.toml tests/
git commit -m "feat: [commerce] config + PRIO_COMMERCE slot"
```

---

### Task 2: CommerceEngine — triggers + stage machine

**Files:**
- Create: `src/mmud/automation/commerce.py`
- Test: `tests/test_commerce.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_commerce.py
from mmud.automation.commerce import CommerceEngine
from mmud.config.schema import CommerceConfig, ItemsConfig
from mmud.state.game_state import GameState
from mmud.state.inventory import Inventory
from mmud.state.tasks import TaskType


class _Harness:
    """Fake bot callables; records navigation/resume calls."""

    def __init__(self, nav_reply="Navigating to BANK (3 steps)",
                 looping=False, traveling=False):
        self.navigated: list[str] = []
        self.resumed = 0
        self._nav_reply = nav_reply
        self.looping = looping
        self.traveling = traveling

    def navigate(self, code):
        self.navigated.append(code)
        return self._nav_reply

    def make(self, commerce_cfg, items_cfg=None):
        return CommerceEngine(
            commerce_cfg, items_cfg or ItemsConfig(),
            navigate=self.navigate,
            resume_loop=lambda: setattr(self, "resumed", self.resumed + 1),
            loop_running=lambda: self.looping,
            travel_active=lambda: self.traveling,
        )


def _rich_state(copper=500, room="HOME"):
    gs = GameState()
    gs.set_room(room)
    gs.inventory = Inventory(coins={"copper": copper})
    gs.inventory_dirty = False
    return gs


def test_deposit_trigger_navigates_to_bank():
    h = _Harness()
    eng = h.make(CommerceConfig(bank_room="BANK"),
                 ItemsConfig(max_wealth=100, min_wealth=10))
    gs = _rich_state(copper=500)
    assert eng.decide(gs) is None            # detour armed, travel does the moving
    assert h.navigated == ["BANK"]


def test_no_trigger_when_under_max_wealth():
    h = _Harness()
    eng = h.make(CommerceConfig(bank_room="BANK"),
                 ItemsConfig(max_wealth=1000, min_wealth=10))
    assert eng.decide(_rich_state(copper=500)) is None
    assert h.navigated == []


def test_no_trigger_when_inventory_dirty():
    h = _Harness()
    eng = h.make(CommerceConfig(bank_room="BANK"),
                 ItemsConfig(max_wealth=100, min_wealth=10))
    gs = _rich_state(copper=500)
    gs.inventory_dirty = True                # stale data: wait for refresh
    assert eng.decide(gs) is None
    assert h.navigated == []


def test_no_trigger_while_traveling():
    h = _Harness(traveling=True)
    eng = h.make(CommerceConfig(bank_room="BANK"),
                 ItemsConfig(max_wealth=100, min_wealth=10))
    assert eng.decide(_rich_state(copper=500)) is None
    assert h.navigated == []


def test_failed_navigation_disables_trigger():
    h = _Harness(nav_reply="No known route to BANK")
    eng = h.make(CommerceConfig(bank_room="BANK"),
                 ItemsConfig(max_wealth=100, min_wealth=10))
    gs = _rich_state(copper=500)
    assert eng.decide(gs) is None
    assert eng.decide(gs) is None            # not retried forever
    assert h.navigated == ["BANK"]           # exactly one attempt


def test_deposit_work_on_arrival_then_resume():
    h = _Harness(looping=True)
    eng = h.make(CommerceConfig(bank_room="BANK"),
                 ItemsConfig(max_wealth=100, min_wealth=10))
    gs = _rich_state(copper=500)
    eng.decide(gs)                           # arm detour
    gs.set_room("BANK")                      # arrived
    assert eng.decide(gs) == "deposit 490 copper"   # 500 - min_wealth(10)
    assert gs.inventory_dirty is False       # dirty only at END of work
    assert eng.decide(gs) is None            # work done -> idle
    assert gs.inventory_dirty is True        # forces re-sync; blocks re-trigger
    assert h.resumed == 1                    # loop restarted


def test_withdraw_when_poor():
    h = _Harness()
    eng = h.make(CommerceConfig(bank_room="BANK"),
                 ItemsConfig(max_wealth=0, min_wealth=1000))
    gs = _rich_state(copper=50)
    eng.decide(gs)
    gs.set_room("BANK")
    assert eng.decide(gs) == "withdraw 950 copper"


def test_sell_detour_one_item_per_decide():
    h = _Harness()
    eng = h.make(CommerceConfig(shop_room="SHOP", sell_items=["rusty sword", "orc ear"]))
    gs = _rich_state(copper=0)
    gs.inventory = Inventory(carried_counts={"rusty sword": 1, "torch": 1,
                                             "orc ear": 2})
    gs.inventory_dirty = False
    eng.decide(gs)
    assert h.navigated == ["SHOP"]
    gs.set_room("SHOP")
    assert eng.decide(gs) == "sell rusty sword"
    assert eng.decide(gs) == "sell orc ear"
    assert eng.decide(gs) is None


def test_buy_missing_items():
    h = _Harness()
    eng = h.make(CommerceConfig(shop_room="SHOP", buy_items=["torch", "rations"]))
    gs = _rich_state(copper=100)
    gs.inventory = Inventory(carried_counts={"torch": 1})
    gs.inventory_dirty = False
    eng.decide(gs)
    gs.set_room("SHOP")
    assert eng.decide(gs) == "buy rations"
    assert eng.decide(gs) is None


def test_train_detour_uses_training_task():
    h = _Harness()
    eng = h.make(CommerceConfig(train_room="TRNR", auto_train=True))
    gs = _rich_state(copper=0)
    eng.on_line("You have enough experience to advance a level!")
    eng.decide(gs)
    assert h.navigated == ["TRNR"]
    gs.set_room("TRNR")
    assert eng.decide(gs) == "train"
    assert gs.task.type is TaskType.TRAINING
    eng.on_line("You advance to level 5!")   # clears the ready flag
    gs.complete_task()
    assert eng.decide(gs) is None
```

- [ ] **Step 2: Run to confirm failure** — `pytest tests/test_commerce.py -v` → ModuleNotFoundError

- [ ] **Step 3: Create `src/mmud/automation/commerce.py`**

```python
from __future__ import annotations
import re
import time
from enum import Enum, auto
from typing import Callable
from mmud.automation.decision import PRIO_COMMERCE
from mmud.config.schema import CommerceConfig, ItemsConfig
from mmud.state.game_state import GameState
from mmud.state.inventory import WEALTH_RATES
from mmud.state.tasks import TaskType

TRAIN_TIMEOUT_S = 15.0

# Tune against the live server; record real wording in docs/testing-plan.md.
_TRAIN_READY_RE = re.compile(
    r"enough experience to advance|you may now advance|ready to train",
    re.IGNORECASE)
_TRAIN_DONE_RE = re.compile(
    r"you advance to level|you are now level|welcome to level", re.IGNORECASE)


class _Stage(Enum):
    IDLE = auto()
    DETOURING = auto()   # travel armed toward _dest
    WORKING = auto()     # at _dest, draining _work queue


class CommerceEngine:
    """PRIO_COMMERCE slot: bank/shop/train detours over Phase 6 travel.

    Pure logic — the bot injects navigate/resume_loop/loop_running/
    travel_active callables. Stage machine: IDLE -> DETOURING -> WORKING.
    The work queue is computed once on arrival; one command per decide().
    """

    def __init__(self, config: CommerceConfig, items: ItemsConfig,
                 navigate: Callable[[str], str],
                 resume_loop: Callable[[], object],
                 loop_running: Callable[[], bool],
                 travel_active: Callable[[], bool],
                 now: Callable[[], float] = time.monotonic) -> None:
        self._cfg = config
        self._items = items
        self._navigate = navigate
        self._resume_loop = resume_loop
        self._loop_running = loop_running
        self._travel_active = travel_active
        self._now = now
        self._stage = _Stage.IDLE
        self._purpose = ""
        self._dest = ""
        self._work: list[str] = []
        self._was_looping = False
        self._train_ready = False
        self._failed_purposes: set[str] = set()   # nav failed: don't retry

    # ---- line monitor -------------------------------------------------------

    def on_line(self, line: str) -> None:
        if _TRAIN_READY_RE.search(line):
            self._train_ready = True
        elif _TRAIN_DONE_RE.search(line):
            self._train_ready = False

    # ---- decider ------------------------------------------------------------

    def decide(self, state: GameState) -> str | None:
        if self._stage is _Stage.IDLE:
            self._maybe_start_detour(state)
            return None
        if self._stage is _Stage.DETOURING:
            if state.current_room == self._dest:
                self._work = self._build_work(state)
                self._stage = _Stage.WORKING
            else:
                return None
        if self._stage is _Stage.WORKING:
            if self._work:
                cmd = self._work.pop(0)
                if self._purpose == "train":
                    state.begin_task(TaskType.TRAINING, priority=PRIO_COMMERCE,
                                     timeout_s=TRAIN_TIMEOUT_S, now=self._now())
                return cmd
            # work complete
            state.inventory_dirty = True      # re-sync; blocks stale re-trigger
            self._stage = _Stage.IDLE
            if self._was_looping:
                self._resume_loop()
            self._was_looping = False
        return None

    # ---- internals ----------------------------------------------------------

    def _maybe_start_detour(self, state: GameState) -> None:
        if self._travel_active() or state.in_combat or state.inventory_dirty:
            return
        purpose, dest = self._pick_purpose(state)
        if not purpose or purpose in self._failed_purposes:
            return
        self._was_looping = self._loop_running()
        reply = self._navigate(dest)
        if reply.startswith("Navigating"):
            self._purpose, self._dest = purpose, dest
            self._stage = _Stage.DETOURING
        else:
            self._failed_purposes.add(purpose)   # unroutable: disable

    def _pick_purpose(self, state: GameState) -> tuple[str, str]:
        wealth = state.inventory.wealth_total()
        if self._train_ready and self._cfg.auto_train and self._cfg.train_room:
            return "train", self._cfg.train_room
        if self._cfg.bank_room and self._items.max_wealth \
                and wealth > self._items.max_wealth:
            return "deposit", self._cfg.bank_room
        if self._cfg.bank_room and self._items.min_wealth \
                and 0 < wealth < self._items.min_wealth:
            return "withdraw", self._cfg.bank_room
        carried = set(state.inventory.carried)
        if self._cfg.shop_room:
            if any(i.lower() in carried for i in self._cfg.sell_items):
                return "sell", self._cfg.shop_room
            if any(i.lower() not in carried for i in self._cfg.buy_items):
                return "buy", self._cfg.shop_room
        return "", ""

    def _build_work(self, state: GameState) -> list[str]:
        inv = state.inventory
        if self._purpose == "deposit":
            excess = inv.wealth_total() - self._items.min_wealth
            cmds = []
            # largest denomination first
            for denom in sorted(inv.coins, key=lambda d: -WEALTH_RATES.get(d, 0)):
                rate = WEALTH_RATES.get(denom, 0)
                if rate <= 0 or excess <= 0:
                    continue
                k = min(inv.coins[denom], excess // rate)
                if k > 0:
                    cmds.append(f"deposit {k} {denom}")
                    excess -= k * rate
            return cmds
        if self._purpose == "withdraw":
            need = self._items.min_wealth - inv.wealth_total()
            return [f"withdraw {need} copper"] if need > 0 else []
        if self._purpose == "sell":
            carried = set(inv.carried)
            return [f"sell {i.lower()}" for i in self._cfg.sell_items
                    if i.lower() in carried]
        if self._purpose == "buy":
            carried = set(inv.carried)
            return [f"buy {i.lower()}" for i in self._cfg.buy_items
                    if i.lower() not in carried]
        if self._purpose == "train":
            return ["train"]
        return []
```

- [ ] **Step 4: Run** — `pytest tests/test_commerce.py -v` → 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/mmud/automation/commerce.py tests/test_commerce.py
git commit -m "feat: CommerceEngine — bank/shop/train detours with stage machine"
```

---

### Task 3: Bot wiring + e2e

**Files:**
- Modify: `src/mmud/bot.py`, `README.md`
- Test: `tests/test_bot.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bot.py` (reuses `_NAV_ROOMS`-style fixtures; bank room is
a named room one step north of HOME):

```python
_BANK_ROOMS = {
    "HOME": _Room(code="HOME", hex_id="AAAA0001", hex_id2="", flags=(0, 0, 0),
                  region="", name="The Home Room"),
    "BANK": _Room(code="BANK", hex_id="BBBB0002", hex_id2="", flags=(0, 0, 0),
                  region="", name="The Grand Bank"),
}
_BANK_PATH = _GamePath(from_code="HOME", from_region="", from_name="",
                       to_code="BANK", to_region="", to_name="", npc="",
                       steps=[_PathStep(hex_id="AAAA0001", command="n")])


@pytest.mark.asyncio
async def test_bank_detour_deposits_and_resyncs():
    from mmud.state.inventory import Inventory
    config = MudConfig()
    config.items.max_wealth = 100
    config.items.min_wealth = 10
    config.commerce.bank_room = "BANK"
    bot = make_transcript_bot(
        ["Obvious exits: north\n",      # idle in HOME: commerce arms, travel moves
         "The Grand Bank\n",            # named arrival
         "Obvious exits: south\n",      # arrival signal completes the route
         "ok\n",                        # commerce works: deposit
         "ok\n"],                       # work done -> dirty -> refresh issues inv
        config=config, rooms=_BANK_ROOMS)
    bot._navigator._paths[("HOME", "BANK")] = _BANK_PATH
    bot._state.set_room("HOME")
    bot._state.current_hex = "AAAA0001"
    bot._state.inventory = Inventory(coins={"copper": 500})
    bot._state.inventory_dirty = False
    await bot.run()
    assert "n" in bot._conn.sent
    assert "deposit 490 copper" in bot._conn.sent
    assert "inv" in bot._conn.sent      # post-work re-sync
```

- [ ] **Step 2: Run to confirm failure** — commerce not wired → no deposit sent

- [ ] **Step 3: Wire into `bot.py`**

Import `PRIO_COMMERCE` in the decision import list. In `__init__` (after the
search registration):

```python
        from mmud.automation.commerce import CommerceEngine
        self._commerce = CommerceEngine(
            self._config.commerce, self._config.items,
            navigate=self.navigate_to_room,
            resume_loop=lambda: self.start_loop(),
            loop_running=lambda: bool(self._loop_runner and self._loop_runner.running),
            travel_active=lambda: self._travel.active,
        )
        self._engine.register("commerce", self._commerce, PRIO_COMMERCE)
```

In `_process_line` (after `self._backstab.on_line(clean)`):

```python
        self._commerce.on_line(clean)
```

- [ ] **Step 4: Run** — `pytest tests/test_bot.py -v -k bank_detour` then `pytest -q` → green

- [ ] **Step 5: README** — extend the config reference with the `[commerce]`
block (same comments as example.toml) and one paragraph under a "Commerce
detours" heading: triggers, that the loop resumes afterward, and the live-tune
caveat for command syntax.

- [ ] **Step 6: Commit**

```bash
git add src/mmud/bot.py tests/test_bot.py README.md
git commit -m "feat: wire CommerceEngine — bank/shop/train detours with loop resume"
```

---

## Verification

- `pytest -q` — full suite green after every task.
- Unit coverage: every trigger (deposit/withdraw/sell/buy/train), dirty-data
  guard, traveling guard, failed-navigation disable, loop resume.
- Live test (user, per docs/testing-plan.md): set `bank_room` + low
  `max_wealth`, watch a full detour: leave loop → walk to bank → deposit →
  `inv` → loop resumes. Verify the server's real `deposit`/`withdraw`/`sell`/
  `buy`/`train` syntax and the train-ready line; tune `_TRAIN_READY_RE`/
  `_TRAIN_DONE_RE` and the command templates.
- Deliberately deferred: shop price awareness / affordability checks (needs
  live `buy` failure wording), selling un-carried `sell_items` variants
  (plural forms), multiple banks.
