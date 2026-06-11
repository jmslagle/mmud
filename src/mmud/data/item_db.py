from __future__ import annotations
import pathlib
from mmud.data.binary import Item, load_items
from mmud.data.monster_db import normalize


class ItemDB:
    """Name-indexed item lookup over ITEMS.MD records."""

    def __init__(self, items: list[Item]) -> None:
        self._by_name: dict[str, Item] = {}
        for it in items:
            key = normalize(it.name)
            if key and key not in self._by_name:
                self._by_name[key] = it

    @classmethod
    def from_file(cls, path: pathlib.Path) -> "ItemDB":
        return cls(load_items(path))

    def find(self, name: str) -> Item | None:
        key = normalize(name)
        if key in self._by_name:
            return self._by_name[key]
        if key.endswith("s") and key[:-1] in self._by_name:
            return self._by_name[key[:-1]]
        return None
