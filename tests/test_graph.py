import pytest
from mmud.data.paths import load_mp_file, GamePath, PathStep
from mmud.data.rooms import load_rooms, Room
from mmud.navigation.graph import RoomGraph, NavStatus


@pytest.fixture(scope="module")
def corpus_graph():
    from conftest import DATA_DIR
    rooms = load_rooms(DATA_DIR / "ROOMS.MD")
    paths = [p for p in (load_mp_file(f) for f in sorted(DATA_DIR.glob("*.MP")))
             if p and p.steps]
    return RoomGraph.from_paths(paths, rooms)


def test_corpus_graph_pinned_shape(corpus_graph):
    assert corpus_graph.node_count() == 4510
    assert corpus_graph.edge_count() == 14035          # distinct (from,cmd,to)
    assert corpus_graph.multi_dest_pairs() == 2482     # (from,cmd) with >1 dest


def test_corpus_reachability_from_aaly(corpus_graph):
    assert len(corpus_graph.reachable("CAB00180")) == 4501


def test_find_path_on_corpus(corpus_graph, data_dir):
    rooms = load_rooms(data_dir / "ROOMS.MD")
    src = rooms["AALY"].hex_id.upper()
    # pick any other named, reachable room
    dst = next(r.hex_id.upper() for c, r in sorted(rooms.items())
               if c != "AALY" and r.hex_id.upper() in corpus_graph.reachable(src))
    result = corpus_graph.find_path(src, dst)
    assert result.status is NavStatus.OK
    assert len(result.steps) >= 1
    assert all(s.command for s in result.steps)
    # every step's expected set is non-empty and the last step can land on dst
    assert dst in result.steps[-1].expect


def test_unknown_start_and_dest():
    g = RoomGraph()
    g.add_edge("AAAA0001", "n", "BBBB0002")
    assert g.find_path("ZZZZ9999", "BBBB0002").status is NavStatus.UNKNOWN_START
    assert g.find_path("AAAA0001", "ZZZZ9999").status is NavStatus.UNKNOWN_DEST


def test_no_path_in_disconnected_graph():
    g = RoomGraph()
    g.add_edge("AAAA0001", "n", "BBBB0002")
    g.add_edge("CCCC0003", "s", "DDDD0004")   # separate island
    assert g.find_path("AAAA0001", "DDDD0004").status is NavStatus.NO_PATH


def test_learned_exit_bridges_islands():
    g = RoomGraph()
    g.add_edge("AAAA0001", "n", "BBBB0002")
    g.add_edge("CCCC0003", "s", "DDDD0004")
    g.add_edge("BBBB0002", "e", "CCCC0003")   # e.g. from store.exits()
    r = g.find_path("AAAA0001", "DDDD0004")
    assert r.status is NavStatus.OK
    assert [s.command for s in r.steps] == ["n", "e", "s"]
