from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Callable

# Copper-equivalent exchange rates. VERIFY against the live server
# (MajorMUD: 10 copper = 1 silver, 10 silver = 1 gold, 10 gold = 1 platinum,
# 10 platinum = 1 runic) and record in docs/testing-plan.md.
WEALTH_RATES = {"copper": 1, "silver": 10, "gold": 100,
                "platinum": 1000, "runic": 10000}

REFRESH_TIMEOUT_S = 5.0


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

    def wealth_total(self) -> int:
        """Total wealth in copper-equivalent."""
        return sum(WEALTH_RATES.get(d, 0) * n for d, n in self.coins.items())


class RefreshDecider:
    """PRIO_REFRESH slot: issue `inv` when the inventory snapshot is stale.

    Begins a WAITING task so the chain below is pinned until the parsed
    response arrives (bot completes the task) or the timeout aborts it.
    """

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now

    def decide(self, state) -> str | None:
        from mmud.automation.decision import PRIO_REFRESH
        from mmud.state.tasks import TaskType
        if state.in_combat or not state.inventory_dirty:
            return None
        state.begin_task(TaskType.WAITING, priority=PRIO_REFRESH,
                         timeout_s=REFRESH_TIMEOUT_S, now=self._now())
        return "inv"
