from __future__ import annotations
import re
from mmud.config.schema import LoginConfig

# Common BBS/MUD prompt patterns. Worldgroup/Galacticomm (which hosts MajorMud)
# asks "...have a User-ID on this system, type it in and press ENTER..." — the
# cue is mid-line, so these are NOT anchored to end-of-line.
_USERNAME_RE = re.compile(
    r"user[\s-]?id|user\s*name|enter your (?:user|login|name)|(?:^|\s)login\s*[:\?]",
    re.IGNORECASE)
_PASSWORD_RE = re.compile(
    r"password\s*[:\?]?\s*$|enter your password|^\s*password", re.IGNORECASE)
# Worldgroup pager prompts. "(N)onstop, (Q)uit, or (C)ontinue?" — answer
# Nonstop to disable paging for the whole session so the bot is never stopped
# by news/menu pagination again. Generic "press enter / more?" -> just Enter.
_NONSTOP_RE = re.compile(r"\(N\)onstop|nonstop[,)].*continue", re.IGNORECASE)
_PAGER_RE = re.compile(
    r"press\s*(?:\[?\s*enter\s*\]?|any key)|more\s*\[|\[\s*pause\s*\]|"
    r"\[\s*Y\s*,\s*n|continue\s*\?\s*$", re.IGNORECASE)
_CHARACTER_RE = re.compile(r"(?:select|choose|enter|which)\s+(?:your\s+)?character", re.IGNORECASE)
_MAJORMUD_RE = re.compile(r"MAJORMUD|MajorMUD|Press any key to continue|press any key", re.IGNORECASE)
_GAME_FULL_RE = re.compile(r"game is (?:currently )?full|try again later", re.IGNORECASE)
_GAME_ENTERED_RE = re.compile(r"(?:character has been saved|entering the game|you are now in)", re.IGNORECASE)


class LoginHandler:
    """Handles the BBS login sequence by matching prompts and replying."""

    def __init__(self, config: LoginConfig) -> None:
        self._cfg = config
        self._user_re = (re.compile(config.username_prompt, re.IGNORECASE)
                         if config.username_prompt else _USERNAME_RE)
        self._pass_re = (re.compile(config.password_prompt, re.IGNORECASE)
                         if config.password_prompt else _PASSWORD_RE)
        self._sent_username = False
        self._sent_password = False
        self.game_full = False
        self.in_game = False

    def process_line(self, line: str) -> str | None:
        """Return the command to send in response to this line, or None."""
        if not self._cfg.username or not self._cfg.auto_login:
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
        if self._user_re.search(stripped) and not self._sent_username:
            self._sent_username = True
            return self._cfg.username

        # Password prompt
        if self._pass_re.search(stripped) and not self._sent_password:
            self._sent_password = True
            return self._cfg.password

        # Worldgroup "(N)onstop, (Q)uit, or (C)ontinue?" — answer Nonstop so the
        # bot is never paused by news/menu pagination again.
        if _NONSTOP_RE.search(stripped):
            return "N"
        # Generic pager / continue prompts — just press Enter.
        if _PAGER_RE.search(stripped):
            return ""

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
