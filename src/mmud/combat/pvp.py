from __future__ import annotations
from mmud.automation.safety import SafetyMonitor
from mmud.config.schema import PlayerRule, PvpConfig
from mmud.state.game_state import GameState


class PvpEngine:
    """React to non-friend players in the room per [pvp] config.

    Actions: "" ignore | "flee" | "attack" (cast pvp.spell at them) |
    "hangup" (via SafetyMonitor) | any other string = literal command.
    Reacts once per player name until they leave sight.
    """

    def __init__(self, config: PvpConfig, rules: list[PlayerRule],
                 safety: SafetyMonitor) -> None:
        self._cfg = config
        self._friends = {r.name.lower() for r in rules if r.friend}
        self._safety = safety
        self._reacted: set[str] = set()

    def check(self, state: GameState) -> str | None:
        if not self._cfg.action:
            return None
        present = {p for p in state.players_present
                   if p.lower() not in self._friends}
        self._reacted &= {p.lower() for p in state.players_present}
        for player in sorted(present):
            if player.lower() in self._reacted:
                continue
            self._reacted.add(player.lower())
            return self._react(state, player)
        return None

    def _react(self, state: GameState, player: str) -> str | None:
        action = self._cfg.action
        if action == "flee":
            n = max(1, self._cfg.flee_rooms)
            for _ in range(n - 1):
                state.enqueue("flee")
            return "flee"
        if action == "attack":
            return (f"{self._cfg.spell} {player}".strip()
                    if self._cfg.spell else f"attack {player}")
        if action == "hangup":
            self._safety.request_hangup(f"pvp: {player} in room")
            return None
        return action
