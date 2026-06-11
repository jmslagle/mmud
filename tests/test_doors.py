from mmud.automation.doors import DoorMonitor
from mmud.config.schema import NavigationConfig


def test_closed_door_opens():
    m = DoorMonitor(NavigationConfig())
    cmds = m.handle("The door is closed.", last_move="w")
    assert cmds == ["open w"]


def test_locked_door_picks_when_able():
    m = DoorMonitor(NavigationConfig(can_pick_locks=True))
    assert m.handle("The door is locked.", last_move="n") == ["pick n"]


def test_locked_door_bashes_when_configured():
    m = DoorMonitor(NavigationConfig(bash_doors=True))
    assert m.handle("The door is locked.", last_move="n") == ["bash n"]


def test_locked_door_no_capability_gives_up():
    m = DoorMonitor(NavigationConfig())
    assert m.handle("The door is locked.", last_move="n") == []


def test_non_door_line_returns_none():
    m = DoorMonitor(NavigationConfig())
    assert m.handle("You can't go that way!", last_move="n") is None
