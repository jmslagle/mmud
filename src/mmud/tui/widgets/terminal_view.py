"""Pyte-backed full-screen terminal widget for the TUI.

Replaces the append-only RichLog GameOutput. Renders the TerminalEmulator's
screen buffer (sized to the pane, 80 cols x pane height) with per-cell colour
from pyte, supports scrollback (PageUp/PageDown + mouse wheel), and preserves
character mode: Tab focuses it, then each
keystroke is forwarded raw to the server (RawInput -> send_raw) for the in-game
full-screen editor. The DISPLAY comes from the emulator; SEMANTICS still flow
through the bot's line parser independently.
"""
from __future__ import annotations

from rich.console import Group
from textual.events import Key
from textual.message import Message
from textual.widgets import Static

from mmud.terminal import TerminalEmulator


class TerminalView(Static):
    """Live terminal screen with scrollback and character-mode raw input."""

    can_focus = True

    # Fill the pane vertically. A Static defaults to auto height (sizing to its
    # 24-line content), which left the bottom of the pane empty — fill it so the
    # grid can grow to use the whole box.
    DEFAULT_CSS = """
    TerminalView {
        height: 1fr;
    }
    """

    # Never shrink the grid below the BBS default the server assumes; growing it
    # to the pane height fills the box and keeps the editor from scrolling off.
    _MIN_LINES = 24

    # Identical to the old GameOutput mapping — keep the char-mode contract.
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

    class RawInput(Message):
        """A keystroke captured in character mode, to be sent raw to the server."""

        def __init__(self, data: str) -> None:
            super().__init__()
            self.data = data

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._emulator = TerminalEmulator()

    def attach_emulator(self, emulator: TerminalEmulator) -> None:
        """Bind to the bot's emulator instance so re-renders show live state."""
        self._emulator = emulator
        self._fit_emulator()

    def on_resize(self, event) -> None:
        self._fit_emulator()

    def _fit_emulator(self) -> None:
        """Grow the emulator grid to the pane's content height (columns stay 80).
        Route through the bot when connected so it reports the new size to the
        server (NAWS) — that's what keeps the full-screen editor aligned."""
        rows = max(self._MIN_LINES, self.content_size.height)
        if rows != self._emulator.lines:
            bot = None
            try:
                bot = getattr(self.app, "_bot", None)
            except Exception:
                bot = None
            if bot is not None and hasattr(bot, "set_terminal_size"):
                bot.set_terminal_size(self._emulator.columns, rows)
            else:
                self._emulator.resize(rows)
        self.refresh_screen()

    def raw_for_key(self, event: Key) -> str | None:
        """Key -> raw bytes to send, or None to ignore. (Same rules as before.)"""
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
        # Scrollback navigation stays local to the widget.
        if event.key in ("pageup", "page_up"):
            self._emulator.prev_page()
            self.refresh_screen()
            event.stop()
            event.prevent_default()
            return
        if event.key in ("pagedown", "page_down"):
            self._emulator.next_page()
            self.refresh_screen()
            event.stop()
            event.prevent_default()
            return
        data = self.raw_for_key(event)
        if data is None:
            return
        self.post_message(self.RawInput(data))
        event.stop()
        event.prevent_default()

    def on_mouse_scroll_up(self, event) -> None:
        """Mouse wheel up -> scroll back into history (same as PageUp)."""
        self._emulator.prev_page()
        self.refresh_screen()
        event.stop()
        event.prevent_default()

    def on_mouse_scroll_down(self, event) -> None:
        """Mouse wheel down -> scroll forward toward live (same as PageDown)."""
        self._emulator.next_page()
        self.refresh_screen()
        event.stop()
        event.prevent_default()

    def refresh_screen(self) -> None:
        """Re-render the emulator's current screen into this widget."""
        self.update(Group(*self._emulator.rich_lines()))

    def screen_text(self) -> str:
        """Plain visible text of the current screen — for testing."""
        return "\n".join(self._emulator.display())
