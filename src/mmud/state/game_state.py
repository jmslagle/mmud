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
    kill_type: int = 0      # MONSTERS.MD kill-type tier (disk 0x25): 2=good NPC,
                            # 3=neutral, 4=hostile, 5=special; 0=unknown/learned


@dataclass
class DamageStat:
    """Per-hit-type damage accumulator for MegaMud's Combat Accuracy panel
    ("R:min-max A:avg"). One per category: hit/extra/crit/backstab/cast/round."""
    count: int = 0
    dmg_min: int = 0
    dmg_max: int = 0
    dmg_sum: int = 0

    def add(self, dmg: int) -> None:
        if self.count == 0 or dmg < self.dmg_min:
            self.dmg_min = dmg
        if dmg > self.dmg_max:
            self.dmg_max = dmg
        self.count += 1
        self.dmg_sum += dmg

    @property
    def avg(self) -> float:
        return self.dmg_sum / self.count if self.count else 0.0

    @property
    def range_str(self) -> str:
        return f"{self.dmg_min}-{self.dmg_max}" if self.count else "0-0"


_DMG_KINDS = ("hit", "extra", "crit", "backstab", "cast", "round")


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
        self.current_hex: str = ""        # room hex id when known
        self.last_exits: list[str] = []   # commands from the last exits line
        self.party: list = []             # list[PartyMember]
        self.party_leader: str = ""
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
        self.exp_needed: int = 0   # exp remaining to next level (from stat/exp screen)
        self.level: int = 0

        # Combat accuracy stats (from Ghidra gs+0x9500 block)
        self.combat_hits: int = 0
        self.combat_misses: int = 0
        self.combat_dmg_sum: int = 0
        self.combat_special: int = 0  # backstab/crit count
        # Per-hit-type damage ranges for the Combat Accuracy panel.
        self.dmg: dict[str, DamageStat] = {k: DamageStat() for k in _DMG_KINDS}
        self.monster_hits: int = 0
        self.monster_misses: int = 0
        self.backstab_attempts: int = 0
        self.backstab_successes: int = 0
        # Stealth / evasion stats (web-panel facing)
        self.sneak_attempts: int = 0
        self.sneak_successes: int = 0
        self.dodges: int = 0
        self.ran_away: int = 0
        self.health_low: int = 0

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

    def replace_monsters(self, sightings: list[MonsterSighting]) -> None:
        """The room's `Also here:` list is the authoritative roster — replace,
        dropping stale entries (mirrors MegaMud's room_entity_classify_all)."""
        self.monsters_present = list(sightings)

    def add_monster(self, sighting: MonsterSighting) -> None:
        """Append-if-absent on an arrival line (exact-name dedupe)."""
        if not any(s.name.lower() == sighting.name.lower()
                   for s in self.monsters_present):
            self.monsters_present.append(sighting)

    def remove_monster(self, name: str) -> bool:
        """Remove one sighting by EXACT (case-insensitive) name — decrement its
        count, drop it when it reaches 0. Exact match so "kobold thief" never
        removes "angry kobold thief". Returns True if something was removed."""
        key = name.strip().lower()
        for i, s in enumerate(self.monsters_present):
            if s.name.lower() == key:
                if s.count > 1:
                    s.count -= 1
                else:
                    del self.monsters_present[i]
                return True
        return False

    def monster_count(self) -> int:
        return sum(s.count for s in self.monsters_present)

    def monster_exp_total(self) -> int:
        return sum(s.count * s.exp_each for s in self.monsters_present)

    def add_kill(self) -> None:
        self.kills += 1

    def set_exp(self, exp: int) -> None:
        self.exp = exp

    def set_exp_needed(self, exp_needed: int) -> None:
        self.exp_needed = exp_needed

    def set_level(self, level: int) -> None:
        self.level = level

    def record_hit(self, damage: int = 0, kind: str = "hit") -> None:
        """Record a landed player attack. `kind` is hit/extra/crit/backstab/cast
        for the per-type Combat Accuracy ranges."""
        self.combat_hits += 1
        self.combat_dmg_sum += damage
        if kind in self.dmg:
            self.dmg[kind].add(damage)
        if kind in ("crit", "backstab", "extra"):
            self.combat_special += 1

    def record_crit(self, damage: int = 0) -> None:
        self.record_hit(damage, kind="crit")

    def record_cast(self, damage: int = 0) -> None:
        self.record_hit(damage, kind="cast")

    def record_miss(self) -> None:
        self.combat_misses += 1

    def record_monster_hit(self, damage: int = 0) -> None:
        self.monster_hits += 1
        self.dmg["round"].add(damage)   # damage taken -> "Round" range

    def record_backstab(self, success: bool) -> None:
        self.backstab_attempts += 1
        if success:
            self.backstab_successes += 1

    def record_sneak(self, success: bool) -> None:
        self.sneak_attempts += 1
        if success:
            self.sneak_successes += 1

    def record_dodge(self) -> None:
        self.dodges += 1

    def record_ran_away(self) -> None:
        self.ran_away += 1

    def record_health_low(self) -> None:
        self.health_low += 1

    @property
    def hit_pct(self) -> float:
        total = self.combat_hits + self.combat_misses + self.combat_special
        return (self.combat_hits / total * 100) if total > 0 else 0.0

    @property
    def sneak_pct(self) -> float:
        return (self.sneak_successes * 100 / self.sneak_attempts) if self.sneak_attempts > 0 else 0.0

    @property
    def dodge_pct(self) -> float:
        total = self.dodges + self.monster_hits
        return (self.dodges * 100 / total) if total > 0 else 0.0

    @property
    def backstab_pct(self) -> float:
        return (self.backstab_successes * 100 / self.backstab_attempts) if self.backstab_attempts > 0 else 0.0

    @property
    def avg_damage(self) -> float:
        return (self.combat_dmg_sum / self.combat_hits) if self.combat_hits > 0 else 0.0

    def combat_accuracy(self) -> dict:
        """MegaMud Combat Accuracy panel: per-type pct + R:min-max + A:avg.
        Percentages are over total swings (hits+crits+extra+misses; backstab is a
        separate success/attempt rate; cast over cast attempts)."""
        swings = (self.dmg["hit"].count + self.dmg["crit"].count
                  + self.dmg["extra"].count + self.combat_misses)

        def row(kind: str, pct: float) -> dict:
            d = self.dmg[kind]
            return {"pct": round(pct, 1), "range": d.range_str, "avg": round(d.avg)}

        def share(kind: str) -> float:
            return self.dmg[kind].count * 100 / swings if swings else 0.0

        return {
            "miss_pct": round(self.combat_misses * 100 / swings, 1) if swings else 0.0,
            "hit": row("hit", share("hit")),
            "extra": row("extra", share("extra")),
            "crit": row("crit", share("crit")),
            "backstab": row("backstab", self.backstab_pct),
            "cast": row("cast", 0.0),
            "round": {"range": self.dmg["round"].range_str,
                      "avg": round(self.dmg["round"].avg)},
        }

    def reset_combat_stats(self) -> None:
        for d in self.dmg.values():
            d.count = d.dmg_min = d.dmg_max = d.dmg_sum = 0
        self.combat_hits = 0
        self.combat_misses = 0
        self.combat_dmg_sum = 0
        self.combat_special = 0
        self.monster_hits = 0
        self.monster_misses = 0
        self.backstab_attempts = 0
        self.backstab_successes = 0
        self.sneak_attempts = 0
        self.sneak_successes = 0
        self.dodges = 0
        self.ran_away = 0
        self.health_low = 0

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
