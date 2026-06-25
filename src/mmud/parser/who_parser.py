from __future__ import annotations
import re
from dataclasses import dataclass

@dataclass
class WhoEntry:
    name: str
    alignment: str = ""   # WHO's leading alignment column (may be empty)
    title: str = ""       # class/rank title shown after " - "

# This server's WHO is a block ("Current Adventurers" / "===") of:
#   "Aurther      -  Squire"
#   "Lawful Bloodrock    -  Sensei"   (leading alignment word)
#   "Wrex Alot    -  Seeker"          (two-word name)
# Split on the "  -  " separator; peel a leading known-alignment word off the left.
_WHO_RE = re.compile(r"^([A-Za-z].*?)\s+-\s+(\S.*?)\s*$")
# Known alignment descriptors that may prefix the name. May need tuning per server
# (this realm uses "Lawful"); peeled only when followed by a real name.
_ALIGNMENTS = {
    "lawful", "neutral", "chaotic", "good", "evil", "saintly", "fiendish",
    "kind", "cruel", "angelic", "demonic", "amiable", "nice", "mean", "noble",
    "heroic", "villainous", "outlaw", "criminal",
}
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
        """Parse one WHO-block entry. Call only within the block (the bot gates on
        the 'Current Adventurers' header) — the '  -  ' shape is permissive."""
        m = _WHO_RE.match(line.rstrip())
        if not m:
            return None
        left, title = m.group(1).strip(), m.group(2).strip()
        words = left.split()
        alignment = ""
        if len(words) > 1 and words[0].lower() in _ALIGNMENTS:
            alignment, name = words[0], " ".join(words[1:])
        else:
            name = left
        if not name:
            return None
        return WhoEntry(name=name, alignment=alignment, title=title)

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
