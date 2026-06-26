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
        return cls.from_directories([directory])

    @classmethod
    def from_directories(cls, directories: list[pathlib.Path]) -> "Navigator":
        """Load .MP paths from several directories, in order. A later directory's path
        for a (from, to) pair OVERRIDES an earlier one — so a user's extra_paths_dir
        can fix/replace bundled paths and add new ones."""
        paths = []
        for directory in directories:
            if directory is None or not pathlib.Path(directory).is_dir():
                continue
            directory = pathlib.Path(directory)
            files = {f.resolve()                       # dedup on case-insensitive FS
                     for pat in ("*.MP", "*.mp") for f in directory.glob(pat)}
            for mp_file in sorted(files):
                try:
                    paths.append(load_mp_file(mp_file))
                except Exception:
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

    def list_loop_paths(self) -> list[str]:
        """Return names of all loop paths (where from_code == to_code)."""
        seen = set()
        result = []
        for (fc, tc), path in self._paths.items():
            if fc == tc and fc not in seen:
                seen.add(fc)
                result.append(fc)
        return sorted(result)
