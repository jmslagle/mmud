from mmud.automation.travel import TravelDecider, expand_annotated
from mmud.config.schema import ItemsConfig, StealthConfig
from mmud.events import GameEventBus, TravelResynced, TravelEnded
from mmud.navigation.graph import RouteStep
from mmud.state.game_state import GameState


def _step(cmd, *expect):
    return RouteStep(command=cmd, expect=frozenset(expect), chosen=expect[0])


def _decider(bus=None):
    return TravelDecider(ItemsConfig(), StealthConfig(),
                         bus or GameEventBus())


def test_expand_annotated():
    assert expand_annotated("n") == ["n"]
    assert expand_annotated("w[search w]") == ["search w", "w"]
    assert expand_annotated("go path") == ["go path"]


def test_matches_corpus_expect_hash_for_room_not_in_roomsmd():
    # The arrived room (e.g. "Mystic Alley") isn't in ROOMS.MD, but its COMPUTED
    # hash is what the .MP corpus recorded as the step's destination. on_arrival
    # gets the set of candidate hashes from the room block and matches expect.
    d = _decider()
    gs = GameState(); gs.current_hex = "DEF00011"
    d.set_route([_step("n", "DB600014"), _step("e", "DB600041")])
    assert d.decide(gs) == "n"
    d.on_arrival(gs, {"99999999", "DB600014"})   # junk + the real room's hash
    assert gs.current_hex == "DB600014"
    assert d.decide(gs) == "e"                    # advanced via corpus match


def test_redisplay_guard_is_one_shot_under_hash_collision():
    # Graveyard collision: the destination room hash-collides with the departure
    # (from_hex). The guard must ignore the re-display only ONCE, then advance —
    # not deadlock in_flight forever (the bug that froze the bot in the graveyard).
    d = _decider()
    gs = GameState(); gs.current_hex = "2B000055"
    d.set_route([_step("e", "DEST0001"), _step("n", "DEST0002")])
    assert d.decide(gs) == "e"               # from_hex = 2B000055
    d.on_arrival(gs, {"2B000055"})           # 1st: looks like a re-display -> ignore
    assert d.decide(gs) is None              # still waiting
    d.on_arrival(gs, {"2B000055"})           # 2nd: persists -> it really moved, advance
    assert d.decide(gs) == "n"               # not deadlocked


def test_ignores_departure_room_redisplay():
    # Reproduces the live hang: after issuing a move, the room we're LEAVING
    # re-displays its exits (an idle refresh racing the move). on_arrival must not
    # treat the departure hex as an arrival and clear("lost").
    d = _decider()
    gs = GameState()
    gs.current_hex = "BANK0001"
    d.set_route([_step("e", "DEST0001"), _step("n", "DEST0002")])
    assert d.decide(gs) == "e"          # from_hex captured = BANK0001
    d.on_arrival(gs, "BANK0001")        # departure room re-display (race)
    assert d.active                     # route NOT cleared
    assert d.decide(gs) is None         # still in flight, awaiting real arrival
    d.on_arrival(gs, "")                # real arrival (unknown room -> empty hex)
    assert d.decide(gs) == "n"          # advanced to the next step


def test_loop_step_reports_position_and_total():
    d = _decider()
    gs = GameState()
    d.set_route([_step("n", "B"), _step("e", "C"), _step("s", "A")], loop=True)
    assert d.loop_step == (1, 3)            # at the first step
    assert d.lap == 0
    assert d.decide(gs) == "n"; d.on_arrival(gs, {"B"})
    assert d.loop_step == (2, 3)
    d.decide(gs); d.on_arrival(gs, {"C"})
    assert d.loop_step == (3, 3)
    d.decide(gs); d.on_arrival(gs, {"A"})   # completed a lap -> wraps
    assert d.lap == 1
    assert d.loop_step == (1, 3)


def test_loop_step_counts_body_only_during_approach():
    d = _decider()
    gs = GameState()
    # 1 approach step + 2 loop-body steps
    d.set_route([_step("e", "X"), _step("n", "B"), _step("s", "X")],
                loop=True, loop_from=1)
    assert d.in_approach and d.loop_step == (0, 0)   # not in the body yet
    assert d.decide(gs) == "e"; d.on_arrival(gs, {"X"})
    assert not d.in_approach and d.loop_step == (1, 2)   # body: step 1 of 2


