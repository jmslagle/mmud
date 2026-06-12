from __future__ import annotations
import pytest
import mmud.events as ev
from mmud.web.serialize import serialize_event

CASES = [
    (ev.LineReceived("hi"), {"type": "LineReceived", "line": "hi"}),
    (ev.HpChanged(10, 20), {"type": "HpChanged", "hp": 10, "max_hp": 20}),
    (ev.MpChanged(3, 7), {"type": "MpChanged", "mp": 3, "max_mp": 7}),
    (ev.RoomChanged("ABCD", "A Room"), {"type": "RoomChanged", "code": "ABCD", "name": "A Room"}),
    (ev.EffectApplied("bless", 4), {"type": "EffectApplied", "name": "bless", "flags": 4}),
    (ev.EffectRemoved("bless"), {"type": "EffectRemoved", "name": "bless"}),
    (ev.CombatChanged(True), {"type": "CombatChanged", "in_combat": True}),
    (ev.ConversationReceived("tell", "Bob", "hi"), {"type": "ConversationReceived", "channel": "tell", "sender": "Bob", "text": "hi"}),
    (ev.PlayerSeen("Bob", "L5", "Neutral", "Gang"), {"type": "PlayerSeen", "name": "Bob", "level": "L5", "rep": "Neutral", "gang": "Gang"}),
    (ev.PathStarted("loop1"), {"type": "PathStarted", "name": "loop1"}),
    (ev.PathStepped("n", 2), {"type": "PathStepped", "command": "n", "lap": 2}),
    (ev.SessionStatUpdated("kills", "3"), {"type": "SessionStatUpdated", "key": "kills", "value": "3"}),
    (ev.MonstersSeen(["rat", "bat"]), {"type": "MonstersSeen", "monsters": ["rat", "bat"]}),
    (ev.TaskChanged("RESTING", "started"), {"type": "TaskChanged", "task_type": "RESTING", "status": "started"}),
    (ev.ConditionChanged("POISONED", True), {"type": "ConditionChanged", "name": "POISONED", "active": True}),
    (ev.HangupTriggered("death"), {"type": "HangupTriggered", "reason": "death"}),
    (ev.DbImported(1, 2, 3), {"type": "DbImported", "added": 1, "updated": 2, "collisions": 3}),
    (ev.DbCollision("monsters", 42), {"type": "DbCollision", "db": "monsters", "record_id": 42}),
    (ev.TravelResynced(1, 4), {"type": "TravelResynced", "from_step": 1, "to_step": 4}),
    (ev.TravelEnded("arrived"), {"type": "TravelEnded", "reason": "arrived"}),
    # ConfigChanged is serializable too (general serializer); it is intentionally
    # NOT in the web server's broadcast list (_EVENT_TYPES) — config edits aren't game state.
    (ev.ConfigChanged("combat", "attack_cmd", "bash"), {"type": "ConfigChanged", "section": "combat", "field": "attack_cmd", "value": "bash"}),
]


@pytest.mark.parametrize("event,expected", CASES)
def test_serialize_event(event, expected):
    assert serialize_event(event) == expected


def test_every_event_type_is_covered():
    covered = {type(e).__name__ for e, _ in CASES}
    declared = {
        name for name in dir(ev)
        if name[0].isupper() and name not in {"GameEventBus", "Callable"}
    }
    assert declared <= covered, f"uncovered events: {declared - covered}"


def test_non_dataclass_raises():
    with pytest.raises(TypeError):
        serialize_event(object())
