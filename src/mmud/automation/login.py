from __future__ import annotations
import re
from mmud.commands import expand_template
from mmud.config.schema import LoginConfig

# Common BBS/MUD prompt patterns. Worldgroup/Galacticomm (which hosts MajorMud)
# asks "...have a User-ID on this system, type it in and press ENTER..." — the
# cue is mid-line, so these are NOT anchored to end-of-line.
_USERNAME_RE = re.compile(
    r"user[\s-]?id|user\s*name|enter your (?:user|login|name)|(?:^|\s)login\s*[:\?]",
    re.IGNORECASE)
_PASSWORD_RE = re.compile(
    r"password\s*[:\?]?\s*$|enter your password|^\s*password", re.IGNORECASE)
# Pager prompts MegaMud answers automatically (game_menu_prompt_parse @0x45f650): the
# Worldgroup "(N)onstop, (Q)uit, or (C)ontinue?", "Press/Hit any key to continue", and the
# generic "press enter / more?" pauses. MegaMud replies with a bare Enter (the default =
# Continue) — NEVER "Q". Always handled, independent of the user's login script.
_PAGER_RE = re.compile(
    r"\(N\)onstop|\bnonstop\s*[,)]|or \(C\)ontinue\?|"
    r"press any key|hit any key|"
    r"press\s*\[\s*enter\s*\]|"                  # "Press [ENTER] ..."
    r"press\s*enter\s+to\s+continue|"            # "Press ENTER to continue"
    r"press\s*enter\s*$|"                        # bare "Press ENTER" at end of line
    r"more\s*\[|\[\s*pause\s*\]|\[\s*Y\s*,\s*n|continue\s*\?\s*$",
    re.IGNORECASE)
# The MajorMUD menu prompt. MegaMud (bbs_login_sequence_handle @0x444e50, default MenuPrompt
# "[MAJORMUD]:") sends the literal "enter" to enter the realm — hardcoded, always.
_MAJORMUD_MENU_RE = re.compile(r"\[MAJORMUD\]\s*:", re.IGNORECASE)
# The authoritative "now in game" signal: a "[HP=...]:" prompt (line starts with it). MegaMud
# flips out of logon mode here (-> ONLINE/READY, AI starts), regardless of any menu_prompt.
_HP_PROMPT_RE = re.compile(r"^\[HP=.*\]:", re.IGNORECASE)
_CHARACTER_RE = re.compile(r"(?:select|choose|enter|which)\s+(?:your\s+)?character", re.IGNORECASE)
_GAME_FULL_RE = re.compile(
    r"game is (?:currently )?full|but the game is currently full|try again later",
    re.IGNORECASE)
_GAME_ENTERED_RE = re.compile(r"(?:character has been saved|entering the game|you are now in)", re.IGNORECASE)


class LoginHandler:
    """Handles the BBS login sequence by matching prompts and replying."""

    def __init__(self, config: LoginConfig) -> None:
        self._cfg = config
        self._user_re = (re.compile(config.username_prompt, re.IGNORECASE)
                         if config.username_prompt else _USERNAME_RE)
        self._pass_re = (re.compile(config.password_prompt, re.IGNORECASE)
                         if config.password_prompt else _PASSWORD_RE)
        # Scripted login (MegaMud-style): compiled ordered expect/reply steps.
        self._script = [(re.compile(s.prompt, re.IGNORECASE), s.reply)
                        for s in config.script if s.prompt]
        self._menu_re = (re.compile(config.menu_prompt, re.IGNORECASE)
                         if config.menu_prompt else None)
        self._vars = {"userid": config.username, "pswd": config.password,
                      "character": config.character}
        self._step = 0
        self._sent_username = False
        self._sent_password = False
        self.game_full = False
        self.in_game = False

    def process_line(self, line: str) -> str | None:
        """Return the command to send in response to this line, or None."""
        if not self._cfg.username or not self._cfg.auto_login:
            return None

        stripped = line.strip()

        # ── MegaMud-hardcoded handling: ALWAYS on, regardless of the login script ──
        # These fire however many times they appear, in any order — which is why the pager
        # works when there are MULTIPLE (N)onstop prompts whose count varies with the
        # who-list/news length (a fixed sequential script can't cover a variable count).

        # Authoritative "now in game": a "[HP=...]:" prompt -> leave logon mode, start the AI.
        if _HP_PROMPT_RE.search(stripped):
            self.in_game = True
            return None
        if _GAME_FULL_RE.search(stripped):
            self.game_full = True
            return None
        if (self._menu_re and self._menu_re.search(stripped)) \
                or _GAME_ENTERED_RE.search(stripped):
            self.in_game = True
            return None
        # Pager: "(N)onstop/(Q)uit/(C)ontinue?", "Press/Hit any key", "more?" -> Enter (the
        # default = Continue). MegaMud sends a bare CR — never "Q". Stateless: every pager,
        # any number of them, gets the same Enter.
        if _PAGER_RE.search(stripped):
            return ""
        # MajorMUD menu prompt "[MAJORMUD]:" -> enter the realm.
        if _MAJORMUD_MENU_RE.search(stripped):
            return "enter"

        # ── BBS-specific: the scripted steps (User-ID / password / BBS menu), in order ──
        # The pager/menu/HP above already drained the standard MajorMUD prompts, so the
        # script only carries genuinely server-specific prompts and never stalls on a
        # variable-count pager.
        if self._script:
            if self._step < len(self._script):
                pattern, reply = self._script[self._step]
                if pattern.search(stripped):
                    self._step += 1
                    return expand_template(reply, self._vars)
            return None

        # ── No script: built-in User-ID / password / character detection ──
        if self._user_re.search(stripped) and not self._sent_username:
            self._sent_username = True
            return self._cfg.username
        if self._pass_re.search(stripped) and not self._sent_password:
            self._sent_password = True
            return self._cfg.password
        if self._cfg.character and _CHARACTER_RE.search(stripped):
            return self._cfg.character

        return None

    def reset(self) -> None:
        """Reset for a new login attempt (e.g. a relog)."""
        self._step = 0
        self._sent_username = False
        self._sent_password = False
        self.game_full = False
        self.in_game = False
