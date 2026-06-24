from __future__ import annotations
import re

_EXITS_RE = re.compile(r"^Obvious exits:\s*(.+?)\.?$", re.IGNORECASE)

# Movement command per direction word. Index = MegaMud's direction order
# (room_exit_parse @ 0x00425290): N,S,E,W,NE,NW,SE,SW,U,D.
_DIR_ORDER = ["n", "s", "e", "w", "ne", "nw", "se", "sw", "u", "d"]
_DIR_WORDS = {
    "north": "n", "south": "s", "east": "e", "west": "w",
    "northeast": "ne", "northwest": "nw", "southeast": "se", "southwest": "sw",
    "up": "u", "down": "d", "above": "u", "below": "d",
    "n": "n", "s": "s", "e": "e", "w": "w",
    "ne": "ne", "nw": "nw", "se": "se", "sw": "sw", "u": "u", "d": "d",
}
_DOOR_WORDS = ("door", "gate", "trap door")

# Exit state codes, matching room_exit_parse: 1 open, 2 closed door, 3 open door,
# 4 secret. (0 = none.)
_STATE_OPEN, _STATE_CLOSED_DOOR, _STATE_OPEN_DOOR = 1, 2, 3


def _tokenize(line: str) -> list[tuple[str, int]] | None:
    """Parse an 'Obvious exits:' line into (direction-short, state) pairs.
    Returns None if not an exits line; [] for 'none'. Handles door/state prefixes
    like 'open door north' / 'closed gate south' (the direction is the last word)."""
    m = _EXITS_RE.match(line.strip())
    if not m:
        return None
    body = m.group(1).strip()
    if body.lower() == "none":
        return []
    out: list[tuple[str, int]] = []
    for raw in re.split(r",\s*|\s+and\s+", body):
        token = raw.strip().lower()
        if not token:
            continue
        words = token.split()
        direction = _DIR_WORDS.get(words[-1])
        if direction is None:
            continue
        is_door = any(dw in token for dw in _DOOR_WORDS)
        if is_door and "closed" in words:
            state = _STATE_CLOSED_DOOR
        elif is_door:
            state = _STATE_OPEN_DOOR
        else:
            state = _STATE_OPEN
        out.append((direction, state))
    return out


def parse_exits(line: str) -> list[str] | None:
    """Parse an 'Obvious exits:' line into short movement commands.

    Returns None when the line is not an exits line; [] for 'none'. Door-prefixed
    exits ('open door north') yield the direction ('n') — the door handler opens
    it on traversal. This line doubles as the ARRIVAL signal for unnamed rooms.
    """
    toks = _tokenize(line)
    if toks is None:
        return None
    return [d for d, _ in toks]


def exit_signature(line: str) -> int | None:
    """The 20-bit exit bitfield MegaMud hashes a room by (room_exit_parse): 10
    directions x 2 bits in N,S,E,W,NE,NW,SE,SW,U,D order. Door state is normalized
    (open-door 3 -> closed-door 2; secret 4 -> 0) so a room matches whether its
    door is shown open or closed. A stable per-room exit fingerprint for learning.

    MegaMud's full 32-bit room id ORs an upper-12-bit base onto this; that base is
    `title_hash(room_title) & 0xFFF` (see room_id()).
    """
    toks = _tokenize(line)
    if toks is None:
        return None
    sig = 0
    for direction, state in toks:
        if state == _STATE_OPEN_DOOR:   # open door -> closed door (normalized)
            state = _STATE_CLOSED_DOOR
        sig |= state << (_DIR_ORDER.index(direction) * 2)
    return sig


def title_hash(title: str) -> int:
    """MegaMud room-title hash (room_title_parse @0x00475e20): a position-weighted
    byte sum with a 1-based index, 32-bit wraparound. The top 12 bits of a room's
    id come from `title_hash(title) & 0xFFF`."""
    acc = 0
    for i, ch in enumerate(title):
        acc = (acc + (i + 1) * ord(ch)) & 0xFFFFFFFF
    return acc


def room_id(title: str, exits_line: str) -> str | None:
    """MegaMud's 32-bit room id (HexID1 in ROOMS.MD, used by the .MP path files):
    top 12 bits from the LIVE room title, low 20 bits from the obvious-exits
    bitfield (room_exit_parse @0x00425290). 8-char upper-hex, or None if
    `exits_line` isn't an 'Obvious exits:' line. Uses the server's displayed room
    name (NOT the abbreviated ROOMS.MD label), so it resolves rooms name-matching
    can't."""
    sig = exit_signature(exits_line)
    if sig is None:
        return None
    rid = (((title_hash(title) & 0xFFF) << 20) | sig) & 0xFFFFFFFF
    if rid == 0xB7200050:        # the binary's single hard-coded fixup
        rid = 0xB7200055
    return f"{rid:08X}"
