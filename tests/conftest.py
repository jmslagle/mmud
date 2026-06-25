import pathlib
import pytest

DATA_DIR = pathlib.Path(__file__).parent.parent / "extractions/mm103s.exe.extracted/45DAD/Default"

@pytest.fixture
def data_dir():
    return DATA_DIR


class FakeConnection:
    """Replays a scripted server transcript; records every command sent.

    Drop-in for MudConnection in MudBot: bot._conn = FakeConnection(lines).
    """

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.sent: list[str] = []
        self.closed = False

    async def connect(self) -> None:
        pass

    async def send(self, command: str) -> None:
        self.sent.append(command)

    async def readlines(self):
        for line in self._lines:
            yield line

    async def close(self) -> None:
        self.closed = True


def make_transcript_bot(lines: list[str], **bot_kwargs):
    """MudBot wired to a FakeConnection. await bot.run(), then assert on bot._conn.sent."""
    from mmud.bot import MudBot
    bot = MudBot("transcript", 0, patterns=bot_kwargs.pop("patterns", []), **bot_kwargs)
    bot._conn = FakeConnection(lines)
    return bot
