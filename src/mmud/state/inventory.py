from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Inventory:
    carried_counts: dict[str, int] = field(default_factory=dict)
    worn: list[str] = field(default_factory=list)
    coins: dict[str, int] = field(default_factory=dict)   # denomination -> count
    encumbrance_pct: int = 0
    encumbrance_level: str = "none"   # none|light|medium|heavy

    @property
    def carried(self) -> list[str]:
        return list(self.carried_counts)
