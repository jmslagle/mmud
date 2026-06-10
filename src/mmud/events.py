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
    level: str
    rep: str
    gang: str

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


class GameEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[type, list[Callable]] = {}

    def subscribe(self, event_type: type, callback: Callable) -> None:
        self._subscribers.setdefault(event_type, []).append(callback)

    def post(self, event: object) -> None:
        for cb in self._subscribers.get(type(event), []):
            cb(event)
