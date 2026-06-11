from __future__ import annotations
import pathlib
import re
from mmud.data.binary import Monster, load_monsters

_ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)


def normalize(name: str) -> str:
    """Lowercase, strip leading article and whitespace."""
    return _ARTICLE_RE.sub("", name.strip().lower())


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
        return None

    def exp_value(self, name: str) -> int:
        m = self.find(name)
        return m.exp_value if m else 0
