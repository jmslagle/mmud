from mmud.events import (
    GameEventBus, LineReceived, HpChanged, MpChanged, RoomChanged,
    EffectApplied, EffectRemoved, CombatChanged, ConversationReceived,
    PlayerSeen, PathStarted, PathStepped, SessionStatUpdated,
)

def test_subscribe_and_post():
    bus = GameEventBus()
    received = []
    bus.subscribe(LineReceived, received.append)
    bus.post(LineReceived(line="hello world"))
    assert received == [LineReceived(line="hello world")]

def test_multiple_subscribers_same_event():
    bus = GameEventBus()
    r1, r2 = [], []
    bus.subscribe(HpChanged, r1.append)
    bus.subscribe(HpChanged, r2.append)
    bus.post(HpChanged(hp=100, max_hp=200))
    assert len(r1) == 1 and len(r2) == 1

def test_different_event_types_dont_cross():
    bus = GameEventBus()
    received = []
    bus.subscribe(HpChanged, received.append)
    bus.post(LineReceived(line="wrong type"))
    assert received == []

def test_post_with_no_subscribers_does_not_raise():
    bus = GameEventBus()
    bus.post(LineReceived(line="nobody listening"))

def test_all_event_types_constructible():
    LineReceived(line="x")
    HpChanged(hp=10, max_hp=100)
    MpChanged(mp=5, max_mp=50)
    RoomChanged(code="HOME", name="The Homely Hearth")
    EffectApplied(name="chain", flags=0x10)
    EffectRemoved(name="chain")
    CombatChanged(in_combat=True)
    ConversationReceived(channel="tell", sender="BumbleBee", text="hi")
    PlayerSeen(name="BumbleBee", level="L5-9", rep="Neutral", gang="")
    PathStarted(name="RHU2LOOP")
    PathStepped(command="e", lap=58)
    SessionStatUpdated(key="kills", value="694")

from mmud.events import MonstersSeen

def test_monsters_seen_constructible():
    e = MonstersSeen(monsters=["orc warrior", "goblin scout"])
    assert e.monsters == ["orc warrior", "goblin scout"]


from mmud.events import TaskChanged


def test_task_changed_constructible():
    e = TaskChanged(task_type="RESTING", status="timeout")
    assert e.task_type == "RESTING"
    assert e.status == "timeout"


def test_raw_output_event_fields():
    from mmud.events import RawOutput
    e = RawOutput(data="\x1b[1;1Hhi")
    assert e.data == "\x1b[1;1Hhi"


def test_screen_updated_event_constructs():
    from mmud.events import ScreenUpdated
    e = ScreenUpdated()
    assert isinstance(e, ScreenUpdated)


def test_raw_output_and_screen_updated_dispatch_on_bus():
    from mmud.events import GameEventBus, RawOutput, ScreenUpdated
    bus = GameEventBus()
    seen: list[object] = []
    bus.subscribe(RawOutput, seen.append)
    bus.subscribe(ScreenUpdated, seen.append)
    bus.post(RawOutput(data="x"))
    bus.post(ScreenUpdated())
    assert len(seen) == 2
    assert isinstance(seen[0], RawOutput)
    assert isinstance(seen[1], ScreenUpdated)
