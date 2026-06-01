from __future__ import annotations
import asyncio


class MudConnection:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)

    async def send(self, command: str) -> None:
        assert self._writer
        self._writer.write((command + "\r\n").encode("latin-1"))
        await self._writer.drain()

    async def readline(self) -> str:
        assert self._reader
        data = await self._reader.readline()
        # Strip telnet IAC sequences (0xFF prefix bytes)
        clean = bytes(b for b in data if b < 0xFF)
        return clean.decode("latin-1", errors="replace")

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
