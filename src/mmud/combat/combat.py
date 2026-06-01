from __future__ import annotations
from mmud.config.schema import CombatConfig
from mmud.state.game_state import GameState


class CombatEngine:
    def __init__(self, config: CombatConfig | None = None) -> None:
        cfg = config or CombatConfig()
        self.attack_cmd = cfg.attack_cmd
        self.flee_threshold = cfg.flee_threshold
        self.rest_threshold = cfg.rest_threshold
        self.mana_attack_pct = cfg.mana_attack_pct

    def decide(self, state: GameState) -> str | None:
        hp_pct = state.hp / state.max_hp if state.max_hp > 0 else 1.0
        mp_pct = state.mana / state.max_mana if state.max_mana > 0 else 1.0

        if state.in_combat:
            if hp_pct <= self.flee_threshold:
                return "flee"
            if state.max_mana > 0 and mp_pct < self.mana_attack_pct:
                return None
            target = state.monsters_present[0] if state.monsters_present else ""
            return f"{self.attack_cmd} {target}".strip()

        if hp_pct < self.rest_threshold:
            return "rest"
        return None
