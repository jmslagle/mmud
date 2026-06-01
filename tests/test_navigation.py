from mmud.data.paths import GamePath, PathStep
from mmud.navigation.navigator import Navigator
from mmud.state.game_state import GameState


def _make_path(from_code, to_code, commands):
    steps = [PathStep(hex_id="0000", command=c) for c in commands]
    return GamePath(from_code=from_code, from_region="", from_name="",
                    to_code=to_code, to_region="", to_name="", npc="", steps=steps)


def test_get_known_path():
    nav = Navigator([_make_path("HOME", "CLKR", ["s"])])
    path = nav.get_path("HOME", "CLKR")
    assert path is not None
    assert len(path.steps) == 1


def test_get_unknown_path_returns_none():
    nav = Navigator([])
    assert nav.get_path("HOME", "CLKR") is None


def test_execute_path_enqueues_commands():
    nav = Navigator([_make_path("A", "B", ["n", "e", "n"])])
    gs = GameState()
    path = nav.get_path("A", "B")
    nav.execute_path(path, gs)
    assert gs.dequeue() == "n"
    assert gs.dequeue() == "e"
    assert gs.dequeue() == "n"
    assert gs.dequeue() is None


def test_load_from_directory(data_dir):
    nav = Navigator.from_directory(data_dir)
    assert len(nav._paths) > 100
