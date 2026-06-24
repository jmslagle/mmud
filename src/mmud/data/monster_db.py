from __future__ import annotations
import pathlib
import re
from mmud.data.binary import Monster, load_monsters

_ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)


def normalize(name: str) -> str:
    """Lowercase, strip leading article and whitespace."""
    return _ARTICLE_RE.sub("", name.strip().lower())


def _word_boundary_match(room: str, db_name: str) -> bool:
    """True if room == db_name, or room ends with " <db_name>". MegaMud's
    monster_db_lookup_by_name (0x4544d0) matches the base name as a word-boundary
    substring (offset 0 or after a space); the base name is the tail of a display
    name ("happy guardsman", "a large giant rat"), so we anchor to the suffix —
    safer than MegaMud's left-only test (won't match "rat" inside "rat catcher")."""
    return room == db_name or room.endswith(" " + db_name)


class MonsterDB:
    """Name-indexed monster lookup over MONSTERS.MD records."""

    def __init__(self, monsters: list[Monster]) -> None:
        self._by_name: dict[str, Monster] = {}
        for m in monsters:
            for candidate in (m.name, m.short_name1, m.short_name2):
                key = normalize(candidate)
                if key and key not in self._by_name:
                    self._by_name[key] = m

    @classmethod
    def from_file(cls, path: pathlib.Path) -> "MonsterDB":
        return cls(load_monsters(path))

    @classmethod
    def from_store(cls, store) -> "MonsterDB":
        from mmud.data.store import store_monsters
        return cls(store_monsters(store))

    def find(self, name: str) -> Monster | None:
        key = normalize(name)
        if key in self._by_name:
            return self._by_name[key]
        # naive de-pluralize: "orc warriors" -> "orc warrior"
        if key.endswith("s") and key[:-1] in self._by_name:
            return self._by_name[key[:-1]]
        # Leading adjectives/moods: MegaMud's monster_db_lookup_by_name (0x4544d0)
        # matches a DB base name as a word-boundary substring of the room name
        # (offset 0 or preceded by a space), absorbing words like "happy"/"large".
        # We prefer the LONGEST match so "rat" can't hijack "giant rat".
        best: Monster | None = None
        best_len = 0
        for db_name, mon in self._by_name.items():
            if len(db_name) > best_len and _word_boundary_match(key, db_name):
                best, best_len = mon, len(db_name)
        return best

    def exp_value(self, name: str) -> int:
        m = self.find(name)
        return m.exp_value if m else 0
