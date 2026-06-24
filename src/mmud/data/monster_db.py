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
        exact = self._by_name.get(key)
        # A REAL (catalogued, record_id >= 0) exact match always wins. A learned
        # placeholder (negative id, e.g. a bogus "happy guardsman" recorded back
        # when lookups were exact-only) must NOT shadow the real base name, so we
        # fall through to adjective matching and only use the learned record if no
        # real monster resolves.
        if exact is not None and exact.record_id >= 0:
            return exact
        # naive de-pluralize: "orc warriors" -> "orc warrior"
        if key.endswith("s"):
            dep = self._by_name.get(key[:-1])
            if dep is not None and dep.record_id >= 0:
                return dep
        # Leading adjectives/moods: MegaMud's monster_db_lookup_by_name (0x4544d0)
        # matches a DB base name as a word-boundary substring of the room name
        # (offset 0 or preceded by a space), absorbing words like "happy"/"large".
        # Real records only, preferring the LONGEST ("rat" can't hijack "giant rat").
        best: Monster | None = None
        best_len = 0
        for db_name, mon in self._by_name.items():
            if (mon.record_id >= 0 and len(db_name) > best_len
                    and _word_boundary_match(key, db_name)):
                best, best_len = mon, len(db_name)
        return best or exact

    def exp_value(self, name: str) -> int:
        m = self.find(name)
        return m.exp_value if m else 0
