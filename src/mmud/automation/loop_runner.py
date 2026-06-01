from __future__ import annotations
from mmud.config.schema import NavigationConfig, StealthConfig
from mmud.data.paths import GamePath
from mmud.events import GameEventBus, RoomChanged
from mmud.state.game_state import GameState


class LoopRunner:
    """Executes a named loop path continuously, re-enqueuing on each RoomChanged arrival."""

    def __init__(
        self,
        nav_config: NavigationConfig,
        stealth_config: StealthConfig,
        paths: list[GamePath],
        state: GameState,
        bus: GameEventBus,
    ) -> None:
        self._nav = nav_config
        self._stealth = stealth_config
        self._state = state
        self._bus = bus
        self._running = False
        self._lap = 0
        self._path = self._find_path(paths)

    def _find_path(self, paths: list[GamePath]) -> GamePath | None:
        name = self._nav.loop_path.upper()
        if not name:
            return None
        # 4-char: from_code == to_code == name
        for p in paths:
            if p.from_code.upper() == name and p.to_code.upper() == name:
                return p
        # 8-char stem: first 4 = from_code, last 4 = to_code
        if len(name) == 8:
            fc, tc = name[:4], name[4:]
            for p in paths:
                if p.from_code.upper() == fc and p.to_code.upper() == tc:
                    return p
        return None

    def start(self) -> None:
        self._running = True
        self._lap = 0
        if self._path:
            self._enqueue_path()
        self._bus.subscribe(RoomChanged, self._on_room_changed)

    def stop(self) -> None:
        self._running = False

    def _on_room_changed(self, event: RoomChanged) -> None:
        if not self._running or not self._path:
            return
        if event.code.upper() == self._path.to_code.upper():
            self._lap += 1
            self._enqueue_path()

    def _enqueue_path(self) -> None:
        for step in self._path.steps:
            if self._stealth.auto_sneak:
                self._state.enqueue(self._stealth.sneak_cmd)
            self._state.enqueue(step.command)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def lap(self) -> int:
        return self._lap
