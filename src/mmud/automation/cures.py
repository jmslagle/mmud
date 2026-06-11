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
