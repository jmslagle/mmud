from __future__ import annotations
import re
import time
from mmud.config.schema import CombatConfig
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType
from mmud.automation.decision import PRIO_REST

_REST_FULL = 0.95       # recover HP/mana to ~this fraction before resuming
_REST_TIMEOUT_S = 180.0  # safety net so a misparsed max can't pin us resting forever

_SNEAK_OK_RE = re.compile(r"move silently|begin to sneak", re.IGNORECASE)
_SNEAK_FAIL_RE = re.compile(r"fail to sneak|make a noise", re.IGNORECASE)


def activity_reason(state: GameState, cmd, mana_attack_pct: float,
                    rest_threshold: float, rest_mana_pct: float = 0.0) -> str:
    """Why the bot is intentionally idle this tick (so a wait doesn't look frozen).
    "" when it's acting or has nothing to wait on."""
    if cmd is not None:
        return ""
    mp_pct = state.mana / state.max_mana if state.max_mana > 0 else 1.0
    hp_pct = state.hp / state.max_hp if state.max_hp > 0 else 1.0
    if state.task.is_active and state.task.type is TaskType.RESTING:
        return "resting"
    if ((state.in_combat or state.monsters_present)
            and state.max_mana > 0 and mp_pct < mana_attack_pct):
        return "waiting for mana"
    if not state.in_combat and not state.monsters_present:
        if hp_pct < rest_threshold:
            return "resting"
        if rest_mana_pct > 0 and state.max_mana > 0 and mp_pct < rest_mana_pct:
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


_REVERSE = {"n": "s", "s": "n", "e": "w", "w": "e", "ne": "sw", "sw": "ne",
            "nw": "se", "se": "nw", "u": "d", "d": "u"}


class EmergencyDecider:
    """Critical-HP escape (our tier — MegaMud has no recall). When HP drops to/below
    `emergency_threshold` (incl. going NEGATIVE), send the configurable `emergency_cmd`
    (e.g. "sys go sil") ONCE — regardless of combat state or the combat toggle, so "run"
    mode still bails when dying. Re-arms once HP recovers above the threshold. Registered
    at PRIO_EMERGENCY (above cures/flee/combat) and never in the combat-toggle's
    disabled slots."""

    def __init__(self, config: CombatConfig | None = None) -> None:
        cfg = config or CombatConfig()
        self._cmd = cfg.emergency_cmd.strip()
        self._threshold = cfg.emergency_threshold
        self._sent = False

    def decide(self, state: GameState) -> str | None:
        if not self._cmd or self._threshold <= 0:
            return None
        if state.max_hp > 0:
            hp_pct = state.hp / state.max_hp
        else:                                  # max unknown: only act on actual ≤0 HP
            hp_pct = 0.0 if state.hp <= 0 else 1.0
        if hp_pct > self._threshold:
            self._sent = False                 # recovered -> re-arm
            return None
        if self._sent:
            return None                        # already bailed; don't spam the recall
        self._sent = True
        return self._cmd


