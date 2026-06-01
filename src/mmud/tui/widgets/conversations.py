from __future__ import annotations
from textual.message import Message
from textual.widgets import RichLog

_CHANNEL_COLORS = {
    "tell": "yellow",
    "shout": "red",
    "party": "magenta",
    "gossip": "cyan",
}


class ConversationsPane(RichLog):
    """Displays player-to-player and channel messages."""

    class NewMessage(Message):
        def __init__(self, channel: str, sender: str, text: str) -> None:
            super().__init__()
            self.channel = channel
            self.sender = sender
            self.text = text

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text_lines: list[str] = []

    def on_conversations_pane_new_message(self, message: NewMessage) -> None:
        color = _CHANNEL_COLORS.get(message.channel, "white")
        line = f"[{message.channel}] {message.sender}: {message.text}"
        self._text_lines.append(line)
        self.write(f"[{color}]{line}[/{color}]")

    def renderable_lines_text(self) -> str:
        return "\n".join(self._text_lines)
