from __future__ import annotations
import asyncio
import re
from typing import AsyncIterator, Callable

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
        self.on_raw: Callable[[str], None] | None = None
        self._iac_pending = b""   # incomplete IAC sequence carried across chunks
        self._size = (80, 24)     # (cols, rows) reported to the server via NAWS
        self._naws_active = False  # server agreed to receive our window size

    def set_size(self, cols: int, rows: int) -> None:
        """Update the window size reported to the server (NAWS). Re-sends once NAWS
        has been negotiated — so the full-screen editor re-lays-out when the grid
        is resized to the TUI pane."""
        size = (cols, rows)
        if size == self._size:
            return
        self._size = size
        if self._naws_active:
            self._write_naws()

    def _write_naws(self) -> None:
        if self._writer is None:
            return
        cols, rows = self._size
        body = bytearray()
        for v in ((cols >> 8) & 0xFF, cols & 0xFF, (rows >> 8) & 0xFF, rows & 0xFF):
            body.append(v)
            if v == IAC:
                body.append(IAC)   # 0xFF inside a subnegotiation must be doubled
        self._writer.write(bytes([IAC, SB, OPT_NAWS]) + bytes(body) + bytes([IAC, SE]))

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

        Each read chunk is IAC-stripped (sequences spanning chunks are carried
        in self._iac_pending), pushed verbatim to the raw display tap
        (self.on_raw) BEFORE line framing, then framed on \\n. If no \\n arrives
        within _PROMPT_TIMEOUT, a buffered partial flushes if it looks like a
        prompt, or after a longer idle (so per-char echo isn't split per key).
        """
        assert self._reader
        buf = ""          # decoded text awaiting a newline
        idle = 0
        while True:
            try:
                chunk = await asyncio.wait_for(
                    self._reader.read(4096), timeout=_PROMPT_TIMEOUT
                )
            except asyncio.TimeoutError:
                # Nothing new arrived. Flush a buffered partial only if it looks
                # like a prompt, or after a longer idle — otherwise per-character
                # echo (character mode) becomes one line per keystroke. on_raw is
                # NOT called here: these flushes re-emit already-tapped text.
                idle += 1
                if buf.strip():
                    if _PROMPT_TAIL_RE.search(buf) or idle >= _IDLE_FLUSH_TICKS:
                        yield buf
                        buf = ""
                        idle = 0
                continue

            idle = 0
            if not chunk:
                # Server closed the connection
                if self._iac_pending:
                    self._iac_pending = b""   # drop a dangling partial on close
                if buf:
                    yield buf
                break

            text, self._iac_pending = self._strip_iac_stream(self._iac_pending + chunk)
            if text and self.on_raw is not None:
                self.on_raw(text)
            buf += text

            # Emit all complete lines
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                yield line + "\n"

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

    def _strip_iac_stream(self, data: bytes) -> tuple[str, bytes]:
        """Like _strip_iac, but returns any trailing INCOMPLETE IAC sequence as
        `pending` bytes instead of dropping it, so a sequence split across read
        chunks survives. Caller must prepend `pending` to the next chunk.
        """
        out = bytearray()
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b != IAC:
                out.append(b)
                i += 1
                continue
            if i + 1 >= n:                       # lone trailing IAC
                return out.decode("latin-1", errors="replace"), data[i:]
            cmd = data[i + 1]
            if cmd == IAC:
                out.append(IAC)
                i += 2
            elif cmd in (WILL, WONT, DO, DONT):
                if i + 2 >= n:                   # missing option byte
                    return out.decode("latin-1", errors="replace"), data[i:]
                self._handle_negotiation(cmd, data[i + 2])
                i += 3
            elif cmd == SB:
                end = data.find(bytes([IAC, SE]), i + 2)
                if end < 0:                      # SE not arrived yet
                    return out.decode("latin-1", errors="replace"), data[i:]
                self._handle_subneg(data[i + 2:end])
                i = end + 2
            else:
                i += 2
        return out.decode("latin-1", errors="replace"), b""

    def _handle_negotiation(self, cmd: int, opt: int) -> None:
        if self._writer is None:
            return
        if cmd == DO and opt == OPT_TERM_TYPE:
            self._writer.write(bytes([IAC, WILL, OPT_TERM_TYPE]))
        elif cmd == DO and opt == OPT_NAWS:
            # Accept NAWS and report our real grid size so the server formats the
            # full-screen editor for our actual screen (it never probes via ESC[6n).
            self._writer.write(bytes([IAC, WILL, OPT_NAWS]))
            self._naws_active = True
            self._write_naws()
        elif cmd == DO and opt in (OPT_ECHO, OPT_SGA):
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
