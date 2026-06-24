from __future__ import annotations
import re
from dataclasses import dataclass

@dataclass
class WhoEntry:
    name: str
    level: str
    rep: str
    gang: str = ""

# "Spawn DaPrawn        L21  Criminal  The Lords of T."
# "BumbleBee            L5-9 Neutral"
_WHO_RE = re.compile(
    r"^(.+?)\s{2,}"                 # name (followed by 2+ spaces)
    r"(L[\d][\d\-]*)\s+"            # level e.g. L21 or L5-9
    r"(Neutral|Criminal|Law Abiding|Outlaw|Hero|Villain)"  # rep
    r"(?:\s+(.+))?$",               # optional gang
    re.IGNORECASE,
)
_EXP_RE = re.compile(r"Exp(?:erience)?[:\s]+(\d[\d,]*)", re.IGNORECASE)
_LEVEL_RE = re.compile(r"Level[:\s]+(\d+)", re.IGNORECASE)
# Per-kill delta: "You gain 26 experience." (megamud.exe combat_event_parse adds
# this to a running total). Distinct from the absolute "Exp:" stat-screen value.
_EXP_GAIN_RE = re.compile(r"You gain\s+(\d[\d,]*)\s+experience", re.IGNORECASE)
# Stat/exp screen: "Exp needed for next level: 92,130".
_EXP_NEEDED_RE = re.compile(
    r"Exp(?:erience)? needed (?:for next level|to level)[:\s]+(\d[\d,]*)", re.IGNORECASE)


class WhoParser:
    def parse_line(self, line: str) -> WhoEntry | None:
        line = line.rstrip()
        if not line or len(line) < 10:
            return None
        if m := _WHO_RE.match(line):
            return WhoEntry(
                name=m.group(1).strip(),
                level=m.group(2).strip(),
                rep=m.group(3).strip(),
                gang=(m.group(4) or "").strip().rstrip("."),
            )
        return None

    def parse_exp_line(self, line: str) -> int | None:
        if m := _EXP_RE.search(line):
            return int(m.group(1).replace(",", ""))
        return None

    def parse_level_line(self, line: str) -> int | None:
        if m := _LEVEL_RE.search(line):
            return int(m.group(1))
        return None

    def parse_exp_gain_line(self, line: str) -> int | None:
        """Per-kill experience DELTA from 'You gain N experience.'"""
        if m := _EXP_GAIN_RE.search(line):
            return int(m.group(1).replace(",", ""))
        return None

    def parse_exp_needed_line(self, line: str) -> int | None:
        """Experience remaining to next level (stat/exp screen)."""
        if m := _EXP_NEEDED_RE.search(line):
            return int(m.group(1).replace(",", ""))
        return None
