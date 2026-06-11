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
_CANT_GET_RE = re.compile(r"you can'?t (?:get|take|pick up)", re.IGNORECASE)


class LootMonitor:
    """Watches 'You notice ... here.' lines and records gettable things.

    `is_monster` lets the bot exclude room monsters (passed from the MonsterDB)
    so a noticed creature is not mistaken for loot.
    """

    def __init__(self, is_monster: Callable[[str], bool] | None = None) -> None:
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
                    self._begin(state, denom)
                    return f"get {denom}"
                del state.ground_coins[denom]   # unwanted: forget it
        if self._cfg.auto_get:
            while state.ground_items:
                name = state.ground_items.pop(0)
                if name in self._ungettable:
                    continue
                self._begin(state, name)
                return f"get {name}"
        return None

    def _begin(self, state: GameState, name: str) -> None:
        state.begin_task(TaskType.GETTING, priority=PRIO_ITEMS,
                         timeout_s=GET_TIMEOUT_S, payload={"item": name},
                         now=self._now())
        state.inventory_dirty = True
