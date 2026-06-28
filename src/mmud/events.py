from __future__ import annotations
from dataclasses import dataclass
from typing import Callable


@dataclass
class LineReceived:
    line: str

@dataclass
class HpChanged:
    hp: int
    max_hp: int

@dataclass
class MpChanged:
    mp: int
    max_mp: int

@dataclass
class RoomChanged:
    code: str
    name: str

@dataclass
class EffectApplied:
    name: str
    flags: int

@dataclass
class EffectRemoved:
    name: str

@dataclass
class CombatChanged:
    in_combat: bool

@dataclass
class ConversationReceived:
    channel: str   # "tell" | "shout" | "party" | "gossip"
    sender: str
    text: str

@dataclass
class PlayerSeen:
    name: str
    alignment: str = ""   # WHO alignment column
    title: str = ""        # WHO class/rank title

@dataclass
class PathStarted:
    name: str

@dataclass
class PathStepped:
    command: str
    lap: int

@dataclass
class SessionStatUpdated:
    key: str
    value: str

@dataclass
class MonstersSeen:
    monsters: list[str]   # monster names parsed from room content

@dataclass
class TaskChanged:
    task_type: str   # TaskType name, e.g. "RESTING"
    status: str      # "started" | "completed" | "aborted" | "timeout"

@dataclass
class ConditionChanged:
    name: str      # Condition name, e.g. "POISONED"
    active: bool   # True = onset, False = recovered

@dataclass
class HangupTriggered:
    reason: str

@dataclass
class DbImported:
    added: int
    updated: int
    collisions: int

@dataclass
class DbCollision:
    db: str
    record_id: int

@dataclass
class TravelResynced:
    from_step: int
    to_step: int

@dataclass
class TravelEnded:
    reason: str   # "arrived" | "lost" | "blocked" | "stopped"


@dataclass
class TravelLost:
    """The path cursor saw 3 consecutive genuine id mismatches (MegaMud's
    state+0x152d > 2 with no re-path hit). The bot STOPs rather than blind-wander."""
    step: int   # 1-based cursor position when Lost fired


@dataclass
class ConfigChanged:
    section: str   # config section name, e.g. "combat"
    field: str     # field name within the section
    value: object  # the new value, already type-coerced


@dataclass
class RawOutput:
    data: str   # raw IAC-stripped server text (ANSI intact) for the terminal emulator


@dataclass
class ScreenUpdated:
    pass        # signal: the terminal emulator's screen changed; re-render


class GameEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[type, list[Callable]] = {}

    def subscribe(self, event_type: type, callback: Callable) -> None:
        self._subscribers.setdefault(event_type, []).append(callback)

    def post(self, event: object) -> None:
        for cb in self._subscribers.get(type(event), []):
            cb(event)
