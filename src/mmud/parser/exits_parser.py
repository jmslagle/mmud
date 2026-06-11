from __future__ import annotations
import re

_EXITS_RE = re.compile(r"^Obvious exits:\s*(.+?)\.?$", re.IGNORECASE)

_DIRECTIONS = {
    "north": "n", "south": "s", "east": "e", "west": "w",
    "northeast": "ne", "northwest": "nw", "southeast": "se", "southwest": "sw",
    "up": "u", "down": "d",
    # already-short forms pass through
    "n": "n", "s": "s", "e": "e", "w": "w",
    "ne": "ne", "nw": "nw", "se": "se", "sw": "sw", "u": "u", "d": "d",
}


def parse_exits(line: str) -> list[str] | None:
    """Parse an 'Obvious exits:' line into short movement commands.

    Returns None when the line is not an exits line; [] for 'none'.
    This line doubles as the ARRIVAL signal for unnamed rooms (88% of the
    graph) — TravelDecider advances on it.
    """
    m = _EXITS_RE.match(line.strip())
    if not m:
        return None
    body = m.group(1).strip().lower()
    if body == "none":
        return []
    out = []
    for raw in re.split(r",\s*|\s+and\s+", body):
        cmd = _DIRECTIONS.get(raw.strip())
        if cmd:
            out.append(cmd)
    return out
