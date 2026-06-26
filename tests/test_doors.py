from mmud.automation.doors import DoorMonitor
from mmud.config.schema import NavigationConfig


def test_closed_door_opens():
    m = DoorMonitor(NavigationConfig())
    cmds = m.handle("The door is closed.", last_move="w")
    assert cmds == ["open w"]


def test_move_blocked_by_closed_door_opens():
    # The move-failed wording (after a keyed unlock leaves the door CLOSED): the
    # black-star-key door says this, and we must send `open <dir>` to get through.
    m = DoorMonitor(NavigationConfig())
    assert m.handle("There is a closed door in that direction!", last_move="e") == ["open e"]


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


def test_closed_gate_opens():
    m = DoorMonitor(NavigationConfig())
    assert m.handle("The gate is closed!", last_move="w") == ["open w"]


def test_locked_gate_bashes_when_configured():
    m = DoorMonitor(NavigationConfig(bash_doors=True))
    assert m.handle("The iron gate is locked.", last_move="w") == ["bash w"]


def test_closed_escalates_to_bash_after_open_fails():
    # closed -> open; still closed -> bash (open didn't work, e.g. a barred gate)
    m = DoorMonitor(NavigationConfig(bash_doors=True))
    assert m.handle("The gate is closed!", last_move="w") == ["open w"]
    assert m.handle("The gate is closed!", last_move="w") == ["bash w"]


def test_bash_gives_up_after_max():
    m = DoorMonitor(NavigationConfig(bash_doors=True, bash_max=2))
    assert m.handle("The gate is locked.", last_move="w") == ["bash w"]
    assert m.handle("The gate is locked.", last_move="w") == ["bash w"]
    assert m.handle("The gate is locked.", last_move="w") == []   # gave up


def test_now_open_resets_and_passes_through():
    m = DoorMonitor(NavigationConfig(bash_doors=True))
    m.handle("The gate is closed!", last_move="w")     # open tried
    assert m.handle("The gate is now open.", last_move="w") is None
    assert m.handle("The gate is closed!", last_move="w") == ["open w"]  # reset
