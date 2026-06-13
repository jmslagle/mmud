from __future__ import annotations
import asyncio
import re
from typing import AsyncIterator

# Telnet control bytes (RFC 854)
IAC  = 0xFF
WILL = 0xFB
WONT = 0xFC
DO   = 0xFD
DONT = 0xFE
SB   = 0xFA   # subnegotiation begin
SE   = 0xF0   # subnegotiation end

OPT_ECHO       = 0x01
OPT_SGA        = 0x03
OPT_TERM_TYPE  = 0x18
OPT_NAWS       = 0x19

_TERMINAL_TYPE = b"xterm"

# Emit a partial line (prompt) if no new data arrives within this window
_PROMPT_TIMEOUT = 0.08   # 80ms — fast enough to feel live, slow enough to batch lines
# A buffered partial is flushed on timeout only if it looks like a prompt (ends
# with a prompt terminator, allowing trailing ANSI). Otherwise it waits for a
# newline — so per-character echo (character-mode typing) isn't split into one
# line per keystroke. A longer idle still flushes anything (no indefinite hang).
_PROMPT_TAIL_RE = re.compile(r"[:>?#]\s*(?:\x1b\[[0-9;?]*[A-Za-z]\s*)*$")
_IDLE_FLUSH_TICKS = 12   # ~1s at 80ms — flush non-prompt partials eventually


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

    async def send_raw(self, data: str) -> None:
        """Write `data` verbatim — no appended newline, no buffering.

        Used by the TUI's character mode so each keystroke (including control
        sequences like arrow keys) reaches the server immediately, which the
        in-game full-screen editor requires.
        """
        if self._writer is None:
            return
        self._writer.write(data.encode("latin-1"))
        await self._writer.drain()

    async def readlines(self) -> AsyncIterator[str]:
        """
        Async generator yielding MUD output lines.

        Emits complete lines immediately on \\n. If no \\n arrives within
        _PROMPT_TIMEOUT seconds, emits whatever partial data is buffered —
        this catches prompts like "[HP=141/216]:" that never end with \\n.
        """
        assert self._reader
        buf = b""
        idle = 0
        while True:
            try:
                chunk = await asyncio.wait_for(
                    self._reader.read(4096), timeout=_PROMPT_TIMEOUT
                )
            except asyncio.TimeoutError:
                # Nothing new arrived. Flush a buffered partial only if it looks
                # like a prompt, or after a longer idle — otherwise per-character
                # echo (character mode) becomes one line per keystroke.
                idle += 1
                if buf.strip():
                    text = self._strip_iac(buf)
                    if _PROMPT_TAIL_RE.search(text) or idle >= _IDLE_FLUSH_TICKS:
                        yield text
                        buf = b""
                        idle = 0
                continue

            idle = 0
            if not chunk:
                # Server closed the connection
                if buf:
                    yield self._strip_iac(buf)
                break

            buf += chunk

            # Emit all complete lines
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                yield self._strip_iac(line + b"\n")

    # Keep readline() for tests that use it directly
    async def readline(self) -> str:
        assert self._reader
        data = await self._reader.readline()
        return self._strip_iac(data)

    def _strip_iac(self, data: bytes) -> str:
        """Strip/respond to IAC sequences, return clean text."""
        out = bytearray()
        i = 0
        while i < len(data):
            b = data[i]
            if b != IAC:
                out.append(b)
                i += 1
                continue
            if i + 1 >= len(data):
                break
            cmd = data[i + 1]
            if cmd == IAC:
                out.append(IAC)
                i += 2
            elif cmd in (WILL, WONT, DO, DONT):
                if i + 2 < len(data):
                    self._handle_negotiation(cmd, data[i + 2])
                i += 3
            elif cmd == SB:
                end = data.find(bytes([IAC, SE]), i + 2)
                if end >= 0:
                    self._handle_subneg(data[i + 2:end])
                    i = end + 2
                else:
                    break
            else:
                i += 2
        return out.decode("latin-1", errors="replace")

    def _handle_negotiation(self, cmd: int, opt: int) -> None:
        if self._writer is None:
            return
        if cmd == DO and opt == OPT_TERM_TYPE:
            self._writer.write(bytes([IAC, WILL, OPT_TERM_TYPE]))
        elif cmd == DO and opt in (OPT_ECHO, OPT_SGA, OPT_NAWS):
            self._writer.write(bytes([IAC, WONT, opt]))
        elif cmd == WILL and opt in (OPT_ECHO, OPT_SGA):
            self._writer.write(bytes([IAC, DO, opt]))

    def _handle_subneg(self, data: bytes) -> None:
        if self._writer is None or len(data) < 2:
            return
        opt, req = data[0], data[1]
        if opt == OPT_TERM_TYPE and req == 0x01:
            self._writer.write(
                bytes([IAC, SB, OPT_TERM_TYPE, 0x00]) + _TERMINAL_TYPE + bytes([IAC, SE])
            )

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
