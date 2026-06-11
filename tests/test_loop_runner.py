# tests/test_loop_runner.py
from mmud.automation.loop_runner import LoopRunner, route_for_path
from mmud.automation.travel import TravelDecider
from mmud.config.schema import ItemsConfig, NavigationConfig, StealthConfig
from mmud.data.paths import GamePath, PathStep
from mmud.data.rooms import Room
from mmud.events import GameEventBus
from mmud.state.game_state import GameState


def _loop(code: str, hexes_cmds: list[tuple[str, str]]) -> GamePath:
    steps = [PathStep(hex_id=h, command=c) for h, c in hexes_cmds]
    return GamePath(from_code=code, from_region="", from_name="",
                    to_code=code, to_region="", to_name="", npc="", steps=steps)


ROOMS = {"HOME": Room(code="HOME", hex_id="AAAA0001", hex_id2="",
                      flags=(0, 0, 0), region="", name="The Home Room")}


def _runner(path, gs=None):
    gs = gs or GameState()
    travel = TravelDecider(ItemsConfig(), StealthConfig(), GameEventBus())
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), [path], ROOMS, travel)
    return runner, travel, gs


def test_route_for_path_expectations():
    path = _loop("HOME", [("AAAA0001", "n"), ("BBBB0002", "s")])
    steps = route_for_path(path, ROOMS)
    assert [s.command for s in steps] == ["n", "s"]
    assert steps[0].expect == frozenset({"BBBB0002"})
    assert steps[1].expect == frozenset({"AAAA0001"})   # final edge -> home


def test_start_arms_looping_route():
    path = _loop("HOME", [("AAAA0001", "n"), ("BBBB0002", "s")])
    runner, travel, gs = _runner(path)
    runner.start()
    assert runner.running
    assert travel.decide(gs) == "n"          # one step, not a bulk enqueue
    assert gs.dequeue() is None
    travel.on_arrival(gs, "")
    assert travel.decide(gs) == "s"
    travel.on_arrival(gs, "")
    assert runner.lap == 1                   # looped
    assert travel.decide(gs) == "n"


def test_stop_clears_route():
    path = _loop("HOME", [("AAAA0001", "n")])
    runner, travel, gs = _runner(path)
    runner.start()
    runner.stop()
    assert not runner.running
    assert travel.decide(gs) is None


def test_missing_path_does_not_arm():
    travel = TravelDecider(ItemsConfig(), StealthConfig(), GameEventBus())
    runner = LoopRunner(NavigationConfig(loop_path="XXXX"), [], ROOMS, travel)
    runner.start()
    assert runner._path is None
    assert not travel.active
