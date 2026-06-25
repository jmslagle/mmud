"""Server-side terminal emulator for full-screen MajorMUD/Worldgroup display.

Wraps pyte's HistoryScreen + Stream. MajorMUD is a full-screen ANSI BBS door:
the in-game editor, menus and "scroll" displays position the cursor to arbitrary
row/col and redraw in place, which an append-only log cannot show. Raw bytes
(IAC-stripped, pre-line-framing) feed this emulator for DISPLAY; the existing
line parser keeps driving SEMANTICS independently.
"""
from __future__ import annotations

import pyte
from rich.style import Style
from rich.text import Text

# Map pyte colour names to Rich-friendly names. pyte emits ANSI colour names
# ("red", "brightblue" style "brown" etc.) or 6-hex strings for 256/truecolor.
# "default" means "no explicit colour" -> let Rich use the terminal default.
_PYTE_COLOR_ALIASES = {
    "brown": "yellow",       # pyte calls SGR 33 "brown"
    "brightblack": "bright_black",
    "brightred": "bright_red",
    "brightgreen": "bright_green",
    "brightbrown": "bright_yellow",
    "brightblue": "bright_blue",
    "brightmagenta": "bright_magenta",
    "brightcyan": "bright_cyan",
    "brightwhite": "bright_white",
}


def _rich_color(name: str) -> str | None:
    """Translate a pyte colour token to a Rich colour spec, or None for default."""
    if not name or name == "default":
        return None
    if len(name) == 6 and all(c in "0123456789abcdefABCDEF" for c in name):
        return "#" + name
    return _PYTE_COLOR_ALIASES.get(name, name)


class TerminalEmulator:
    """A fixed-size screen buffer fed raw ANSI text.

    Size defaults to 80x24 (the BBS default MajorMUD assumes; the bot declines
    telnet NAWS, so the server never learns a real window size). columns/lines
    are params so a future NAWS phase can resize.
    """

    def __init__(self, columns: int = 80, lines: int = 24, history: int = 2000) -> None:
        self.columns = columns
        self.lines = lines
        self._screen = pyte.HistoryScreen(columns, lines, history=history, ratio=0.5)
        self._stream = pyte.Stream(self._screen)

    def feed(self, text: str) -> None:
        """Feed raw ANSI text (already IAC-stripped) into the screen."""
        self._stream.feed(text)

    def resize(self, lines: int | None = None, columns: int | None = None) -> None:
        """Resize the screen grid to fill the TUI pane.

        Only `lines` typically varies: the bot declines telnet NAWS, so the
        server keeps formatting for 80 columns. Sizing the grid to the pane both
        uses the whole box for scrolling game text AND fixes the in-game editor's
        "off by one" — a grid at least as tall as the server's assumed screen
        means its top-aligned full-screen redraw never scrolls off the top.
        """
        new_lines = self.lines if lines is None else lines
        new_cols = self.columns if columns is None else columns
        if new_lines == self.lines and new_cols == self.columns:
            return
        self.lines = new_lines
        self.columns = new_cols
        self._screen.resize(new_lines, new_cols)

    def display(self) -> list[str]:
        """Clean visible rows (length == lines, each padded to columns)."""
        return list(self._screen.display)

    def cursor(self) -> tuple[int, int]:
        """0-based (x, y) cursor position."""
        return (self._screen.cursor.x, self._screen.cursor.y)

    def take_dirty(self) -> set[int]:
        """Return the set of changed line indices and clear it."""
        dirty = set(self._screen.dirty)
        self._screen.dirty.clear()
        return dirty

    def render_line(self, y: int) -> Text:
        """Render screen row `y` as a Rich Text with per-cell colour/attributes."""
        row = self._screen.buffer[y]
        text = Text()
        for x in range(self.columns):
            char = row[x]
            style = Style(
                color=_rich_color(char.fg),
                bgcolor=_rich_color(char.bg),
                bold=bool(char.bold),
                italic=bool(char.italics),
                underline=bool(char.underscore),
                reverse=bool(char.reverse),
            )
            text.append(char.data or " ", style=style)
        return text

    def rich_lines(self) -> list[Text]:
        """All `lines` rows rendered as Rich Text (top to bottom)."""
        return [self.render_line(y) for y in range(self.lines)]

    def prev_page(self) -> None:
        """Scroll the scrollback view up one page (PageUp)."""
        self._screen.prev_page()

    def next_page(self) -> None:
        """Scroll the scrollback view down one page (PageDown)."""
        self._screen.next_page()
