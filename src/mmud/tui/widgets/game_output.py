from __future__ import annotations
from textual.message import Message
from textual.widgets import RichLog


class GameOutput(RichLog):
    """Scrolling display of raw MUD server output. Not focusable — focus stays on the input."""

    can_focus = False

    class NewLine(Message):
        def __init__(self, line: str) -> None:
            super().__init__()
            self.line = line

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text_lines: list[str] = []

    def on_game_output_new_line(self, message: NewLine) -> None:
        clean = message.line.rstrip("\r\n")
        self._text_lines.append(clean)
        self.write(clean)

    def renderable_lines_text(self) -> str:
        """Return all visible text joined — for testing only."""
        return "\n".join(self._text_lines)
