from __future__ import annotations
import re
from mmud.data.rooms import Room

_NOTICE_RE = re.compile(r"You notice\s+(.*?)\s+here\.", re.IGNORECASE)
_IS_HERE_RE = re.compile(
    r"^(?:A|An|The)\s+(.+?)\s+(?:is|are|stands?|guard\w*)\s+here", re.IGNORECASE
)
_ALSO_HERE_RE = re.compile(r"^Also here:\s+(.+)\.", re.IGNORECASE)
_ITEM_ENTRY_RE = re.compile(r"^(\d+\s+)?(?:A|An|The)\s+(.+)$", re.IGNORECASE)
_COUNT_RE = re.compile(r"^\d+\s+")
_AND_RE = re.compile(r"\s+and\s+|\s*,\s*", re.IGNORECASE)
_NON_MONSTER = re.compile(
    r"\b(copper|silver|gold|platinum|noble|crown|coin|key|here)\b", re.IGNORECASE
)


class RoomParser:
    def __init__(self, rooms: dict[str, Room]) -> None:
        self._name_to_code: dict[str, str] = {
            r.name.lower(): code for code, r in rooms.items()
        }

    def detect_room(self, line: str) -> str | None:
        return self._name_to_code.get(line.strip().lower())

    def extract_monsters(self, line: str) -> list[str]:
        # "Also here: A dark elf, 2 orc warriors, Krang Moan."
        if m := _ALSO_HERE_RE.match(line.strip()):
            raw = m.group(1)
            entries = [e.strip().rstrip(".") for e in raw.split(",")]
            results = []
            for entry in entries:
                # Only take entries that start with A/An/The (monster-like, not player names)
                if em := _ITEM_ENTRY_RE.match(entry):
                    name = em.group(2).strip().lower()
                    if name and not _NON_MONSTER.search(name):
                        results.append(name)
            return results
        if m := _IS_HERE_RE.match(line.strip()):
            name = m.group(1).strip()
            if not _NON_MONSTER.search(name):
                return [name.lower()]
        if m := _NOTICE_RE.search(line):
            raw = m.group(1)
            parts = _AND_RE.split(raw)
            results = []
            for part in parts:
                part = _COUNT_RE.sub("", part.strip()).lower()
                if part and not _NON_MONSTER.search(part):
                    results.append(part)
            return results
        return []