class CombatEngine:
    def __init__(self, config: CombatConfig | None = None,
                 sneak_cmd: str = "", must_sneak: bool = False) -> None:
        cfg = config or CombatConfig()
        self.attack_cmd = cfg.attack_cmd
        self.flee_threshold = cfg.flee_threshold
        self.flee_rooms = max(1, cfg.flee_rooms)
        self.run_backwards = cfg.run_backwards
        self.rest_threshold = cfg.rest_threshold
        self.rest_mana_pct = cfg.rest_mana_pct
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
        self._fleeing = False       # currently running away (low HP in combat)
        self._flee_retrace: list[str] = []   # precomputed backtrack moves (run_backwards)
        self._resting = False       # server has us resting (prompt shows (Resting))
        self._rest_pending = False  # sent 'rest', awaiting the next prompt to confirm
        self._recovering = False    # recovering HP/mana -> keep resting until full

    def on_line(self, line: str) -> None:
        # The MajorMUD prompt authoritatively flags resting: "[HP=..]: (Resting)".
        # Track it so we send 'rest' once instead of spamming it every tick.
        low = line.lower()
        if "[hp=" in low:
            self._resting = "(resting)" in low
            # A prompt came back, so the prior 'rest' resolved — re-arm. Without
            # this debounce we re-issued 'rest' on every line (echoes, etc.) in the
            # window before the "(Resting)" prompt and flooded the server.
            self._rest_pending = False
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
            if state.max_hp > 0 and hp_pct <= self.flee_threshold:
                return self._flee(state, hp_pct)
            # MegaMud melees below ManaAttack% (it doesn't wait) — the spell engine
            # (higher priority) declines to cast there, so the combat engine just
            # swings. No mana gate here.
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

        # Not engaged (safe): reset the flee episode + sneak flags for the next encounter.
        # With danger gone, the rest-to-recover block below brings HP/mana back to full.
        self._fleeing = False
        self._flee_retrace = []
        self._sneaked_this_encounter = False
        self._sneak_confirmed = False
        self._engaged_target = ""

        # Rest to recover (out of combat). Like MegaMud (combat_rest_decide), HOLD
        # and rest until HP & mana are back to FULL — and RESUME resting if a buff
        # cast (or anything) interrupts. Recovery is tracked in our own `_recovering`
        # flag, NOT the RESTING task: a cast is higher priority than rest, so the
        # engine aborts the task when it casts; without the flag we'd stop resting
        # the moment mana climbed back over the (lower) start threshold.
        hp_done = hp_pct >= _REST_FULL
        mana_done = state.max_mana <= 0 or mp_pct >= _REST_FULL
        if self._recovering and hp_done and mana_done:
            self._recovering = False        # fully recovered -> let the loop resume
            self._rest_pending = False
            if state.task.is_active and state.task.type is TaskType.RESTING:
                state.complete_task()
            return None
        hp_low = hp_pct < self.rest_threshold
        mana_low = (self.rest_mana_pct > 0 and state.max_mana > 0
                    and mp_pct < self.rest_mana_pct)
        if self._recovering or hp_low or mana_low:
            self._recovering = True
            # Keep the RESTING task alive (blocks travel) — re-begin it if a cast
            # aborted it, so we resume resting rather than walking off half-recovered.
            if not (state.task.is_active and state.task.type is TaskType.RESTING):
                state.begin_task(TaskType.RESTING, priority=PRIO_REST,
                                 timeout_s=_REST_TIMEOUT_S, now=time.monotonic())
            return self._rest_cmd()
        return None

    def _flee(self, state: GameState, hp_pct: float) -> str | None:
        """Run away when low on HP. MegaMud never sends the literal "flee" — it WALKS OUT
        an exit (one room per turn), retracing the way it came if RunBackwards, then rests
        once safe. (The critical-HP `emergency_cmd` is a separate EmergencyDecider that
        fires at a lower threshold, above this in priority.)"""
        if not self._fleeing:               # start of a run episode
            self._fleeing = True
            self._flee_retrace = []
            if self.run_backwards:
                recent = list(state.move_history)[-self.flee_rooms:]
                self._flee_retrace = [_REVERSE[m] for m in reversed(recent) if m in _REVERSE]
        if self._flee_retrace:              # retrace the moves we came in by
            return self._flee_retrace.pop(0)
        exits = list(state.last_exits or [])
        if exits:                           # walk out a real exit, away from where we came
            last = state.move_history[-1] if state.move_history else ""
            rev = _REVERSE.get(last)
            return next((e for e in exits if e != rev), exits[0])
        return "flee"                       # no known exit -> MajorMUD's flee verb (last resort)

    def _rest_cmd(self) -> str | None:
        """Issue `rest` at most once per prompt cycle. We're already resting, or
        we've sent `rest` and are waiting for the next [HP=..] prompt to confirm —
        either way, don't re-send (the server rate-limits a flood of `rest`)."""
        if self._resting or self._rest_pending:
            return None
        self._rest_pending = True
        return "rest"

    def _pick_target(self, state: GameState) -> str:
        return select_attack_target(state, self.monster_priority,
                                    self.attack_order, self.attack_neutral)
