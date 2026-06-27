from __future__ import annotations
import pathlib
from mmud.data.binary import load_classes, load_races


class ClassRaceDB:
    """id → name lookup for CLASSES.MD / RACES.MD, used to resolve PLAYERS.MD
    class_id/race_id (and the spy DB) to human names (e.g. race 7 -> 'Dark-Elf',
    class 10 -> 'Gypsy')."""

    def __init__(self, classes: dict[int, str], races: dict[int, str]) -> None:
        self._classes = classes
        self._races = races

    @classmethod
    def from_dir(cls, data_dir: pathlib.Path | None) -> "ClassRaceDB":
        return cls.from_dirs([data_dir] if data_dir is not None else [])

    @classmethod
    def from_dirs(cls, dirs) -> "ClassRaceDB":
        """Resolve CLASSES.MD/RACES.MD across `dirs` (override order, case-insensitive),
        so the per-BBS extra dir overrides the bundled set."""
        from mmud.data.store import resolve_md
        cf = resolve_md(dirs, "CLASSES.MD")
        rf = resolve_md(dirs, "RACES.MD")
        classes = {c.record_id: c.name for c in load_classes(cf)} if cf else {}
        races = {r.record_id: r.name for r in load_races(rf)} if rf else {}
        return cls(classes, races)

    def class_name(self, class_id: int) -> str:
        return self._classes.get(class_id, "")

    def race_name(self, race_id: int) -> str:
        return self._races.get(race_id, "")
