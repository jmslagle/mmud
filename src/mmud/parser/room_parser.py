from __future__ import annotations
import re
from mmud.data.rooms import Room

_NOTICE_RE = re.compile(r"You notice\s+(.*?)\s+here\.", re.IGNORECASE)
_IS_HERE_RE = re.compile(
    r"^(?:A|An|The)\s+(.+?)\s+(?:is|are|stands?|guard\w*)\s+here", re.IGNORECASE
)
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
