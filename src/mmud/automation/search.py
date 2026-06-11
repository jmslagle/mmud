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
