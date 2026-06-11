from mmud.automation.search import SearchDecider
from mmud.automation.decision import PRIO_SEARCH
from mmud.config.schema import NavigationConfig
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType


def _state(hex_id="AAAA0001", exits=("n", "e")):
    gs = GameState()
    gs.current_hex = hex_id
    gs.last_exits = list(exits)
    return gs


def test_auto_search_searches_new_room():
    d = SearchDecider(NavigationConfig(auto_search=True, search_max=2),
                      now=lambda: 5.0)
    gs = _state()
    assert d.decide(gs) == "search"
    assert gs.task.type is TaskType.SEARCHING
    assert gs.task.priority == PRIO_SEARCH


def test_search_max_per_room():
    d = SearchDecider(NavigationConfig(auto_search=True, search_max=2),
                      now=lambda: 5.0)
    gs = _state()
    for _ in range(2):
        assert d.decide(gs) == "search"
        gs.complete_task()
    assert d.decide(gs) is None              # exhausted for this room
    gs.current_hex = "BBBB0002"
    assert d.decide(gs) == "search"          # fresh room, fresh budget


def test_roam_cycles_exits():
    d = SearchDecider(NavigationConfig(roam=True), now=lambda: 5.0)
    gs = _state(exits=("n", "e"))
    assert d.decide(gs) == "n"
    assert d.decide(gs) == "e"
    assert d.decide(gs) == "n"               # round-robin, no randomness


def test_disabled_does_nothing():
    d = SearchDecider(NavigationConfig(), now=lambda: 5.0)
    assert d.decide(_state()) is None


def test_quiet_in_combat():
    d = SearchDecider(NavigationConfig(auto_search=True), now=lambda: 5.0)
    gs = _state()
    gs.set_combat(True)
    assert d.decide(gs) is None
