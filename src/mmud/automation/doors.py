from __future__ import annotations
import re
from mmud.config.schema import NavigationConfig

# Blocked-passage replies. Gates and doors share all handling (MegaMud's
# room_door_response_parse @0x42609e matches both). Server wording on this realm:
# "The gate is closed!", "... is Closed!", "... is locked", "It's closed.", and the
# move-blocked form "There is a closed door in that direction!" — the last is what we
# get after a keyed unlock (use <key> <dir>) leaves the door UNLOCKED but still CLOSED.
_OBSTACLE = r"(?:door|gate|portcullis|grate|drawbridge)"
_CLOSED_RE = re.compile(
    rf"{_OBSTACLE}\s+is\s+closed|it'?s\s+closed"
    rf"|closed\s+{_OBSTACLE}\s+in\s+that\s+direction",
    re.IGNORECASE)
_LOCKED_RE = re.compile(rf"{_OBSTACLE}\s+is\s+locked|it'?s\s+locked|just\s+locked",
                        re.IGNORECASE)
_OPEN_RE = re.compile(r"is\s+now\s+open|(?:is|was)\s+already\s+open", re.IGNORECASE)


class DoorMonitor:
    """Turns a door/gate-blocked move into open/pick/bash commands for the last
    move (MegaMud-style: pick if able, else bash; open a merely-closed one first,
    escalate to bash if it won't open). Returns a list of commands to send (empty
    = give up this passage), or None when the line isn't door-related.
    """

    def __init__(self, config: NavigationConfig) -> None:
        self._cfg = config
        self._open_tried = False
        self._bash_count = 0
        self._pick_count = 0

    def reset(self) -> None:
        """New room / passage cleared — forget per-door attempt counters."""
        self._open_tried = False
        self._bash_count = 0
        self._pick_count = 0

    def handle(self, line: str, last_move: str) -> list[str] | None:
        if not last_move:
            return None
        if _OPEN_RE.search(line):       # it opened -> proceed (move retries)
            self.reset()
            return None
        if _LOCKED_RE.search(line):     # locked -> pick/bash (open won't help)
            return self._force(last_move)
        if _CLOSED_RE.search(line):
            if not self._open_tried:    # try a plain open first
                self._open_tried = True
                return [f"open {last_move}"]
            return self._force(last_move)   # open didn't work -> pick/bash
        return None

    def _force(self, last_move: str) -> list[str]:
        """Pick (if able and under PickMax) else bash (under BashMax), else give up."""
        if self._cfg.can_pick_locks and self._pick_count < self._cfg.pick_max:
            self._pick_count += 1
            return [f"pick {last_move}"]
        if self._cfg.bash_doors and self._bash_count < self._cfg.bash_max:
            self._bash_count += 1
            return [f"bash {last_move}"]
        return []   # no capability / exhausted -> give up (path-blocked)