def test_loop_from_resets_to_offset_not_zero():
    # 1 approach step ("e") + 2 loop steps ("n","s"); loop_from=1 means a completed
    # lap restarts at the loop body, never replaying the approach.
    d = _decider()
    gs = GameState()
    d.set_route([_step("e", "B"), _step("n", "C"), _step("s", "B")],
                loop=True, loop_from=1)
    assert d.decide(gs) == "e"; d.on_arrival(gs, "B")
    assert d.decide(gs) == "n"; d.on_arrival(gs, "C")
    assert d.decide(gs) == "s"; d.on_arrival(gs, "B")
    assert d.lap == 1
    assert d.decide(gs) == "n"   # back to loop body (idx 1), not "e"


def test_one_step_per_arrival():
    d = _decider()
    gs = GameState()
    d.set_route([_step("n", "BBBB0002"), _step("e", "CCCC0003")])
    assert d.decide(gs) == "n"
    assert d.decide(gs) is None              # in flight: wait for arrival
    d.on_arrival(gs, "")                     # unnamed room: trust expectation
    assert gs.current_hex == "BBBB0002"
    assert d.decide(gs) == "e"
    d.on_arrival(gs, "CCCC0003")
    assert not d.active                      # route complete
    assert gs.current_hex == "CCCC0003"


def test_annotation_queues_move_after_search():
    d = _decider()
    gs = GameState()
    d.set_route([_step("w[search w]", "BBBB0002")])
    assert d.decide(gs) == "search w"
    assert gs.dequeue() == "w"               # queued for the next line


def test_sneak_prefix():
    d = TravelDecider(ItemsConfig(), StealthConfig(auto_sneak=True),
                      GameEventBus())
    gs = GameState()
    d.set_route([_step("n", "BBBB0002")])
    assert d.decide(gs) == "sneak"
    assert gs.dequeue() == "n"


def test_resync_jumps_cursor():
    received = []
    bus = GameEventBus()
    bus.subscribe(TravelResynced, received.append)
    d = _decider(bus)
    gs = GameState()
    d.set_route([_step("n", "BBBB0002"), _step("e", "CCCC0003"),
                 _step("s", "DDDD0004")])
    d.decide(gs)
    d.on_arrival(gs, "CCCC0003")             # overshot: landed after step 2
    assert received and received[0].to_step == 2
    assert d.decide(gs) == "s"               # cursor resumed at step 3


def test_off_route_hash_advances_optimistically():
    # Room hashes are unreliable (many live rooms aren't in the corpus), so an
    # arrival that matches no route step is TRUSTED as a successful move (advance
    # via the planned dest) rather than ending the route. Genuine dead-ends surface
    # as nav failures ("no exit") -> on_move_failed, not as a hash mismatch.
    d = _decider()
    gs = GameState()
    d.set_route([_step("n", "BBBB0002"), _step("e", "CCCC0003")])
    assert d.decide(gs) == "n"
    d.on_arrival(gs, "ZZZZ9999")             # nowhere on the route
    assert gs.current_hex == "BBBB0002"      # advanced via planned dest (chosen)
    assert d.decide(gs) == "e"


def test_move_failed_retries_then_ends():
    received = []
    bus = GameEventBus()
    bus.subscribe(TravelEnded, received.append)
    d = _decider(bus)
    gs = GameState()
    d.set_route([_step("n", "BBBB0002")])
    assert d.decide(gs) == "n"
    d.on_move_failed()
    assert d.decide(gs) == "n"               # retry 1
    d.on_move_failed()
    assert d.decide(gs) == "n"               # retry 2
    d.on_move_failed()
    assert not d.active
    assert received[0].reason == "blocked"


def test_loop_mode_restarts_and_counts_laps():
    d = _decider()
    gs = GameState()
    d.set_route([_step("n", "BBBB0002")], loop=True)
    d.decide(gs); d.on_arrival(gs, "")
    assert d.lap == 1
    assert d.decide(gs) == "n"               # restarted


def test_encumbrance_gate():
    from mmud.state.inventory import Inventory
    d = TravelDecider(ItemsConfig(dont_go_heavy=True), StealthConfig(),
                      GameEventBus())
    gs = GameState()
    gs.inventory = Inventory(encumbrance_level="heavy")
    d.set_route([_step("n", "BBBB0002")])
    assert d.decide(gs) is None              # halted while heavy
