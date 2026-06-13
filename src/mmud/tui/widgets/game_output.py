from __future__ import annotations
from rich.text import Text
from textual.events import Key
from textual.message import Message
from textual.widgets import RichLog


class GameOutput(RichLog):
    """Scrolling display of raw MUD server output.

    Focusable: Tab into it to enter *character mode*, where every keystroke is
    forwarded raw to the server (no line buffering, no local echo) — what the
    in-game full-screen editor needs. Shift+Tab moves focus back out; Ctrl/Alt/
    F-key app bindings still work while it is focused.
    """

    can_focus = True

    # Non-printable keys that need a raw byte sequence in the in-game ANSI
    # editor. Tune against the live server if a key misbehaves.
    _RAW_KEYS = {
        "enter": "\r",
        "backspace": "\x08",
        "delete": "\x7f",
        "tab": "\t",
        "escape": "\x1b",
        "up": "\x1b[A",
        "down": "\x1b[B",
        "right": "\x1b[C",
        "left": "\x1b[D",
        "home": "\x1b[H",
        "end": "\x1b[F",
    }

    class NewLine(Message):
        def __init__(self, line: str) -> None:
            super().__init__()
            self.line = line

    class RawInput(Message):
        """A keystroke captured in character mode, to be sent raw to the server."""

        def __init__(self, data: str) -> None:
            super().__init__()
            self.data = data

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text_lines: list[str] = []

    def raw_for_key(self, event: Key) -> str | None:
        """Translate a key event into the raw bytes to send, or None to ignore.

        Printable characters (incl. the letter 'f' and space) pass through as
        themselves. Shift+Tab is reserved for leaving character mode; Ctrl/Alt
        combos and F1..F12 are reserved for app bindings. Everything else maps
        through `_RAW_KEYS`.
        """
        if event.is_printable and event.character:
            return event.character
        key = event.key
        if key == "shift+tab":
            return None
        if key.startswith(("ctrl+", "alt+")):
            return None
        if key.startswith("f") and key[1:].isdigit():
            return None
        return self._RAW_KEYS.get(key)

    def on_key(self, event: Key) -> None:
        if not self.has_focus:
            return
        data = self.raw_for_key(event)
        if data is None:
            return
        self.post_message(self.RawInput(data))
        event.stop()
        event.prevent_default()

    def on_game_output_new_line(self, message: NewLine) -> None:
        clean = message.line.rstrip("\r\n")
        self._text_lines.append(clean)
        # Convert ANSI escape codes to Rich Text so colours render properly
        try:
            self.write(Text.from_ansi(clean))
        except Exception:
            self.write(clean)

    def renderable_lines_text(self) -> str:
        """Return all visible text joined — for testing only."""
        return "\n".join(self._text_lines)
