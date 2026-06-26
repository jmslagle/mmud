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


def test_find_loop_by_filename_or_description_case_insensitively():
    # A custom "slm2loop.mp" whose code is SLMC must resolve by code, by the filename
    # stem, AND by header description — all case-insensitive.
    path = GamePath(from_code="SLMC", from_region="", from_name="Slum Crossroads",
                    to_code="SLMC", to_region="", to_name="", npc="",
                    steps=[PathStep(hex_id="AAAA0001", command="e")],
                    source_file="slm2loop", description="Slum Loop")
    travel = TravelDecider(ItemsConfig(), StealthConfig(), GameEventBus())
    for name in ("SLMC", "slmc", "slm2loop", "SLM2LOOP", "slum loop"):
        runner = LoopRunner(NavigationConfig(loop_path=name), [path], ROOMS, travel)
        assert runner._path is path, name


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


def test_resumes_loop_when_already_on_it():
    # On the loop already -> finish it from here (no routing to the start).
    path = _loop("HOME", [("AAAA0001", "n"), ("BBBB0002", "e"), ("CCCC0003", "s")])
    travel = TravelDecider(ItemsConfig(), StealthConfig(), GameEventBus())
    def code_route(frm, to):
        raise AssertionError("should not route when already on the loop")
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), [path], ROOMS, travel,
                        code_route=code_route, current_code="HOME",
                        current_hex="BBBB0002")           # index 1
    runner.start()
    gs = GameState()
    assert travel.decide(gs) == "e"           # resumes at index-1's command
    gs.current_hex = "BBBB0002"
    travel.on_arrival(gs, {"CCCC0003"})
    assert travel.decide(gs) == "s"
    travel.on_arrival(gs, {"AAAA0001"})       # looped back to the top
    assert runner.lap == 1
    assert travel.decide(gs) == "n"           # full loop from step 0 now


def test_routes_to_loop_when_away():
    from mmud.navigation.graph import RouteStep
    path = _loop("HOME", [("AAAA0001", "n"), ("BBBB0002", "s")])
    travel = TravelDecider(ItemsConfig(), StealthConfig(), GameEventBus())
    calls = {}
    def code_route(frm, to):
        calls["args"] = (frm, to)
        return [RouteStep("e", frozenset({"AAAA0001"}), "AAAA0001")]
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), [path], ROOMS, travel,
                        code_route=code_route, current_code="FARR",
                        current_hex="FAR00000")
    runner.start()
    assert calls["args"] == ("FARR", "HOME")           # routed over the code graph
    gs = GameState()
    assert travel.decide(gs) == "e"                    # approach step first
    travel.on_arrival(gs, "AAAA0001")
    assert travel.decide(gs) == "n"                    # then the loop body
    travel.on_arrival(gs, "BBBB0002")
    assert travel.decide(gs) == "s"
    travel.on_arrival(gs, "AAAA0001")
    assert runner.lap == 1
    assert travel.decide(gs) == "n"                    # loops body, not the approach


def test_start_skips_approach_when_already_at_loop_start():
    path = _loop("HOME", [("AAAA0001", "n"), ("BBBB0002", "s")])
    travel = TravelDecider(ItemsConfig(), StealthConfig(), GameEventBus())
    def code_route(frm, to):
        raise AssertionError("should not route when already at start")
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), [path], ROOMS, travel,
                        code_route=code_route, current_code="HOME",
                        current_hex="AAAA0001")
    runner.start()
    assert travel.decide(GameState()) == "n"           # straight into the loop


def test_no_route_to_loop_falls_back_to_wander():
    path = _loop("HOME", [("AAAA0001", "n")])
    travel = TravelDecider(ItemsConfig(), StealthConfig(), GameEventBus())
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), [path], ROOMS, travel,
                        code_route=lambda f, t: None, current_code="FARR",
                        current_hex="FAR00000")
    msg = runner.start()
    assert runner.running and "wander" in msg.lower()


def test_wanders_when_position_unknown_then_engages_loop():
    path = _loop("HOME", [("AAAA0001", "n"), ("BBBB0002", "e")])
    travel = TravelDecider(ItemsConfig(), StealthConfig(), GameEventBus())
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), [path], ROOMS, travel,
                        code_route=lambda f, t: None, current_code="",
                        current_hex="")                  # unknown position
    msg = runner.start()
    assert "wander" in msg.lower() and runner.running
    gs = GameState(); gs.last_exits = ["s", "e"]
    assert travel.decide(gs) in ("s", "e")               # wander move
    travel.on_arrival(gs, {"ZZZZ9999"})                  # not on loop -> keep going
    gs.last_exits = ["w", "n"]
    assert travel.decide(gs) in ("w", "n")
    travel.on_arrival(gs, {"AAAA0001"})                  # stepped onto the loop
    assert travel.decide(gs) == "n"                      # real loop engaged at idx 0


def test_relocate_repaths_from_a_known_room_mid_wander():
    # Lost and wandering with no idea where we are; then we recognise a KNOWN room.
    # relocate() must re-path to the loop FROM that room (not keep wandering).
    from mmud.navigation.graph import RouteStep
    path = _loop("HOME", [("AAAA0001", "n"), ("BBBB0002", "s")])
    travel = TravelDecider(ItemsConfig(), StealthConfig(), GameEventBus())
    calls = {}
    def code_route(frm, to):
        calls["args"] = (frm, to)
        return [RouteStep("e", frozenset({"AAAA0001"}), "AAAA0001")]
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), [path], ROOMS, travel,
                        code_route=code_route, current_code="", current_hex="")
    runner.start()                                    # position unknown -> wander
    assert travel.wandering
    msg = runner.relocate("FARR", "FAR00000")         # recognised a known room
    assert calls["args"] == ("FARR", "HOME")          # re-pathed from there
    assert not travel.wandering                        # wander cancelled
    assert travel.decide(GameState()) == "e"           # follows the approach now


def test_recover_wanders_to_relocate_the_loop():
    # A bad direction means we've desynced -> wander to find a loop room again.
    path = _loop("HOME", [("AAAA0001", "n"), ("BBBB0002", "e")])
    travel = TravelDecider(ItemsConfig(), StealthConfig(), GameEventBus())
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), [path], ROOMS, travel,
                        code_route=lambda f, t: [], current_code="HOME",
                        current_hex="AAAA0001")
    runner.start()
    assert travel.route                       # following the loop
    msg = runner.recover()
    assert "wander" in msg.lower()
    assert not travel.route                    # switched to wander (no fixed steps)
    gs = GameState(); gs.last_exits = ["s", "e"]
    assert travel.decide(gs) in ("s", "e")     # wandering
    travel.on_arrival(gs, {"AAAA0001"})        # found a loop room
    assert travel.decide(gs) == "n"            # loop re-engaged


def test_missing_path_does_not_arm():
    travel = TravelDecider(ItemsConfig(), StealthConfig(), GameEventBus())
    runner = LoopRunner(NavigationConfig(loop_path="XXXX"), [], ROOMS, travel)
    runner.start()
    assert runner._path is None
    assert not travel.active
