from __future__ import annotations
from typing import Protocol
from mmud.state.game_state import GameState

# Priority slots mirroring megamud.exe's DoSomething order (lower = tried first).
# Phases 2-11 register deciders into these slots; unused slots simply have no decider.
PRIO_QUEUE = 0      # queued commands (login, path steps, user/remote commands)
PRIO_CURE = 10      # condition cures + panic            (Phase 2)
PRIO_FLEE = 20      # flee/run rules                     (Phase 4)
PRIO_SPELLS = 30    # heal/mana/attack/pre-attack/bless  (current SpellEngine)
PRIO_COMBAT = 40    # melee attack/rest                  (current CombatEngine)
PRIO_REST = 50      # rest task management               (Phase 4)
PRIO_REFRESH = 60   # stats/inventory refresh            (Phase 5)
PRIO_BLESS = 70     # bless scheduling split-out         (Phase 4)
PRIO_EQUIP = 80     # auto-equip                         (Phase 5)
PRIO_ITEMS = 90     # get/drop/stash/cash                (Phase 5)
PRIO_PARTY = 100    # party heal/wait/share              (Phase 10)
PRIO_TRAVEL = 110   # path following / goto              (Phase 6)
PRIO_SEARCH = 120   # hidden-exit searching              (Phase 6)


class Decider(Protocol):
    """One slot in the decision chain: return a command to send, or None to pass."""

    def decide(self, state: GameState) -> str | None: ...


class QueueDecider:
    """Slot 0 — drains GameState's command queue (login, path steps, user commands)."""

    def decide(self, state: GameState) -> str | None:
        return state.dequeue()


class DecisionEngine:
    """Priority-ordered decider chain with task pinning, after megamud's DoSomething.

    While a task is active, slots at or below the task's priority are skipped
    (the bot is busy at that level). A higher-priority decider that returns a
    command preempts: the task is aborted before the command is issued.
    """

    def __init__(self) -> None:
        self._slots: list[tuple[int, str, Decider]] = []

    def register(self, name: str, decider: Decider, priority: int) -> None:
        self._slots.append((priority, name, decider))
        self._slots.sort(key=lambda slot: slot[0])

    def next_command(self, state: GameState) -> str | None:
        for priority, _name, decider in self._slots:
            if state.task.is_active and priority >= state.task.priority:
                return None
            cmd = decider.decide(state)
            if cmd is not None:
                if state.task.is_active:
                    state.abort_task()
                return cmd
        return None
