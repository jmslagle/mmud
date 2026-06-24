from __future__ import annotations
import time
from typing import Callable
from mmud.automation.decision import PRIO_SPELLS
from mmud.combat.combat import attackable_sightings, select_attack_target
from mmud.config.schema import SpellsConfig
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType

BLESS_COOLDOWN_TICKS = 600
# Pace attack casts to one combat round. MegaMud's combat_spell_cast (0x00407b7d)
# enforces a 4-second cooldown on (non-area) casts; without pacing the bot recast
# on every server line and spammed the spell.
CAST_ROUND_S = 4.0


class SpellEngine:
    """Decides which spell to cast based on SpellsConfig and current GameState."""

    def __init__(self, config: SpellsConfig, monster_priority: list[str] | None = None,
                 attack_order: str = "first", attack_neutral: bool = False,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._cfg = config
        # Target selection mirrors melee so the nuke and the swing share a target.
        self._monster_priority = [p.lower() for p in (monster_priority or [])]
        self._attack_order = attack_order
        self._attack_neutral = attack_neutral
        self._now = now
        # Initialize to -BLESS_COOLDOWN_TICKS so the first cast is always allowed
        self._bless_cooldowns: list[int] = [-BLESS_COOLDOWN_TICKS] * len(config.bless)
        self._ticks = 0
        self._attack_casts = 0
        self._swapped_to_melee = False
        self._cast_primary_next = True

    def tick(self) -> None:
        """Advance one game tick (call once per ~1Hz timer)."""
        self._ticks += 1

    def _attack_on_target(self, state: GameState) -> str:
        """The primary attack spell is single-target offensive: MegaMud sends
        "{spell} {target}" (combat_spell_cast @ 0x00407b7d). Without the target
        the server rejects it ("You must specify a target for that spell!")."""
        target = select_attack_target(state, self._monster_priority,
                                      self._attack_order, self._attack_neutral)
        return f"{self._cfg.attack} {target}".strip()

    def _begin_cast(self, state: GameState, command: str) -> str:
        """Pace casts: hold the spell slot (and melee below it) for one combat
        round so the bot doesn't recast on every server line. A higher-priority
        decider (flee/cure) can still preempt; the 1Hz ticker clears the timeout."""
        state.begin_task(TaskType.CASTING, priority=PRIO_SPELLS,
                         timeout_s=CAST_ROUND_S, now=self._now())
        return command

    def decide(self, state: GameState) -> str | None:
        """Return the spell command to cast, or None."""
        hp_pct = state.hp / state.max_hp if state.max_hp > 0 else 1.0
        mp_pct = state.mana / state.max_mana if state.max_mana > 0 else 1.0

        # Encounter ended (truly idle: not fighting AND no monster present):
        # reset the cast counter, optionally swap back to the casting weapon.
        if not state.in_combat and not state.monsters_present:
            if self._swapped_to_melee:
                self._swapped_to_melee = False
                self._attack_casts = 0
                self._cast_primary_next = True
                if self._cfg.cast_weapon_cmd:
                    return self._cfg.cast_weapon_cmd
            self._attack_casts = 0
            self._cast_primary_next = True

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

        # Attack spell — cast when an *attackable* monster is present (initiating)
        # or we're already fighting; takes priority over bless. Bounded by
        # max_cast_count. NPCs/guards (kill-type 2) never trigger a nuke.
        attackable = attackable_sightings(state, self._attack_neutral)
        if self._cfg.attack and (attackable or state.in_combat):
            limit = self._cfg.max_cast_count
            if limit <= 0 or self._attack_casts < limit:
                self._attack_casts += 1
                if self._cfg.multi_attack:
                    if self._cast_primary_next:
                        self._cast_primary_next = False
                        return self._begin_cast(state, self._attack_on_target(state))
                    self._cast_primary_next = True
                    # AoE: cast bare (no target), still paced as a round
                    return self._begin_cast(state, self._cfg.multi_attack)
                return self._begin_cast(state, self._attack_on_target(state))
            if not self._swapped_to_melee and self._cfg.melee_weapon_cmd:
                self._swapped_to_melee = True
                return self._cfg.melee_weapon_cmd
            return None

        # Pre-attack spell — cast just before engaging (only for attackable targets)
        if (self._cfg.pre_attack and not state.in_combat and attackable):
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
