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
