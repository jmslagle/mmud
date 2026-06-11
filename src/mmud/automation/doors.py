from __future__ import annotations
import re
from mmud.config.schema import NavigationConfig

# Tune against the live server; record real wording in docs/testing-plan.md.
_CLOSED_RE = re.compile(r"(?:the )?door is closed|it'?s closed", re.IGNORECASE)
_LOCKED_RE = re.compile(r"(?:the )?door is locked|it'?s locked", re.IGNORECASE)


class DoorMonitor:
    """Turns door-blocked lines into open/pick/bash commands for the last move.

    Returns: list of commands to send (may be empty = give up), or None when
    the line is not door-related.
    """

    def __init__(self, config: NavigationConfig) -> None:
        self._cfg = config

    def handle(self, line: str, last_move: str) -> list[str] | None:
        if not last_move:
            return None
        if _LOCKED_RE.search(line):
            if self._cfg.can_pick_locks:
                return [f"pick {last_move}"]
            if self._cfg.bash_doors:
                return [f"bash {last_move}"]
            return []
        if _CLOSED_RE.search(line):
            return [f"open {last_move}"]
        return None
