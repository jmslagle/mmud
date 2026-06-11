from __future__ import annotations
from mmud.config.schema import CombatConfig
from mmud.state.game_state import GameState


class CombatEngine:
    def __init__(self, config: CombatConfig | None = None,
                 sneak_cmd: str = "") -> None:
        cfg = config or CombatConfig()
        self.attack_cmd = cfg.attack_cmd
        self.flee_threshold = cfg.flee_threshold
        self.rest_threshold = cfg.rest_threshold
        self.mana_attack_pct = cfg.mana_attack_pct
        self.sneak_cmd = sneak_cmd
        self._sneaked_this_encounter = False

    def decide(self, state: GameState) -> str | None:
        hp_pct = state.hp / state.max_hp if state.max_hp > 0 else 1.0
        mp_pct = state.mana / state.max_mana if state.max_mana > 0 else 1.0

        if state.in_combat:
            if hp_pct <= self.flee_threshold:
                return "flee"
            if state.max_mana > 0 and mp_pct < self.mana_attack_pct:
                return None
            # Sneak before first attack if configured
            if self.sneak_cmd and not self._sneaked_this_encounter:
                self._sneaked_this_encounter = True
                return self.sneak_cmd
            target = state.monster_names()[0] if state.monsters_present else ""
            return f"{self.attack_cmd} {target}".strip()

        # Reset sneak flag when not in combat
        self._sneaked_this_encounter = False

        if hp_pct < self.rest_threshold:
            return "rest"
        return None
