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
