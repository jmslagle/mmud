from __future__ import annotations
from mmud.config.schema import SpellsConfig
from mmud.state.game_state import GameState

BLESS_COOLDOWN_TICKS = 600


class SpellEngine:
    """Decides which spell to cast based on SpellsConfig and current GameState."""

    def __init__(self, config: SpellsConfig) -> None:
        self._cfg = config
        # Initialize to -BLESS_COOLDOWN_TICKS so the first cast is always allowed
        self._bless_cooldowns: list[int] = [-BLESS_COOLDOWN_TICKS] * len(config.bless)
        self._ticks = 0

    def tick(self) -> None:
        """Advance one game tick (call once per ~1Hz timer)."""
        self._ticks += 1

    def decide(self, state: GameState) -> str | None:
        """Return the spell command to cast, or None."""
        hp_pct = state.hp / state.max_hp if state.max_hp > 0 else 1.0
        mp_pct = state.mana / state.max_mana if state.max_mana > 0 else 1.0

        # Mana heal (only out of combat)
        if (self._cfg.mana_heal and not state.in_combat
                and state.max_mana > 0
                and mp_pct < self._cfg.mana_heal_pct):
            return self._cfg.mana_heal

        # Heal spell (out of combat or in combat if config says so)
        if (self._cfg.heal and state.max_hp > 0
                and hp_pct < self._cfg.heal_hp_pct
                and not state.in_combat):
            return self._cfg.heal

        # Attack spell (in combat, takes priority over bless)
        if state.in_combat and self._cfg.attack and state.monsters_present:
            return self._cfg.attack

        # Pre-attack spell — cast just before engaging
        if (self._cfg.pre_attack and not state.in_combat
                and state.monsters_present):
            return self._cfg.pre_attack

        # Bless spells (check each slot)
        for i, bless in enumerate(self._cfg.bless):
            if not bless.cmd:
                continue
            if mp_pct < bless.mana_pct:
                continue
            if self._ticks - self._bless_cooldowns[i] < BLESS_COOLDOWN_TICKS:
                continue
            self._bless_cooldowns[i] = self._ticks
            return bless.cmd

        return None
