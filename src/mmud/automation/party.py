from __future__ import annotations
import re
import time
from typing import Callable
from mmud.automation.decision import PRIO_PARTY
from mmud.config.schema import PartyConfig, PlayerRule
from mmud.state.game_state import GameState
from mmud.state.inventory import WEALTH_RATES
from mmud.state.tasks import TaskType

HEAL_TIMEOUT_S = 5.0

# Reconstructed; live-tune in docs/testing-plan.md.
_INVITE_RE = re.compile(r"(\w+) has invited you to join", re.IGNORECASE)
_LEADER_HIT_RE = re.compile(
    r"\b(?:swings?|attacks?|hits?|strikes?|slashes?|casts?)\b", re.IGNORECASE)


class InviteMonitor:
    """Auto-accept party invites from friend=True players."""

    def __init__(self, rules: list[PlayerRule]) -> None:
        self._friends = {r.name.lower() for r in rules if r.friend}

    def check(self, line: str) -> str | None:
        m = _INVITE_RE.search(line)
        if m and m.group(1).lower() in self._friends:
            return f"join {m.group(1)}"
        return None


class PartyDecider:
    """PRIO_PARTY slot: wait/resume -> heal -> bless -> share -> status."""

    def __init__(self, config: PartyConfig, rules: list[PlayerRule],
                 now: Callable[[], float] = time.monotonic) -> None:
        self._cfg = config
        self._dont_heal = {r.name.lower() for r in rules if r.dont_heal}
        self._now = now
        self._bless_last = [float("-inf")] * len(config.bless)
        self._status_last = float("-inf")
        self._waiting = False
        self._share_queue: list[str] = []
        self._attack_with_leader = config.attack_with_leader
        self._leader_engaged = False
        self._leader_name = ""

    @property
    def leader_engaged(self) -> bool:
        return self._leader_engaged

    def on_line(self, line: str) -> None:
        if not self._leader_name:
            return
        if (line.lower().startswith(self._leader_name.lower())
                and _LEADER_HIT_RE.search(line)):
            self._leader_engaged = True

    def decide(self, state: GameState) -> str | None:
        now = self._now()
        self._leader_name = state.party_leader
        if not state.monsters_present:
            self._leader_engaged = False
        # The wait protocol is gated on party automation being IN USE
        # (heal_spell or status_cmd) — wait_cmd/wait_hp_pct have non-empty
        # defaults, and a pure-default config must stay inert.
        engaged = bool(self._cfg.heal_spell or self._cfg.status_cmd)
        # 1) wait/resume protocol
        if engaged and self._cfg.wait_cmd and self._cfg.wait_hp_pct > 0 \
                and state.party:
            low = [m for m in state.party
                   if m.hp_pct < self._cfg.wait_hp_pct * 100]
            if low and not self._waiting:
                self._waiting = True
                state.begin_task(TaskType.WAITING, priority=PRIO_PARTY,
                                 timeout_s=self._cfg.wait_max_seconds, now=now)
                return self._cfg.wait_cmd
            if self._waiting:
                if low:
                    return None                  # keep waiting
                self._waiting = False
                if state.task.type is TaskType.WAITING:
                    state.complete_task()
                return self._cfg.resume_cmd
        # 2) heal the lowest eligible member
        if self._cfg.heal_spell and state.party:
            hurt = [m for m in state.party
                    if m.hp_pct < self._cfg.heal_hp_pct * 100
                    and m.name.lower() not in self._dont_heal]
            if hurt:
                target = min(hurt, key=lambda m: m.hp_pct)
                state.begin_task(TaskType.CASTING, priority=PRIO_PARTY,
                                 timeout_s=HEAL_TIMEOUT_S, now=now)
                return f"{self._cfg.heal_spell} {target.name}"
        # 3) party bless slots
        if state.party:
            for i, bless in enumerate(self._cfg.bless):
                if bless.cmd and now - self._bless_last[i] >= bless.wait_seconds:
                    self._bless_last[i] = now
                    return bless.cmd
        # 4) share cash
        if self._cfg.share_cash and state.party and not state.inventory_dirty:
            if not self._share_queue and state.inventory.coins:
                self._share_queue = [
                    f"share {n} {denom}"
                    for denom, n in sorted(
                        state.inventory.coins.items(),
                        key=lambda kv: -WEALTH_RATES.get(kv[0], 0))
                    if n > 0]
            if self._share_queue:
                cmd = self._share_queue.pop(0)
                if not self._share_queue:
                    state.inventory_dirty = True   # re-sync; blocks re-share
                return cmd
        # 5) periodic party status refresh
        if (self._cfg.status_cmd
                and now - self._status_last >= self._cfg.status_interval_s):
            self._status_last = now
            return self._cfg.status_cmd
        return None
