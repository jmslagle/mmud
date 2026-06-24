from __future__ import annotations
import re

# Examine block from "l <name>":
#   [ Horis ]
#   Horis is a solid, well built Dark-Elf Gypsy with no hair and black eyes.  He
_EXAMINE_HEADER_RE = re.compile(r"^\[\s*([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?)\s*\]$")
# "... is a <build...> <Race> <Class> with ..." — Race/Class are the two words
# immediately before " with " (Race may be hyphenated, e.g. Dark-Elf).
_EXAMINE_DESC_RE = re.compile(r"\bis an?\b.+ ([A-Za-z'-]+) ([A-Za-z]+) with\b", re.IGNORECASE)

# Presence transitions.
_ARRIVE_RE = re.compile(
    r"(?:You notice (\w+) (?:sneak(?:s|ing)? in|com(?:e|ing) in|arriv)"
    r"|(\w+) (?:walks?|strides?|steps?|arrives?|enters?|wanders?) (?:in|into))",
    re.IGNORECASE)
_DEPART_RE = re.compile(
    r"(?:You notice (\w+) (?:sneak(?:s|ing)? out|leav|head)"
    r"|(\w+) (?:leaves|departs|walks out|heads (?:north|south|east|west|up|down)))",
    re.IGNORECASE)
_LOOKING_AT_RE = re.compile(r"(\w+) is looking at you", re.IGNORECASE)


class PlayerExamineParser:
    """Stateful: feed each line; returns {name, race, class} when an examine
    block (started by "[ Name ]") yields a race/class description."""

    def __init__(self) -> None:
        self._current: str | None = None

    def feed(self, line: str) -> dict | None:
        line = line.strip()
        if m := _EXAMINE_HEADER_RE.match(line):
            self._current = m.group(1).strip()
            return None
        if self._current and (m := _EXAMINE_DESC_RE.search(line)):
            name, self._current = self._current, None
            return {"name": name, "race": m.group(1), "class": m.group(2)}
        return None


def _first_group(m: re.Match) -> str:
    return next(g for g in m.groups() if g)


def parse_arrival(line: str) -> str | None:
    m = _ARRIVE_RE.search(line.strip())
    return _first_group(m) if m else None


def parse_departure(line: str) -> str | None:
    m = _DEPART_RE.search(line.strip())
    return _first_group(m) if m else None


def parse_looking_at(line: str) -> str | None:
    m = _LOOKING_AT_RE.search(line.strip())
    return m.group(1) if m else None
