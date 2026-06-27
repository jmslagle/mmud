from __future__ import annotations
import pathlib
from mmud.data.paths import GamePath, load_mp_file
from mmud.state.game_state import GameState


class Navigator:
    def __init__(self, paths: list[GamePath]) -> None:
        # Keep EVERY path, deduped by .MP filename stem (UPPER) so an extra dir's file
        # overrides the same-named bundled one but DIFFERENT files survive — there can
        # be several loops at the same source room (CAVWLOOP and CAVWLOP2 both start at
        # CAVW), which a (from,to) key would collapse into one.
        by_file: dict[str, GamePath] = {}
        self._noname: list[GamePath] = []
        for p in paths:
            stem = (p.source_file or "").upper()
            if stem:
                by_file[stem] = p          # later (extra dir) wins
            else:
                self._noname.append(p)
        self._by_file = by_file
        # (from,to) -> path for routing/legacy lookup (case-insensitive; last wins).
        self._paths: dict[tuple[str, str], GamePath] = {}
        for p in self.all_paths():
            self._paths[(p.from_code.upper(), p.to_code.upper())] = p

    def all_paths(self) -> list[GamePath]:
        """Every loaded path (deduped by filename, all source-room variants kept).
        Also surfaces any path inserted directly into `_paths` (test/programmatic)."""
        out = list(self._by_file.values()) + self._noname
        seen = {id(p) for p in out}
        out += [p for p in self._paths.values() if id(p) not in seen]
        return out

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
        return self._paths.get((from_code.upper(), to_code.upper()))

    def navigate_to(self, from_code: str, to_code: str) -> GamePath | None:
        """Find any path from from_code to to_code and return it (or None)."""
        return self._paths.get((from_code.upper(), to_code.upper()))

    def execute_path(self, path: GamePath, state: GameState) -> None:
        for step in path.steps:
            state.enqueue(step.command)

    def list_loop_paths(self) -> list[str]:
        """Names of all loop paths (from == to), by .MP filename so variants at the
        same source room are distinguishable (e.g. CAVWLOOP vs CAVWLOP2)."""
        names = {p.source_file or p.from_code
                 for p in self.all_paths() if p.from_code == p.to_code}
        return sorted(n for n in names if n)

    def loop_choices(self) -> list[tuple[str, str]]:
        """(identifier, label) for every loop path, for the picker. The identifier is
        what `:loop <name>` accepts (filename stem, else room code); the label adds the
        human room name (and NPC) so the picker reads 'Cave Worm Area (cavwloop)' or
        'General Store (Giovanni) (sgen)' rather than a bare opaque code."""
        out: dict[str, tuple[str, str]] = {}
        for p in self.all_paths():
            if p.from_code.upper() != p.to_code.upper():
                continue
            ident = p.source_file or p.from_code
            if not ident:
                continue
            name = p.from_name or p.description or ident
            label = name + (f" ({p.npc})" if p.npc else "") + f" ({ident.lower()})"
            out[ident.upper()] = (ident, label)
        return [out[k] for k in sorted(out, key=lambda k: out[k][1].lower())]
