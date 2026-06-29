from __future__ import annotations
from typing import Callable
from mmud.automation.travel import TravelDecider
from mmud.config.schema import NavigationConfig
from mmud.data.paths import GamePath
from mmud.data.rooms import Room
from mmud.navigation.graph import RouteStep


def route_for_path(path: GamePath, rooms: dict[str, Room]) -> list[RouteStep]:
    """A recorded .MP path -> RouteSteps. Expected hex after step i is
    step[i+1].hex_id; the final step lands on the destination room's hex."""
    steps: list[RouteStep] = []
    hexes = [s.hex_id.upper() for s in path.steps]
    for i, s in enumerate(path.steps):
        if i + 1 < len(path.steps):
            dest = hexes[i + 1]
        else:
            room = rooms.get(path.to_code.upper())
            dest = room.hex_id.upper() if room and room.hex_id else ""
        expect = frozenset({dest}) if dest else frozenset()
        steps.append(RouteStep(command=s.command, expect=expect, chosen=dest))
    return steps


_MAX_WANDER = 40   # wander moves before we declare the loop lost and stop (MegaMud's
                   # "Lost!"): a hash-colliding maze like the graveyard can't be
                   # wandered out of, so don't burn hours trying.

_MAX_REENGAGE = 4  # re-engage (recover/wander) attempts allowed since the last
                   # COMPLETED lap before we give up. set_route resets the per-wander
                   # move counter, so without this cumulative cap a maze that desyncs
                   # every approach would re-arm forever and never trip _MAX_WANDER.


