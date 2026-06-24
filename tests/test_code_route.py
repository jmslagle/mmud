from mmud.data.paths import GamePath, PathStep
from mmud.data.rooms import Room
from mmud.navigation.code_route import find_code_route, build_code_edges


def _path(fc, tc, *hex_cmds):
    return GamePath(from_code=fc, from_region="", from_name="", to_code=tc,
                    to_region="", to_name="", npc="",
                    steps=[PathStep(hex_id=h, command=c) for h, c in hex_cmds])


_ROOMS = {"C": Room(code="C", hex_id="C0000000", hex_id2="", flags=(0, 0, 0),
                    region="", name="Room C")}


def test_chains_legs_into_one_walkable_route():
    p1 = _path("A", "B", ("A0000000", "n"), ("A1000000", "e"))   # A -> B
    p2 = _path("B", "C", ("B0000000", "s"))                       # B -> C
    steps = find_code_route("A", "C", [p1, p2], _ROOMS)
    assert [s.command for s in steps] == ["n", "e", "s"]
    assert steps[0].expect == frozenset({"A1000000"})            # within leg 1
    assert steps[1].expect == frozenset({"B0000000"})            # leg-1 end == leg-2 start
    assert steps[2].expect == frozenset({"C0000000"})            # final -> dest room hex


def test_returns_none_when_unreachable():
    p1 = _path("A", "B", ("A0000000", "n"))
    assert find_code_route("A", "Z", [p1], _ROOMS) is None


def test_empty_route_when_already_there():
    assert find_code_route("A", "A", [], {}) == []


def test_self_loops_skipped_for_routing():
    loop = _path("A", "A", ("A0000000", "n"))   # a loop, not a connector
    edges = build_code_edges([loop])
    assert "A" not in edges.get("A", {})
