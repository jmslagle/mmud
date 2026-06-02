from __future__ import annotations
import re
from mmud.config.schema import LoginConfig

# Common BBS/MUD prompt patterns
_USERNAME_RE = re.compile(r"(?:username|login|user\s*name|user\s*id|handle)\s*[:\?]?\s*$", re.IGNORECASE)
_PASSWORD_RE = re.compile(r"(?:password|passwd|pass)\s*[:\?]?\s*$", re.IGNORECASE)
_CHARACTER_RE = re.compile(r"(?:select|choose|enter|which)\s+(?:your\s+)?character", re.IGNORECASE)
_MAJORMUD_RE = re.compile(r"MAJORMUD|MajorMUD|Press any key to continue|press any key", re.IGNORECASE)
_GAME_FULL_RE = re.compile(r"game is (?:currently )?full|try again later", re.IGNORECASE)
_GAME_ENTERED_RE = re.compile(r"(?:character has been saved|entering the game|you are now in)", re.IGNORECASE)


class LoginHandler:
    """Handles the BBS login sequence by matching prompts and replying."""

    def __init__(self, config: LoginConfig) -> None:
        self._cfg = config
        self._sent_username = False
        self._sent_password = False
        self.game_full = False
        self.in_game = False

    def process_line(self, line: str) -> str | None:
        """Return the command to send in response to this line, or None."""
        if not self._cfg.username:
            return None

        stripped = line.strip()

        # Game state detection (no reply needed)
        if _GAME_FULL_RE.search(stripped):
            self.game_full = True
            return None
        if _GAME_ENTERED_RE.search(stripped):
            self.in_game = True
            return None

        # Username prompt
        if _USERNAME_RE.search(stripped) and not self._sent_username:
            self._sent_username = True
            return self._cfg.username

        # Password prompt
        if _PASSWORD_RE.search(stripped) and not self._sent_password:
            self._sent_password = True
            return self._cfg.password

        # Character selection — send character name
        if self._cfg.character and _CHARACTER_RE.search(stripped):
            return self._cfg.character

        # MajorMUD menu prompt — send enter to continue
        if _MAJORMUD_RE.search(stripped):
            return ""   # send empty line (just \r\n = press any key)

        return None

    def reset(self) -> None:
        """Reset for a new login attempt."""
        self._sent_username = False
        self._sent_password = False
        self.game_full = False
        self.in_game = False
