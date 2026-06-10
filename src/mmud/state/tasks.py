from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto


class TaskType(Enum):
    """Multi-step activities, mirroring megamud.exe's task state machine."""
    IDLE = auto()
    GETTING = auto()
    DROPPING = auto()
    STASHING = auto()
    EQUIPPING = auto()
    SEARCHING = auto()
    RUNNING = auto()
    BLESSING = auto()
    CASTING = auto()
    RESTING = auto()
    WAITING = auto()
    RELOGGING = auto()
    HANGING = auto()
    TRAINING = auto()


@dataclass
class TaskState:
    type: TaskType = TaskType.IDLE
    priority: int = 0          # decision-chain slot that owns this task
    deadline: float = 0.0      # monotonic seconds; 0.0 = no deadline
    payload: dict = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.type is not TaskType.IDLE

    def expired(self, now: float) -> bool:
        return self.is_active and self.deadline > 0.0 and now >= self.deadline
