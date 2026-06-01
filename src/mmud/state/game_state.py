from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from mmud.parser.matcher import MatchResult


@dataclass
class Effect:
    name: str
    flags: int


class GameState:
    def __init__(self) -> None:
        self.current_room: str = ""
        self.hp: int = 0
        self.max_hp: int = 0
        self.mana: int = 0
        self.max_mana: int = 0
        self.active_effects: set[str] = set()
        self.monsters_present: list[str] = []
        self.in_combat: bool = False
        self._command_queue: deque[str] = deque()

    def apply_match(self, result: MatchResult) -> None:
        name = result.pattern.name
        if result.is_apply:
            self.active_effects.add(name)
        else:
            self.active_effects.discard(name)

    def set_hp(self, hp: int, max_hp: int) -> None:
        self.hp = hp
        self.max_hp = max_hp

    def set_mana(self, mana: int, max_mana: int) -> None:
        self.mana = mana
        self.max_mana = max_mana

    def set_room(self, code: str) -> None:
        self.current_room = code

    def set_combat(self, in_combat: bool) -> None:
        self.in_combat = in_combat

    def enqueue(self, command: str) -> None:
        self._command_queue.append(command)

    def dequeue(self) -> str | None:
        return self._command_queue.popleft() if self._command_queue else None
