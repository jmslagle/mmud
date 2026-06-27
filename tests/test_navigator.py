from mmud.navigation.navigator import Navigator
from mmud.data.paths import GamePath, PathStep
from mmud.state.game_state import GameState


def _path(fc, tc, steps):
    return GamePath(
        from_code=fc, from_region="", from_name="",
        to_code=tc, to_region="", to_name="", npc="",
        steps=[PathStep(hex_id="", command=c) for c in steps],
    )


def test_from_directories_extra_overrides_and_adds(tmp_path):
    bundled = tmp_path / "bundled"; bundled.mkdir()
    extra = tmp_path / "extra"; extra.mkdir()
    # bundled AABB->BBCC is 1 step; the user's extra version is 2 steps and must win.
    (bundled / "AABB.MP").write_text(
        "[][]\n[AABB:R:From]\n[BBCC:R:To]\nH0:H1:1:-1:0:::\nH0:0000:n\n")
    (extra / "AABB.MP").write_text(
        "[][]\n[AABB:R:From]\n[BBCC:R:To]\nH0:H1:2:-1:0:::\nH0:0000:n\nH1:0000:e\n")
    # a brand-new path only in the extra dir
    (extra / "XXYY.MP").write_text(
        "[][]\n[XXYY:R:X]\n[YYZZ:R:Y]\nH0:H1:1:-1:0:::\nH0:0000:s\n")
    nav = Navigator.from_directories([bundled, extra])
    assert [s.command for s in nav.get_path("AABB", "BBCC").steps] == ["n", "e"]  # extra won
    assert nav.get_path("XXYY", "YYZZ") is not None                                # new path added


def test_get_path_finds_registered_path():
    p = _path("AAAA", "BBBB", ["n", "e"])
    nav = Navigator([p])
    assert nav.get_path("AAAA", "BBBB") is p


def test_keeps_multiple_loops_at_the_same_source_room(tmp_path):
    # Two CAVW loops (different files) both start at CAVW. A (from,to) key would
    # collapse them to one; keying by filename keeps BOTH.
    d = tmp_path / "p"; d.mkdir()
    (d / "CAVWLOOP.MP").write_text("[Loop A][]\n[CAVW:R:Cave]\nH0:H0:1:-1:0:::\nH0:0000:e\n")
    (d / "CAVWLOP2.MP").write_text("[Loop B][]\n[CAVW:R:Cave]\nH0:H0:2:-1:0:::\nH0:0000:e\nH1:0000:s\n")
    nav = Navigator.from_directories([d])
    assert {"CAVWLOOP", "CAVWLOP2"} <= {p.source_file.upper() for p in nav.all_paths()}
    assert {"CAVWLOOP", "CAVWLOP2"} <= set(nav.list_loop_paths())


def test_get_path_is_case_insensitive():
    nav = Navigator([_path("SLMC", "A070", ["e"])])
    assert nav.get_path("slmc", "a070") is not None     # lowercase query
    assert nav.get_path("SLMC", "A070") is not None


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


def test_loop_choices_label_with_room_name_and_file():
    # Picker should show the room NAME plus the identifier: "Cave Worm Area (cavwloop)".
    p = GamePath(from_code="CAVW", from_region="Black House", from_name="Cave Worm Area",
                 to_code="CAVW", to_region="Black House", to_name="Cave Worm Area",
                 npc="", steps=[PathStep(hex_id="H0", command="e")],
                 source_file="Cavwloop")
    choices = Navigator([p]).loop_choices()
    assert ("Cavwloop", "Cave Worm Area (cavwloop)") in choices


def test_loop_choices_includes_npc_and_falls_back_to_code():
    # "General Store (Giovanni) (sgen)" — name + npc + identifier.
    store = GamePath(from_code="SGEN", from_region="", from_name="General Store",
                     to_code="SGEN", to_region="", to_name="General Store",
                     npc="Giovanni", steps=[PathStep(hex_id="H0", command="buy")],
                     source_file="")
    # No name/file -> identifier (the room code) stands in for the label.
    bare = _path("ZZZZ", "ZZZZ", ["n"])
    choices = dict(Navigator([store, bare]).loop_choices())
    assert choices["SGEN"] == "General Store (Giovanni) (sgen)"
    assert choices["ZZZZ"] == "ZZZZ (zzzz)"
