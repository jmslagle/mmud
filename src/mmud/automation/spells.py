from __future__ import annotations
import re
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
                 mana_attack_pct: float = 0.0,
                 bless_durations: dict[str, float] | None = None,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._cfg = config
        # Target selection mirrors melee so the nuke and the swing share a target.
        self._monster_priority = [p.lower() for p in (monster_priority or [])]
        self._attack_order = attack_order
        self._attack_neutral = attack_neutral
        # MegaMud's "ManaAttack%" floor: cast the attack spell only at/above it;
        # below it -> melee (combat engine swings).
        self._mana_attack_pct = mana_attack_pct
        self._now = now
        # Per-bless re-cast timing (time-based, MegaMud-style): last-cast time + an
        # immediate-refresh flag set when the buff's fade line is seen. None = never
        # cast yet -> due now.
        self._bless_last: list[float | None] = [None] * len(config.bless)
        self._bless_due: list[bool] = [False] * len(config.bless)
        self._bless_fade = [re.compile(b.refresh_on, re.IGNORECASE) if b.refresh_on
                            else None for b in config.bless]
        # Per-slot re-cast interval (seconds): explicit interval_s wins; else derive
        # from the spell's SPELLS.MD duration (minutes) at 85% to avoid gaps; else
        # MegaMud's flat 600s.
        durs = bless_durations or {}
        self._bless_interval = [
            b.interval_s if b.interval_s and b.interval_s > 0
            else (durs[k] * 60 * 0.85 if (k := b.cmd.strip().lower().split()[-1]
                                          if b.cmd.strip() else "") in durs
                  else float(BLESS_COOLDOWN_TICKS))
            for b in config.bless]
        self._ticks = 0
        self._attack_casts = 0
        self._swapped_to_melee = False
        self._cast_primary_next = True

    def tick(self) -> None:
        """Advance one game tick (call once per ~1Hz timer)."""
        self._ticks += 1

    def on_line(self, line: str) -> None:
        """Detect a buff's fade line (per-bless `refresh_on`) and mark it for an
        immediate re-cast — true 'always-on', better than MegaMud's blind timer."""
        for i, pat in enumerate(self._bless_fade):
            if pat is not None and pat.search(line):
                self._bless_due[i] = True

    def _attack_on_target(self, state: GameState) -> str | None:
        """The primary attack spell is single-target offensive: MegaMud sends
        "{spell} {target}" (combat_spell_cast @ 0x00407b7d). Returns None when
        there's no target — never cast a bare "{spell}" (the server rejects it, and
        in_combat can linger for a beat after the last kill with an empty roster)."""
        target = select_attack_target(state, self._monster_priority,
                                      self._attack_order, self._attack_neutral)
        if not target:
            return None
        return f"{self._cfg.attack} {target}"

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
            cap_reached = limit > 0 and self._attack_casts >= limit
            # MegaMud: cast only if mana% >= ManaAttack% AND under the cast cap.
            # Below the mana floor it melees PER ROUND (re-casts if mana recovers);
            # the cap is sticky for the encounter (swap to the melee weapon once).
            has_mana = (state.max_mana <= 0 or mp_pct >= self._mana_attack_pct)
            if cap_reached and not self._swapped_to_melee and self._cfg.melee_weapon_cmd:
                self._swapped_to_melee = True
                return self._cfg.melee_weapon_cmd
            if self._swapped_to_melee or cap_reached or not has_mana:
                return None   # melee: the combat engine swings
            # AoE round (alternating) — only when there's actually something to hit.
            if self._cfg.multi_attack and not self._cast_primary_next:
                if not attackable:
                    return None
                self._cast_primary_next = True
                self._attack_casts += 1
                return self._begin_cast(state, self._cfg.multi_attack)
            cmd = self._attack_on_target(state)
            if cmd is None:
                return None   # no monster to target -> never bare-cast the spell
            self._cast_primary_next = False
            self._attack_casts += 1
            return self._begin_cast(state, cmd)

        # Pre-attack spell — cast just before engaging (only for attackable targets)
        if (self._cfg.pre_attack and not state.in_combat and attackable):
            return self._cfg.pre_attack

        # Bless spells: re-cast each slot when its interval has elapsed, or at once
        # if its fade line was seen (on_line). Gated by mana%. Reached only when not
        # attacking (buffs are maintained between fights).
        now = self._now()
        for i, bless in enumerate(self._cfg.bless):
            if not bless.cmd:
                continue
            if state.max_mana > 0 and mp_pct < bless.mana_pct:
                continue
            last = self._bless_last[i]
            due = (self._bless_due[i] or last is None
                   or (now - last) >= self._bless_interval[i])
            if not due:
                continue
            self._bless_last[i] = now
            self._bless_due[i] = False
            return bless.cmd

        return None
