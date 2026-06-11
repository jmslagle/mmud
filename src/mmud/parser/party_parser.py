from __future__ import annotations
import re
from dataclasses import dataclass
from mmud.state.game_state import GameState

# EXACT anchors from megamud.exe party_list_parse @ 0x004618e0.
_NOT_IN_PARTY_RE = re.compile(r"You are not in a party", re.IGNORECASE)
_LIST_HEADER_RE = re.compile(r"The following people are in your", re.IGNORECASE)
_FOLLOWING_RE = re.compile(r"^You are following\s+(\w+)", re.IGNORECASE)

# Member row — RECONSTRUCTED layout (live-tune in docs/testing-plan.md):
# "Name [Surname] [Class] [HP%] [MP%] [P]"
_ROW_RE = re.compile(
    r"^\s*([A-Z][\w']*)"            # first name
    r"(?:\s+[A-Z][\w']*)?"          # optional surname
    r"\s+\[([^\]]+)\]"              # [Class]
    r"\s+\[\s*(\d+)\]"              # [HP%]
    r"(?:\s+\[\s*(\d+)\])?"         # [MP%] (optional)
    r"(?:\s+(P))?\s*$"              # leader/rank flag
)


@dataclass
class PartyMember:
    name: str
    hp_pct: int = 100
    mp_pct: int = 100
    klass: str = ""
    is_leader: bool = False


class PartyParser:
    """Stateful party-list parser: header line opens the list, the first
    non-matching line closes it."""

    def __init__(self) -> None:
        self._in_list = False
        self._pending: list[PartyMember] = []

    def feed(self, line: str, state: GameState) -> bool:
        """Returns True when the line was party-related."""
        if _NOT_IN_PARTY_RE.search(line):
            self._in_list = False
            self._pending = []
            state.party = []
            state.party_leader = ""
            return True
        if _LIST_HEADER_RE.search(line):
            self._in_list = True
            self._pending = []
            return True
        if m := _FOLLOWING_RE.match(line.strip()):
            state.party_leader = m.group(1)
            return True
        if self._in_list:
            if m := _ROW_RE.match(line):
                self._pending.append(PartyMember(
                    name=m.group(1),
                    klass=m.group(2).strip(),
                    hp_pct=int(m.group(3)),
                    mp_pct=int(m.group(4)) if m.group(4) else 100,
                    is_leader=bool(m.group(5)),
                ))
                return True
            # list ended: commit what we collected
            self._in_list = False
            state.party = self._pending
            self._pending = []
        return False
