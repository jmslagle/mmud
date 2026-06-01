from mmud.state.game_state import GameState, Effect
from mmud.data.messages import MessagePattern
from mmud.parser.matcher import MatchResult


def _make_result(name, flags, is_apply, captures=None):
    p = MessagePattern(name=name, flags=flags, third_field=0,
                       apply_message="x", remove_message="y")
    return MatchResult(pattern=p, is_apply=is_apply, captures=captures or {})


def test_initial_state():
    gs = GameState()
    assert gs.current_room == ""
    assert gs.hp == 0
    assert gs.max_hp == 0
    assert gs.mana == 0
    assert gs.active_effects == set()


def test_apply_effect():
    gs = GameState()
    gs.apply_match(_make_result("chain", 0x10, is_apply=True))
    assert "chain" in gs.active_effects


def test_remove_effect():
    gs = GameState()
    gs.apply_match(_make_result("chain", 0x10, is_apply=True))
    gs.apply_match(_make_result("chain", 0x10, is_apply=False))
    assert "chain" not in gs.active_effects


def test_hp_update():
    gs = GameState()
    gs.set_hp(80, 100)
    assert gs.hp == 80
    assert gs.max_hp == 100


def test_room_update():
    gs = GameState()
    gs.set_room("HOME")
    assert gs.current_room == "HOME"


def test_command_queue():
    gs = GameState()
    gs.enqueue("n")
    gs.enqueue("e")
    assert gs.dequeue() == "n"
    assert gs.dequeue() == "e"
    assert gs.dequeue() is None
