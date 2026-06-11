# tests/test_loop_runner.py
from mmud.data.paths import GamePath, PathStep
from mmud.events import GameEventBus, RoomChanged
from mmud.automation.loop_runner import LoopRunner
from mmud.state.game_state import GameState
from mmud.config.schema import NavigationConfig, StealthConfig


def _loop(code: str, commands: list[str]) -> GamePath:
    steps = [PathStep(hex_id="0000", command=c) for c in commands]
    return GamePath(from_code=code, from_region="", from_name="",
                    to_code=code, to_region="", to_name="", npc="", steps=steps)


def test_enqueues_on_start():
    gs = GameState()
    bus = GameEventBus()
    path = _loop("HOME", ["n", "e", "s", "w"])
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), StealthConfig(), [path], gs, bus)
    runner.start()
    assert gs.dequeue() == "n"
    assert gs.dequeue() == "e"


def test_reruns_on_arrival():
    gs = GameState()
    bus = GameEventBus()
    path = _loop("HOME", ["n", "s"])
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), StealthConfig(), [path], gs, bus)
    runner.start()
    gs.dequeue(); gs.dequeue()  # drain first iteration
    bus.post(RoomChanged(code="HOME", name="Home"))  # simulate arrival
    assert gs.dequeue() == "n"  # second iteration queued


def test_stop_prevents_requeue():
    gs = GameState()
    bus = GameEventBus()
    path = _loop("HOME", ["n", "s"])
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), StealthConfig(), [path], gs, bus)
    runner.start()
    runner.stop()
    gs.dequeue(); gs.dequeue()
    bus.post(RoomChanged(code="HOME", name="Home"))
    assert gs.dequeue() is None


def test_sneak_prefix():
    gs = GameState()
    bus = GameEventBus()
    path = _loop("HOME", ["n", "s"])
    sneak = StealthConfig(auto_sneak=True, sneak_cmd="sneak")
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), sneak, [path], gs, bus)
    runner.start()
    assert gs.dequeue() == "sneak"
    assert gs.dequeue() == "n"
    assert gs.dequeue() == "sneak"
    assert gs.dequeue() == "s"


def test_no_path_found():
    gs = GameState()
    bus = GameEventBus()
    runner = LoopRunner(NavigationConfig(loop_path="XXXX"), StealthConfig(), [], gs, bus)
    runner.start()  # must not raise
    assert gs.dequeue() is None


def test_encumbrance_blocks_stepping():
    from mmud.state.inventory import Inventory
    from mmud.config.schema import ItemsConfig
    gs = GameState()
    gs.inventory = Inventory(encumbrance_level="heavy")
    bus = GameEventBus()
    path = _loop("HOME", ["n", "e"])
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), StealthConfig(), [path], gs, bus,
                        items_config=ItemsConfig(dont_go_heavy=True))
    runner.start()
    assert gs.dequeue() is None         # nothing enqueued while heavy


def test_no_encumbrance_gate_when_light():
    from mmud.state.inventory import Inventory
    from mmud.config.schema import ItemsConfig
    gs = GameState()
    gs.inventory = Inventory(encumbrance_level="light")
    bus = GameEventBus()
    path = _loop("HOME", ["n", "e"])
    runner = LoopRunner(NavigationConfig(loop_path="HOME"), StealthConfig(), [path], gs, bus,
                        items_config=ItemsConfig(dont_go_heavy=True))
    runner.start()
    assert gs.dequeue() == "n"
