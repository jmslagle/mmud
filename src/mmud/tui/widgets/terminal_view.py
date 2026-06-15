"""Pyte-backed full-screen terminal widget for the TUI.

Replaces the append-only RichLog GameOutput. Renders the TerminalEmulator's
80x24 screen buffer with per-cell colour from pyte, supports scrollback
(PageUp/PageDown), and preserves character mode: Tab focuses it, then each
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

    def refresh_screen(self) -> None:
        """Re-render the emulator's current screen into this widget."""
        self.update(Group(*self._emulator.rich_lines()))

    def screen_text(self) -> str:
        """Plain visible text of the current screen — for testing."""
        return "\n".join(self._emulator.display())
