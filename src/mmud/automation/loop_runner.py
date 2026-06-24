from __future__ import annotations
from typing import Callable
from mmud.automation.travel import TravelDecider
from mmud.config.schema import NavigationConfig
from mmud.data.paths import GamePath
from mmud.data.rooms import Room
from mmud.navigation.graph import NavResult, NavStatus, RouteStep


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


class LoopRunner:
    """Thin adapter: arms a looping route on the shared TravelDecider."""

    def __init__(self, nav_config: NavigationConfig, paths: list[GamePath],
                 rooms: dict[str, Room], travel: TravelDecider,
                 find_path: Callable[[str, str], NavResult] | None = None,
                 current_hex: str = "") -> None:
        self._nav = nav_config
        self._rooms = rooms
        self._travel = travel
        self._running = False
        self._path = self._find_path(paths)
        # When the bot isn't standing on the loop's first room, path there first.
        self._route_find = find_path          # RoomGraph.find_path (hex -> hex)
        self._current_hex = current_hex.upper()

    def _find_path(self, paths: list[GamePath]) -> GamePath | None:
        name = self._nav.loop_path.upper()
        if not name:
            return None
        for p in paths:
            if p.from_code.upper() == name and p.to_code.upper() == name:
                return p
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
        loop_start = loop_hexes[0]
        cur = self._current_hex

        # Already ON the loop -> finish it from here (MegaMud-style), no routing.
        if cur and cur in loop_hexes:
            idx = loop_hexes.index(cur)
            self._travel.set_route(loop_steps, loop=True, loop_from=0, start_at=idx)
            self._running = True
            return (f"On loop {self._nav.loop_path} -> resuming from step "
                    f"{idx + 1}/{len(loop_steps)}")

        if self._route_find is not None:
            # Known position off the loop -> route to its start, then loop.
            if cur:
                res = self._route_find(cur, loop_start)
                if res.status is NavStatus.OK:
                    approach = res.steps
                    self._travel.set_route(approach + loop_steps, loop=True,
                                           loop_from=len(approach))
                    self._running = True
                    return (f"Navigating {len(approach)} steps to "
                            f"{self._nav.loop_path} start, then looping")
            # Unknown position, or no route from a known one -> wander onto the loop.
            self._travel.set_wander(set(loop_hexes), self._engage_at)
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

    def stop(self) -> None:
        self._running = False
        self._travel.clear(reason="stopped")

    def on_nav_failure(self) -> None:
        self._travel.on_move_failed()

    @property
    def running(self) -> bool:
        return self._running and self._travel.active

    @property
    def lap(self) -> int:
        return self._travel.lap
