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
