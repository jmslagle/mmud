from __future__ import annotations
import re
from enum import Enum, auto
from mmud.automation.decision import PRIO_FLEE
from mmud.combat.combat import attackable_sightings, select_attack_target
from mmud.config.schema import CombatConfig, StealthConfig
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType

# Tune against the live server; record real wording in docs/testing-plan.md.
_HIDE_OK_RE = re.compile(r"slip into the shadows|you are hidden", re.IGNORECASE)
_HIDE_FAIL_RE = re.compile(r"fail to hide|can'?t hide", re.IGNORECASE)
_SNEAK_OK_RE = re.compile(r"move silently|begin to sneak", re.IGNORECASE)
_SNEAK_FAIL_RE = re.compile(r"fail to sneak|make a noise", re.IGNORECASE)
_BS_OK_RE = re.compile(r"plant your weapon|backstab.*for \d+", re.IGNORECASE)
_BS_FAIL_RE = re.compile(r"backstab attempt fails|fails? to find an opening", re.IGNORECASE)

_MAX_HIDE_TRIES = 2


class _Stage(Enum):
    IDLE = auto()
    HIDING = auto()      # hide sent, awaiting result
    HIDDEN = auto()
    SNEAKING = auto()
    SNUCK = auto()
    STABBING = auto()
    DONE = auto()        # success/failure handled; melee takes over
    RUN = auto()         # bs failed and run_if_bs_fails


class BackstabEngine:
    """track→hide→sneak→backstab, one command per decide(), line-driven."""

    def __init__(self, combat: CombatConfig, stealth: StealthConfig) -> None:
        self._enabled = combat.backstab
        self._run_if_fails = combat.run_if_bs_fails
        # Share the melee/nuke target policy so we never open on a guard/NPC.
        self._attack_neutral = combat.attack_neutral
        self._priority = [p.lower() for p in combat.monster_priority]
        self._attack_order = combat.attack_order
        # MegaMud hardcodes these verbs (literals "hide"/"sneak"/"bs" — see
        # docs/megamud-commands-reference.md §3); they are not configurable.
        self._hide_cmd = "hide"
        self._sneak_cmd = "sneak"
        self._stage = _Stage.IDLE
        self._hide_tries = 0

    def reset(self) -> None:
        self._stage = _Stage.IDLE
        self._hide_tries = 0

    def on_line(self, line: str) -> None:
        if self._stage is _Stage.HIDING:
            if _HIDE_OK_RE.search(line):
                self._stage = _Stage.HIDDEN
            elif _HIDE_FAIL_RE.search(line):
                self._hide_tries += 1
                self._stage = (_Stage.IDLE if self._hide_tries < _MAX_HIDE_TRIES
                               else _Stage.DONE)
        elif self._stage is _Stage.SNEAKING:
            if _SNEAK_OK_RE.search(line):
                self._stage = _Stage.SNUCK
            elif _SNEAK_FAIL_RE.search(line):
                self._stage = _Stage.DONE
        elif self._stage is _Stage.STABBING:
            if _BS_OK_RE.search(line):
                self._stage = _Stage.DONE
            elif _BS_FAIL_RE.search(line):
                self._stage = _Stage.RUN if self._run_if_fails else _Stage.DONE

    def decide(self, state: GameState) -> str | None:
        # Only open on an attackable target — NPCs/guards (kill-type 2, or neutral
        # when attack_neutral is off) never trigger a backstab.
        targets = attackable_sightings(state, self._attack_neutral)
        if not self._enabled or state.in_combat or not targets:
            if not targets and not state.in_combat:
                self.reset()        # no valid target: new encounter next time
            return None
        if self._stage is _Stage.IDLE:
            self._stage = _Stage.HIDING
            return self._hide_cmd
        if self._stage is _Stage.HIDDEN:
            self._stage = _Stage.SNEAKING
            return self._sneak_cmd
        if self._stage is _Stage.SNUCK:
            self._stage = _Stage.STABBING
            return f"bs {select_attack_target(state, self._priority, self._attack_order, self._attack_neutral)}"
        if self._stage is _Stage.RUN:
            self._stage = _Stage.DONE
            state.begin_task(TaskType.RUNNING, priority=PRIO_FLEE, timeout_s=15.0)
            return "flee"
        return None
