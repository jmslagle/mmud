from __future__ import annotations
import re
from mmud.state.inventory import Inventory

_CARRYING_RE = re.compile(r"^You are carrying\s+(.*)$", re.IGNORECASE)
_WEARING_RE = re.compile(r"^You are wearing\s+(.*)$", re.IGNORECASE)
_WEALTH_RE = re.compile(
    r"^Wealth:\s+(\d+)\s+(copper|silver|gold|platinum|runic)", re.IGNORECASE)
_ENCUMBRANCE_RE = re.compile(
    r"^Encumbrance:\s+(\d+)/(\d+)\s*-\s*(\w+)\s*\[(\d+)%\]", re.IGNORECASE)
_COUNT_ITEM_RE = re.compile(r"^(\d+)\s+(.*)$")
_ARTICLE_RE = re.compile(r"^(?:a|an|the|some)\s+", re.IGNORECASE)
_COIN_RE = re.compile(
    r"^(\d+)\s+(copper|silver|gold|platinum|runic)\b", re.IGNORECASE)


def _split_items(text: str) -> list[str]:
    return [part.strip() for part in re.split(r",\s*|\s+and\s+", text.rstrip(". "))
            if part.strip()]


class InventoryParser:
    """Accumulates the multi-line `inv` response; returns the completed
    Inventory when the Encumbrance line arrives, else None."""

    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._carried: dict[str, int] = {}
        self._worn: list[str] = []
        self._coins: dict[str, int] = {}
        self._section: str | None = None   # "carrying" | "wearing" | None

    def feed(self, line: str) -> Inventory | None:
        line = line.rstrip()
        if m := _CARRYING_RE.match(line):
            self._section = "carrying"
            self._add_items(m.group(1))
            return None
        if m := _WEARING_RE.match(line):
            self._section = "wearing"
            self._worn.extend(_ARTICLE_RE.sub("", i).lower()
                              for i in _split_items(m.group(1)))
            return None
        if m := _WEALTH_RE.match(line):
            self._coins[m.group(2).lower()] = int(m.group(1))
            self._section = None
            return None
        if m := _ENCUMBRANCE_RE.match(line):
            inv = Inventory(
                carried_counts=dict(self._carried),
                worn=list(self._worn),
                coins=dict(self._coins),
                encumbrance_pct=int(m.group(4)),
                encumbrance_level=m.group(3).lower(),
            )
            self._reset()
            return inv
        # continuation of a wrapped carrying/wearing list (starts with spaces)
        if self._section and line.startswith(" "):
            if self._section == "carrying":
                self._add_items(line)
            else:
                self._worn.extend(_ARTICLE_RE.sub("", i).lower()
                                  for i in _split_items(line))
            return None
        self._section = None
        return None

    def _add_items(self, text: str) -> None:
        for raw in _split_items(text):
            if cm := _COIN_RE.match(raw):
                self._coins[cm.group(2).lower()] = int(cm.group(1))
                continue
            count = 1
            if m := _COUNT_ITEM_RE.match(raw):
                count, raw = int(m.group(1)), m.group(2)
            name = _ARTICLE_RE.sub("", raw).strip().lower()
            if name:
                self._carried[name] = self._carried.get(name, 0) + count
