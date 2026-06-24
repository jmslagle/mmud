from __future__ import annotations
import re
from mmud.data.rooms import Room

_NOTICE_RE = re.compile(r"You notice\s+(.*?)\s+here\.", re.IGNORECASE)
_IS_HERE_RE = re.compile(
    r"^(?:A|An|The)\s+(.+?)\s+(?:is|are|stands?|guard\w*)\s+here", re.IGNORECASE
)
# A monster wandering in: "A fat giant rat creeps into the room from nowhere."
# Article-prefixed (players arrive without an article), so this is a monster.
_ARRIVES_RE = re.compile(
    r"^(?:A|An|The)\s+(.+?)\s+(?:creeps?|walks?|wanders?|lumbers?|slithers?|"
    r"crawls?|strides?|stumbles?|saunters?|sneaks?|charges?|rushes?|shuffles?|"
    r"flies|floats?|arrives?|enters?|appears?|steps?)\b", re.IGNORECASE)
_ALSO_HERE_RE = re.compile(r"^Also here:\s+(.+)\.", re.IGNORECASE)
# Trailing parenthetical on an entity, e.g. "goblin (Charmed)" — MegaMud strips it.
_PAREN_SUFFIX_RE = re.compile(r"\s*\(.*\)\s*$")
_AND_RE = re.compile(r"\s+and\s+|\s*,\s*", re.IGNORECASE)
_COUNT_PREFIX_RE = re.compile(r"^(\d+)\s+(.+)$")
_ARTICLE_PREFIX_RE = re.compile(r"^(?:a|an|the)\s+(.+)$", re.IGNORECASE)
_PLAYER_NAME_RE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?$")
_NON_MONSTER = re.compile(
    r"\b(copper|silver|gold|platinum|noble|crown|coin|key|here)\b", re.IGNORECASE
)
# A monster leaving the roster: death ("The kobold thief falls to the ground"),
# a named slay ("You have slain the X"), or the server rejecting a stale target
# ("You do not see X here!"). The "You gain N experience" kill carries no name
# and is handled by removing the current target (see bot._parse_who_and_exp).
_DEATH_RE = re.compile(
    r"^(?:A|An|The)\s+(.+?)\s+(?:falls?|drops?|slumps?|crumples?|collapses?)\s+"
    r"to the ground", re.IGNORECASE)
_IS_DEAD_RE = re.compile(r"^(?:A|An|The)\s+(.+?)\s+(?:is|are)\s+dead\b", re.IGNORECASE)
_SLAIN_RE = re.compile(r"You (?:have )?(?:slain|killed)\s+(.+?)[.!]", re.IGNORECASE)
_NOT_HERE_RE = re.compile(r"You do not see\s+(.+?)\s+here", re.IGNORECASE)


def _normalize_room_name(name: str) -> str:
    """Canonicalize a room name for matching: lowercase, drop commas, collapse
    whitespace. The server prints "Newhaven, Arena" while ROOMS.MD stores
    "Newhaven Arena" — normalization bridges that punctuation/format gap."""
    return re.sub(r"\s+", " ", name.replace(",", " ")).strip().lower()


class RoomParser:
    def __init__(self, rooms: dict[str, Room]) -> None:
        self._name_to_code: dict[str, str] = {
            _normalize_room_name(r.name): code for code, r in rooms.items()
        }

    def detect_room(self, line: str) -> str | None:
        return self._name_to_code.get(_normalize_room_name(line))

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
        if m := _ARRIVES_RE.match(line):
            name = _PAREN_SUFFIX_RE.sub("", m.group(1)).strip().lower()
            if name and not _NON_MONSTER.search(name):
                return [(name, 1)]
            return []
        # NOTE: "You notice X here." is GROUND LOOT (handled by items.LootMonitor),
        # NOT monsters — e.g. "You notice 2 log raft here." Treating it as a
        # monster made the bot try to attack scenery. Monsters appear in
        # "Also here:" / "A X is here." / arrival lines only.
        return []

    def extract_removed_monster(self, line: str) -> str | None:
        """A monster name to drop from the roster (death / slay / "do not see"),
        or None. Article + trailing parenthetical stripped; lowercased to match
        sighting names. Exact-name removal is the caller's job (game_state)."""
        line = line.strip()
        for rx in (_DEATH_RE, _IS_DEAD_RE, _SLAIN_RE, _NOT_HERE_RE):
            if m := rx.search(line):
                name = _PAREN_SUFFIX_RE.sub("", m.group(1).strip()).strip()
                if am := _ARTICLE_PREFIX_RE.match(name):
                    name = am.group(1).strip()
                name = name.lower()
                if name and not _NON_MONSTER.search(name):
                    return name
        return None

    def extract_players(self, line: str) -> list[str]:
        """Bare capitalized non-article entities in "Also here:" lines = players."""
        if m := _ALSO_HERE_RE.match(line.strip()):
            return self._classify_also_here(m.group(1))[1]
        return []

    def _classify_also_here(self, raw: str) -> tuple[list[tuple[str, int]], list[str]]:
        """Split "Also here:" content into (monster sightings, player names).

        Per MegaMud's room_also_here_parse, EVERY comma-separated entry is an
        entity (no article/count required); trailing "(...)" is stripped. The
        original keys monster-vs-player off the name's ANSI colour; lacking that
        here we use the observed convention: a bare Capitalized proper name is a
        player/NPC (e.g. "Betram", "Krang Moan"); everything else is a monster.
        """
        monsters: list[tuple[str, int]] = []
        players: list[str] = []
        for entry in _AND_RE.split(raw.rstrip(".")):
            entry = _PAREN_SUFFIX_RE.sub("", entry.strip()).strip()
            if not entry:
                continue
            count = 1
            if cm := _COUNT_PREFIX_RE.match(entry):
                count, entry = int(cm.group(1)), cm.group(2).strip()
            had_article = bool(_ARTICLE_PREFIX_RE.match(entry))
            if had_article:
                entry = _ARTICLE_PREFIX_RE.match(entry).group(1).strip()
            if not entry or _NON_MONSTER.search(entry.lower()):
                continue
            if count == 1 and not had_article and _PLAYER_NAME_RE.match(entry):
                players.append(entry)
            else:
                monsters.append((entry.lower(), count))
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
