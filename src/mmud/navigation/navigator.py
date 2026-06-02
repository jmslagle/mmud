from __future__ import annotations
import pathlib
from mmud.data.paths import GamePath, load_mp_file
from mmud.state.game_state import GameState


class Navigator:
    def __init__(self, paths: list[GamePath]) -> None:
        self._paths: dict[tuple[str, str], GamePath] = {}
        for p in paths:
            self._paths[(p.from_code, p.to_code)] = p

    @classmethod
    def from_directory(cls, directory: pathlib.Path) -> "Navigator":
        paths = []
        for mp_file in directory.glob("*.MP"):
            try:
                paths.append(load_mp_file(mp_file))
            except (ValueError, Exception):
                pass
        return cls(paths)

    def get_path(self, from_code: str, to_code: str) -> GamePath | None:
        return self._paths.get((from_code, to_code))

    def navigate_to(self, from_code: str, to_code: str) -> GamePath | None:
        """Find any path from from_code to to_code and return it (or None)."""
        return self._paths.get((from_code, to_code))

    def execute_path(self, path: GamePath, state: GameState) -> None:
        for step in path.steps:
            state.enqueue(step.command)
