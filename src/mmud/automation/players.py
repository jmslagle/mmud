from __future__ import annotations
import time
from typing import Callable
from mmud.automation.decision import PRIO_LOOK
from mmud.config.schema import PvpConfig, PlayerRule
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType


class PlayerLookDecider:
    """Auto-examine unknown players: send 'l <name>' at each player in the room we
    haven't looked at yet (skipping friends), so we learn race/class/alignment.
    Mirrors MegaMud's player_info_lookup_decide (0x004037cf) gated by LookPlayers.

    Begins a LOOKING task so the engine waits for the examine result (or timeout)
    before looking at the next player or moving on."""

    def __init__(self, pvp: PvpConfig, rules: list[PlayerRule],
                 now: Callable[[], float] = time.monotonic) -> None:
        self._enabled = pvp.look_players
        self._friends = {r.name.lower() for r in rules if r.friend}
        self._now = now
        self._looked: set[str] = set()

    def mark_looked(self, name: str) -> None:
        self._looked.add(name.lower())

    def decide(self, state: GameState) -> str | None:
        if not self._enabled or state.in_combat:
            return None
        for name in state.players_present:
            key = name.lower()
            if key in self._friends or key in self._looked:
                continue
            self._looked.add(key)
            state.begin_task(TaskType.LOOKING, priority=PRIO_LOOK,
                             timeout_s=4.0, now=self._now())
            return f"l {name}"
        return None
