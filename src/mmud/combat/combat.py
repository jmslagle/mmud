from __future__ import annotations
import re
from mmud.config.schema import CombatConfig
from mmud.state.game_state import GameState

_SNEAK_OK_RE = re.compile(r"move silently|begin to sneak", re.IGNORECASE)
_SNEAK_FAIL_RE = re.compile(r"fail to sneak|make a noise", re.IGNORECASE)


def select_target(names: list[str], priority: list[str], attack_order: str) -> str:
    """Pick the monster to act on: configured priority first, else by attack_order.
    `priority` is expected pre-lowercased. Returns "" when no monster is present.
    Shared by melee (CombatEngine) and spell (SpellEngine) so the nuke and the
    swing land on the same target."""
    if not names:
        return ""
    for wanted in priority:
        for name in names:
            if wanted in name.lower():
                return name
    if attack_order == "last":
        return names[-1]
    if attack_order == "reverse":
        return names[::-1][0]
    return names[0]


class CombatEngine:
    def __init__(self, config: CombatConfig | None = None,
                 sneak_cmd: str = "", must_sneak: bool = False) -> None:
        cfg = config or CombatConfig()
        self.attack_cmd = cfg.attack_cmd
        self.flee_threshold = cfg.flee_threshold
        self.rest_threshold = cfg.rest_threshold
        self.mana_attack_pct = cfg.mana_attack_pct
        self.attack_order = cfg.attack_order
        self.polite_attacks = cfg.polite_attacks
        self.monster_priority = [p.lower() for p in cfg.monster_priority]
        self.sneak_cmd = sneak_cmd
        self.must_sneak = must_sneak
        self._sneaked_this_encounter = False
        self._sneak_confirmed = False

    def on_line(self, line: str) -> None:
        if not self.must_sneak:
            return
        if _SNEAK_OK_RE.search(line):
            self._sneak_confirmed = True
        elif _SNEAK_FAIL_RE.search(line):
            self._sneaked_this_encounter = False

    def decide(self, state: GameState) -> str | None:
        hp_pct = state.hp / state.max_hp if state.max_hp > 0 else 1.0
        mp_pct = state.mana / state.max_mana if state.max_mana > 0 else 1.0

        # Engage if already fighting OR a monster is in the room (initiate).
        if state.in_combat or state.monsters_present:
            if state.in_combat and hp_pct <= self.flee_threshold:
                return "flee"
            if state.max_mana > 0 and mp_pct < self.mana_attack_pct:
                return None
            # Sneak before first attack if configured
            if self.sneak_cmd and not self._sneaked_this_encounter:
                self._sneaked_this_encounter = True
                return self.sneak_cmd
            if self.must_sneak and not self._sneak_confirmed:
                return None
            if self.polite_attacks and state.players_present:
                return None
            target = self._pick_target(state)
            return f"{self.attack_cmd} {target}".strip()

        # Not engaged: reset sneak flags for the next encounter
        self._sneaked_this_encounter = False
        self._sneak_confirmed = False

        if hp_pct < self.rest_threshold:
            return "rest"
        return None

    def _pick_target(self, state: GameState) -> str:
        return select_target(state.monster_names(), self.monster_priority,
                             self.attack_order)