class LoopRunner:
    """Thin adapter: arms a looping route on the shared TravelDecider."""

    def __init__(self, nav_config: NavigationConfig, paths: list[GamePath],
                 rooms: dict[str, Room], travel: TravelDecider,
                 code_route: Callable[[str, str], list | None] | None = None,
                 current_code: str = "", current_hex: str = "",
                 missing_items: Callable[[str, str], list | None] | None = None) -> None:
        self._nav = nav_config
        self._rooms = rooms
        self._travel = travel
        self._running = False
        self._path = self._find_path(paths)
        # Route to the loop by chaining .MP paths over the room-CODE graph (reliable),
        # not the collision-ridden room-hash BFS.
        self._code_route = code_route         # callable(from_code, to_code)->[RouteStep]|None
        # callable(from_code, to_code) -> items needed (beyond those held) to reach the
        # loop, [] if reachable, None if unreachable even with every item. Lets us say
        # "need rope and grapple" instead of wandering off lost.
        self._missing_items = missing_items
        self._current_code = current_code.upper()
        self._current_hex = current_hex.upper()
        self.on_lost = None   # optional callback() the bot sets to log/alert on give-up
        self._reengages = 0   # recover() attempts since the last completed lap
        self._last_lap = self._travel.lap

    def _find_path(self, paths: list[GamePath]) -> GamePath | None:
        name = self._nav.loop_path.upper()
        if not name:
            return None
        # 1) by room CODE (loop where from == to == name) — e.g. "CRY1", "SLMC".
        for p in paths:
            if p.from_code.upper() == name and p.to_code.upper() == name:
                return p
        # 2) by .MP FILENAME stem or header DESCRIPTION, for a self-loop — so a custom
        # "slm2loop.mp" (whose code is SLMC) can be referenced as "slm2loop".
        for p in paths:
            if p.from_code == p.to_code and (
                    p.source_file.upper() == name
                    or p.description.upper() == name):
                return p
        # 3) an 8-char "FROMTO" pair (a point-to-point "loop").
        if len(name) == 8:
            fc, tc = name[:4], name[4:]
            for p in paths:
                if p.from_code.upper() == fc and p.to_code.upper() == tc:
                    return p
        return None

    def start(self) -> str:
        """Arm the loop. If we're not at the loop's start room, prepend a one-time
        route from the current room to it (MegaMud-style), then loop the body.
        Returns a status message."""
        if self._path is None:
            return f"Loop path '{self._nav.loop_path}' not found in loaded paths"
        loop_steps = route_for_path(self._path, self._rooms)
        if not loop_steps:
            return f"Loop path '{self._nav.loop_path}' has no steps"
        loop_hexes = [s.hex_id.upper() for s in self._path.steps]
        loop_code = self._path.from_code.upper()
        cur = self._current_hex

        # Already ON the loop -> finish it from here (MegaMud-style), no routing.
        if cur and cur in loop_hexes:
            idx = loop_hexes.index(cur)
            self._travel.set_route(loop_steps, loop=True, loop_from=0, start_at=idx)
            self._running = True
            return (f"On loop {self._nav.loop_path} -> resuming from step "
                    f"{idx + 1}/{len(loop_steps)}")

        if self._code_route is not None:
            # Known room off the loop -> chain .MP paths over the code graph to the
            # loop, then loop. (Reliable; avoids hash-BFS collisions.)
            if self._current_code:
                approach = self._code_route(self._current_code, loop_code)
                if approach:
                    self._travel.set_route(approach + loop_steps, loop=True,
                                           loop_from=len(approach))
                    self._running = True
                    return (f"Routing {len(approach)} steps "
                            f"({self._current_code}->{loop_code}), then looping")
                if approach == []:                     # already at the loop's room
                    self._travel.set_route(loop_steps, loop=True, loop_from=0)
                    self._running = True
                    return f"Loop started: {self._nav.loop_path}"
                # approach is None: no walkable route from this KNOWN room. If the only
                # way there is gated by an item we lack, name it and stop — don't wander
                # off "lost" (the user can't tell a maze from a missing rope & grapple).
                need = (self._missing_items(self._current_code, loop_code)
                        if self._missing_items else None)
                if need:
                    self._running = False
                    self._travel.clear(reason="need-item")
                    reason = (f"Can't reach {self._nav.loop_path} from "
                              f"{self._current_code}: need {', '.join(need)}")
                    self._alert_lost(reason)
                    return reason
            # Unknown room, or no code route -> wander until we step onto the loop.
            self._travel.set_wander(set(loop_hexes), self._engage_at,
                                    limit=_MAX_WANDER, on_giveup=self._giveup)
            self._running = True
            return f"Position unknown -> wandering until on loop {self._nav.loop_path}"

        # No navigation context (simple use): assume we're at the loop start.
        self._travel.set_route(loop_steps, loop=True, loop_from=0)
        self._running = True
        return f"Loop started: {self._nav.loop_path}"

    def _engage_at(self, hexid: str) -> None:
        """Wander reached a loop room: resume the loop from that index."""
        loop_steps = route_for_path(self._path, self._rooms)
        loop_hexes = [s.hex_id.upper() for s in self._path.steps]
        idx = loop_hexes.index(hexid.upper()) if hexid.upper() in loop_hexes else 0
        self._travel.set_route(loop_steps, loop=True, loop_from=0, start_at=idx)

    def recover(self) -> str:
        """We took a bad direction (desynced — rife in hash-colliding areas like the
        graveyard). Drop the recorded route and WANDER until we step onto a known
        loop room, then resume — MegaMud-style 'find a known room to reset'."""
        if self._path is None:
            return "no loop to recover"
        # Cumulative give-up: a completed lap (travel.lap changed) is real progress, so
        # reset the re-engage budget; otherwise count this attempt and give up once it
        # exceeds K. A re-arm (set_route via _engage_at) zeroes travel.lap, which we also
        # treat as a fresh budget — the live hole is the maze that NEVER completes a lap
        # (lap stays put while recover() keeps re-arming), which this catches.
        lap = self._travel.lap
        if lap != self._last_lap:
            self._last_lap = lap
            self._reengages = 0
        self._reengages += 1
        if self._reengages > _MAX_REENGAGE:
            self._giveup()
            return (f"gave up loop {self._nav.loop_path}: "
                    f"{self._reengages - 1} re-engages without completing a lap")
        loop_hexes = [s.hex_id.upper() for s in self._path.steps]
        self._travel.set_wander(set(loop_hexes), self._engage_at,
                                limit=_MAX_WANDER, on_giveup=self._giveup)
        self._running = True
        return f"wandering to relocate loop {self._nav.loop_path}"

    def relocate(self, code: str, hexid: str = "") -> str:
        """Lost-wander recovery: we recognised a KNOWN room while wandering. Re-route
        to the loop FROM HERE — resume if we're on it, else re-path over the code
        graph — instead of wandering blindly until we stumble onto a loop room."""
        code = code.upper()
        room = self._rooms.get(code)
        self._current_code = code
        self._current_hex = (hexid or (room.hex_id if room and room.hex_id else "")).upper()
        return self.start()

    def _giveup(self) -> None:
        """Wander hit its move cap without relocating the loop — stop, don't wander a
        colliding maze (e.g. the graveyard) for hours. The bot's on_lost alerts."""
        self._running = False
        self._travel.clear(reason="lost")
        self._alert_lost("")

    def _alert_lost(self, reason: str) -> None:
        """Fire the bot's on_lost hook with a reason (a missing item, or "" for a
        plain lost-wander give-up). Tolerates a no-arg callback for back-compat."""
        if not self.on_lost:
            return
        try:
            self.on_lost(reason)
        except TypeError:
            self.on_lost()

    def stop(self) -> None:
        self._running = False
        self._travel.clear(reason="stopped")

    def on_nav_failure(self) -> None:
        self._travel.on_move_failed()

    @property
    def running(self) -> bool:
        return self._running and self._travel.active

    @property
    def loop_start_code(self) -> str:
        """The 4-letter code of the loop's start room (where relocate re-routes TO)."""
        return self._path.from_code.upper() if self._path else ""

    @property
    def loop_len(self) -> int:
        """Number of steps in the loop body — the natural scale for 'how far off the
        loop could we plausibly have drifted in one move' (see bot._relocate_is_phantom)."""
        return len(self._path.steps) if self._path else 0

    @property
    def lap(self) -> int:
        return self._travel.lap
