from __future__ import annotations
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


class LoopRunner:
    """Thin adapter: arms a looping route on the shared TravelDecider."""

    def __init__(self, nav_config: NavigationConfig, paths: list[GamePath],
                 rooms: dict[str, Room], travel: TravelDecider) -> None:
        self._nav = nav_config
        self._rooms = rooms
        self._travel = travel
        self._running = False
        self._path = self._find_path(paths)

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

    def start(self) -> None:
        if self._path is None:
            return
        self._travel.set_route(route_for_path(self._path, self._rooms), loop=True)
        self._running = True

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
