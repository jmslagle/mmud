from mmud.navigation.navigator import Navigator
from mmud.data.paths import GamePath, PathStep
from mmud.state.game_state import GameState


def _path(fc, tc, steps):
    return GamePath(
        from_code=fc, from_region="", from_name="",
        to_code=tc, to_region="", to_name="", npc="",
        steps=[PathStep(hex_id="", command=c) for c in steps],
    )


def test_get_path_finds_registered_path():
    p = _path("AAAA", "BBBB", ["n", "e"])
    nav = Navigator([p])
    assert nav.get_path("AAAA", "BBBB") is p


def test_get_path_unknown_returns_none():
    nav = Navigator([_path("AAAA", "BBBB", ["n"])])
    assert nav.get_path("AAAA", "ZZZZ") is None
    assert nav.get_path("ZZZZ", "BBBB") is None


def test_navigate_to_returns_same_path_as_get_path():
    p = _path("AAAA", "BBBB", ["s"])
    nav = Navigator([p])
    assert nav.navigate_to("AAAA", "BBBB") is p
    assert nav.navigate_to("AAAA", "CCCC") is None


def test_execute_path_enqueues_commands_in_order():
    p = _path("AAAA", "BBBB", ["n", "e", "open door", "w"])
    nav = Navigator([p])
    state = GameState()
    nav.execute_path(p, state)
    drained = []
    while True:
        cmd = state.dequeue()
        if cmd is None:
            break
        drained.append(cmd)
    assert drained == ["n", "e", "open door", "w"]


def test_execute_empty_path_enqueues_nothing():
    p = _path("AAAA", "BBBB", [])
    nav = Navigator([p])
    state = GameState()
    nav.execute_path(p, state)
    assert state.dequeue() is None


def test_list_loop_paths_returns_sorted_deduped_loop_codes():
    paths = [
        _path("CCCC", "CCCC", ["n"]),   # loop
        _path("AAAA", "AAAA", ["e"]),   # loop
        _path("AAAA", "BBBB", ["s"]),   # not a loop
        _path("BBBB", "BBBB", ["w"]),   # loop
    ]
    nav = Navigator(paths)
    assert nav.list_loop_paths() == ["AAAA", "BBBB", "CCCC"]


def test_list_loop_paths_empty_when_no_loops():
    nav = Navigator([_path("AAAA", "BBBB", ["n"])])
    assert nav.list_loop_paths() == []
