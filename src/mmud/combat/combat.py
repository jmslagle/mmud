from __future__ import annotations
from mmud.state.game_state import GameState


class CombatEngine:
    def __init__(self, flee_threshold: float = 0.15, rest_threshold: float = 0.40) -> None:
        self.flee_threshold = flee_threshold
        self.rest_threshold = rest_threshold

    def decide(self, state: GameState) -> str | None:
        hp_pct = state.hp / state.max_hp if state.max_hp > 0 else 1.0
        if state.in_combat:
            if hp_pct <= self.flee_threshold:
                return "flee"
            return "attack"
        if hp_pct < self.rest_threshold:
            return "rest"
        return None
