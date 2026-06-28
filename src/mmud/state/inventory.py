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
    encumbrance_cur: int = 0          # raw "1938/2880" current weight (for the pickup cap)
    encumbrance_max: int = 0          # raw max weight (0 = not seen yet)
    wealth_copper: int = 0            # authoritative total from the "Wealth:" line (copper-equiv,
                                      # 0 = not reported). NOT stored in `coins` — that's the
                                      # actual carried denominations only.

    @property
    def carried(self) -> list[str]:
        return list(self.carried_counts)

    def wealth_total(self) -> int:
        """Total wealth in copper-equivalent — the server's authoritative 'Wealth:' total
        when reported, else summed from the carried coins."""
        return self.wealth_copper or sum(WEALTH_RATES.get(d, 0) * n
                                         for d, n in self.coins.items())


class RefreshDecider:
    """PRIO_REFRESH slot: issue the inventory command when the snapshot is stale.

    Begins a WAITING task so the chain below is pinned until the parsed
    response arrives (bot completes the task) or the timeout aborts it. The
    command is configurable (`items.inventory_cmd`) — some servers reject "inv"
    and want "i" or "inventory".
    """

    def __init__(self, inventory_cmd: str = "inv",
                 now: Callable[[], float] = time.monotonic) -> None:
        self._cmd = inventory_cmd or "inv"
        self._now = now

    def decide(self, state) -> str | None:
        from mmud.automation.decision import PRIO_REFRESH
        from mmud.state.tasks import TaskType
        if state.in_combat or not state.inventory_dirty:
            return None
        state.begin_task(TaskType.WAITING, priority=PRIO_REFRESH,
                         timeout_s=REFRESH_TIMEOUT_S, now=self._now())
        return self._cmd
