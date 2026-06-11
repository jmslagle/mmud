from __future__ import annotations
import re
from mmud.config.schema import SafetyConfig

_DEATH_RE = re.compile(
    r"you have died|you are dead|your lifeless body|death has come", re.IGNORECASE
)
# Hangup-player matching is restricted to room-presence lines to avoid
# false positives from conversations mentioning the name.
_ROOM_PRESENCE_RE = re.compile(r"^\s*also here:|\benters? the room\b", re.IGNORECASE)


class SafetyMonitor:
    """Watches server output for danger and requests a disconnect."""

    def __init__(self, config: SafetyConfig) -> None:
        self._cfg = config
        self.hangup_requested = False
        self.reason = ""

    def process_line(self, line: str) -> None:
        if self.hangup_requested:
            return
        if self._cfg.hangup_on_death and _DEATH_RE.search(line):
            self.request_hangup("death detected")
            return
        if self._cfg.hangup_players and _ROOM_PRESENCE_RE.search(line):
            for name in self._cfg.hangup_players:
                if name and re.search(rf"\b{re.escape(name)}\b", line, re.IGNORECASE):
                    self.request_hangup(f"hangup player seen: {name}")
                    return

    def request_hangup(self, reason: str) -> None:
        self.hangup_requested = True
        self.reason = reason

    def reset(self) -> None:
        self.hangup_requested = False
        self.reason = ""
