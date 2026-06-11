from __future__ import annotations
import re
from mmud.data.rooms import Room

_NOTICE_RE = re.compile(r"You notice\s+(.*?)\s+here\.", re.IGNORECASE)
_IS_HERE_RE = re.compile(
    r"^(?:A|An|The)\s+(.+?)\s+(?:is|are|stands?|guard\w*)\s+here", re.IGNORECASE
)
_ALSO_HERE_RE = re.compile(r"^Also here:\s+(.+)\.", re.IGNORECASE)
_AND_RE = re.compile(r"\s+and\s+|\s*,\s*", re.IGNORECASE)
_COUNT_PREFIX_RE = re.compile(r"^(\d+)\s+(.+)$")
_ARTICLE_PREFIX_RE = re.compile(r"^(?:a|an|the)\s+(.+)$", re.IGNORECASE)
_PLAYER_NAME_RE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?$")
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
        """Monster names only (names-only view of extract_sightings)."""
        return [name for name, _ in self.extract_sightings(line)]

    def extract_sightings(self, line: str) -> list[tuple[str, int]]:
        """Monster names with counts.

        "Also here: a dark elf, 2 orc warriors." -> [("dark elf", 1), ("orc warriors", 2)]
        Player names (bare capitalized entries in "Also here:") are excluded.
        """
        line = line.strip()
        if m := _ALSO_HERE_RE.match(line):
            return self._classify_also_here(m.group(1))[0]
        if m := _IS_HERE_RE.match(line):
            name = m.group(1).strip().lower()
            if name and not _NON_MONSTER.search(name):
                return [(name, 1)]
            return []
        if m := _NOTICE_RE.search(line):
            out: list[tuple[str, int]] = []
            for part in _AND_RE.split(m.group(1)):
                sighting = self._classify_monster(part)
                if sighting:
                    out.append(sighting)
            return out
        return []

    def extract_players(self, line: str) -> list[str]:
        """Bare capitalized non-article entities in "Also here:" lines = players."""
        if m := _ALSO_HERE_RE.match(line.strip()):
            return self._classify_also_here(m.group(1))[1]
        return []

    def _classify_also_here(self, raw: str) -> tuple[list[tuple[str, int]], list[str]]:
        """Split "Also here:" content into (monster sightings, player names)."""
        monsters: list[tuple[str, int]] = []
        players: list[str] = []
        for entry in _AND_RE.split(raw.rstrip(".")):
            entry = entry.strip()
            if not entry:
                continue
            sighting = self._classify_monster(entry)
            if sighting:
                monsters.append(sighting)
            elif _PLAYER_NAME_RE.match(entry):
                players.append(entry)
        return monsters, players

    @staticmethod
    def _classify_monster(entry: str) -> tuple[str, int] | None:
        """A raw entry -> (name, count) if monster-like, else None.

        Count-prefixed ("2 orc warriors") and article-prefixed ("a dark elf")
        entries are monsters; coins/keys and bare proper names are not.
        """
        entry = entry.strip().rstrip(".")
        count = 1
        if cm := _COUNT_PREFIX_RE.match(entry):
            count, entry = int(cm.group(1)), cm.group(2).strip()
            if am := _ARTICLE_PREFIX_RE.match(entry):
                entry = am.group(1).strip()
        elif am := _ARTICLE_PREFIX_RE.match(entry):
            entry = am.group(1).strip()
        else:
            return None     # bare entry: a player name or non-monster
        name = entry.lower()
        if not name or _NON_MONSTER.search(name):
            return None
        return name, count
