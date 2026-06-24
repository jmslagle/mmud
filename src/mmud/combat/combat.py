from __future__ import annotations
import re
from mmud.config.schema import CombatConfig
from mmud.state.game_state import GameState

_SNEAK_OK_RE = re.compile(r"move silently|begin to sneak", re.IGNORECASE)
_SNEAK_FAIL_RE = re.compile(r"fail to sneak|make a noise", re.IGNORECASE)


def activity_reason(state: GameState, cmd, mana_attack_pct: float,
                    rest_threshold: float) -> str:
    """Why the bot is intentionally idle this tick (so a wait doesn't look frozen).
    "" when it's acting or has nothing to wait on."""
    if cmd is not None:
        return ""
    mp_pct = state.mana / state.max_mana if state.max_mana > 0 else 1.0
    hp_pct = state.hp / state.max_hp if state.max_hp > 0 else 1.0
    if ((state.in_combat or state.monsters_present)
            and state.max_mana > 0 and mp_pct < mana_attack_pct):
        return "waiting for mana"
    if (not state.in_combat and not state.monsters_present
            and hp_pct < rest_threshold):
        return "resting"
    return ""


def is_attackable(kill_type: int, attack_neutral: bool) -> bool:
    """MegaMud's attack gate (combat_flee_or_hide_decide: `tier != 4 -> skip`).
    kill-type 4 = hostile (always attacked); 3 = neutral (only if AttackNeutral);
    2 = good NPC and 5 = special (never attacked). 0 = unknown/learned: NOT in
    MONSTERS.MD, so we never catalogued it as a protected NPC -> default to
    attackable (also keeps the bot working before the monster DB is wired)."""
    if kill_type in (2, 5):
        return False
    if kill_type == 3:
        return attack_neutral
    return True   # kill-type 4 (hostile) or 0 (unknown/uncatalogued)


def attackable_sightings(state: GameState, attack_neutral: bool) -> list:
    """The monsters in the room the bot is allowed to *initiate* on, filtered by
    kill-type. Tolerates bare-string entries (treated as unknown/attackable)."""
    return [s for s in state.monsters_present
            if is_attackable(getattr(s, "kill_type", 0), attack_neutral)]


def select_attack_target(state: GameState, priority: list[str], attack_order: str,
                         attack_neutral: bool) -> str:
    """THE shared attack-target picker for every attack path (melee swing, nuke,
    backstab). Returns the chosen monster name, or "" if nothing should be hit.
    Only attackable (non-NPC) monsters are eligible to initiate on; once already
    in combat we fight back against whatever is here (a guard that engaged us)."""
    names = [getattr(s, "name", s) for s in attackable_sightings(state, attack_neutral)]
    if not names and state.in_combat:
        names = state.monster_names()
    return select_target(names, priority, attack_order)


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
        self.attack_neutral = cfg.attack_neutral
        self.sneak_cmd = sneak_cmd
        self.must_sneak = must_sneak
        self._sneaked_this_encounter = False
        self._sneak_confirmed = False
        self._engaged_target = ""   # monster we've already sent the attack at
        self._resting = False       # server has us resting (prompt shows (Resting))

    def on_line(self, line: str) -> None:
        # The MajorMUD prompt authoritatively flags resting: "[HP=..]: (Resting)".
        # Track it so we send 'rest' once instead of spamming it every tick.
        low = line.lower()
        if "[hp=" in low:
            self._resting = "(resting)" in low
        if not self.must_sneak:
            return
        if _SNEAK_OK_RE.search(line):
            self._sneak_confirmed = True
        elif _SNEAK_FAIL_RE.search(line):
            self._sneaked_this_encounter = False

    def decide(self, state: GameState) -> str | None:
        hp_pct = state.hp / state.max_hp if state.max_hp > 0 else 1.0
        mp_pct = state.mana / state.max_mana if state.max_mana > 0 else 1.0

        # Engage if already fighting OR an *attackable* monster is in the room.
        # Non-hostile creatures (kill-type 2 NPCs, neutral guards when
        # attack_neutral is off) never trigger an initiation — that's the fix for
        # auto-attacking town guards/shopkeepers.
        if state.in_combat or attackable_sightings(state, self.attack_neutral):
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
            # No monster to target: the in_combat flag can linger for a beat after
            # the kill, before *Combat Off* arrives. A bare "kill" is useless (the
            # server treats it as chat — `You say "kill"`), so wait instead.
            if not target:
                self._engaged_target = ""
                return None
            # Engage ONCE per target: MajorMUD auto-combat swings each round on
            # its own, so re-sending the attack restarts the round and wastes
            # swings. Re-send only when the target changes (e.g. after a kill).
            # The between-round *Combat Off*/*Combat Engaged* flicker leaves the
            # target unchanged, so it won't re-trigger.
            if target == self._engaged_target:
                return None
            self._engaged_target = target
            return f"{self.attack_cmd} {target}"

        # Not engaged: reset sneak flags for the next encounter
        self._sneaked_this_encounter = False
        self._sneak_confirmed = False
        self._engaged_target = ""

        if hp_pct < self.rest_threshold and not self._resting:
            return "rest"
        return None

    def _pick_target(self, state: GameState) -> str:
        return select_attack_target(state, self.monster_priority,
                                    self.attack_order, self.attack_neutral)
