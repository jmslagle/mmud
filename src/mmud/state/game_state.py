from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from mmud.parser.matcher import MatchResult
from mmud.state.tasks import TaskState, TaskType


@dataclass
class Effect:
    name: str
    flags: int


@dataclass
class MonsterSighting:
    name: str
    count: int = 1
    exp_each: int = 0       # from MonsterDB; 0 if unknown
    record_id: int = -1     # MONSTERS.MD record id; -1 if unknown


class GameState:
    def __init__(self) -> None:
        self.current_room: str = ""
        self.hp: int = 0
        self.max_hp: int = 0
        self.mana: int = 0
        self.max_mana: int = 0
        self.active_effects: set[str] = set()
        self.conditions: set = set()   # set[Condition] — active status conditions
        self.monsters_present: list[MonsterSighting] = []
        self.players_present: list[str] = []
        self.move_history: deque[str] = deque(maxlen=20)  # recent movement cmds
        from mmud.state.inventory import Inventory
        self.inventory: Inventory = Inventory()
        # Starts clean: the bot marks it dirty on combat-end / get / equip so an
        # idle bot never polls `inv` unprompted.
        self.inventory_dirty: bool = False
        self.ground_items: list[str] = []
        self.ground_coins: dict[str, int] = {}
        self.in_combat: bool = False
        self._command_queue: deque[str] = deque()
        self.task: TaskState = TaskState()
        self.kills: int = 0
        self.exp: int = 0
        self.level: int = 0

        # Combat accuracy stats (from Ghidra gs+0x9500 block)
        self.combat_hits: int = 0
        self.combat_misses: int = 0
        self.combat_dmg_sum: int = 0
        self.combat_special: int = 0  # backstab/crit count
        self.monster_hits: int = 0
        self.monster_misses: int = 0
        self.backstab_attempts: int = 0
        self.backstab_successes: int = 0

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

    def monster_names(self) -> list[str]:
        return [s.name for s in self.monsters_present]

    def monster_count(self) -> int:
        return sum(s.count for s in self.monsters_present)

    def monster_exp_total(self) -> int:
        return sum(s.count * s.exp_each for s in self.monsters_present)

    def add_kill(self) -> None:
        self.kills += 1

    def set_exp(self, exp: int) -> None:
        self.exp = exp

    def set_level(self, level: int) -> None:
        self.level = level

    def record_hit(self, damage: int = 0) -> None:
        self.combat_hits += 1
        self.combat_dmg_sum += damage

    def record_miss(self) -> None:
        self.combat_misses += 1

    def record_monster_hit(self) -> None:
        self.monster_hits += 1

    def record_backstab(self, success: bool) -> None:
        self.backstab_attempts += 1
        if success:
            self.backstab_successes += 1

    @property
    def hit_pct(self) -> float:
        total = self.combat_hits + self.combat_misses + self.combat_special
        return (self.combat_hits / total * 100) if total > 0 else 0.0

    @property
    def avg_damage(self) -> float:
        return (self.combat_dmg_sum / self.combat_hits) if self.combat_hits > 0 else 0.0

    def reset_combat_stats(self) -> None:
        self.combat_hits = 0
        self.combat_misses = 0
        self.combat_dmg_sum = 0
        self.combat_special = 0
        self.monster_hits = 0
        self.monster_misses = 0
        self.backstab_attempts = 0
        self.backstab_successes = 0

    def enqueue(self, command: str) -> None:
        self._command_queue.append(command)

    def dequeue(self) -> str | None:
        return self._command_queue.popleft() if self._command_queue else None

    def begin_task(
        self,
        task_type: TaskType,
        priority: int,
        timeout_s: float = 0.0,
        payload: dict | None = None,
        now: float = 0.0,
    ) -> None:
        self.task = TaskState(
            type=task_type,
            priority=priority,
            deadline=(now + timeout_s) if timeout_s > 0.0 else 0.0,
            payload=payload or {},
        )

    def complete_task(self) -> None:
        self.task = TaskState()

    def abort_task(self) -> None:
        self.task = TaskState()
