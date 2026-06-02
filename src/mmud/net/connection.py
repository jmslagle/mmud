from __future__ import annotations
import asyncio

# Telnet control bytes (RFC 854)
IAC  = 0xFF
WILL = 0xFB
WONT = 0xFC
DO   = 0xFD
DONT = 0xFE
SB   = 0xFA   # subnegotiation begin
SE   = 0xF0   # subnegotiation end

# Options we accept / respond to
OPT_ECHO       = 0x01
OPT_SGA        = 0x03  # suppress go-ahead
OPT_TERM_TYPE  = 0x18  # terminal type
OPT_NAWS       = 0x19  # window size

_TERMINAL_TYPE = b"xterm"


class MudConnection:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._iac_buf: bytes = b""

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)

    async def send(self, command: str) -> None:
        assert self._writer
        self._writer.write((command + "\r\n").encode("latin-1"))
        await self._writer.drain()

    async def readline(self) -> str:
        assert self._reader
        raw = await self._reader.readline()
        return self._strip_iac(raw)

    def _strip_iac(self, data: bytes) -> str:
        """Strip IAC sequences, respond to negotiation requests, return clean text."""
        out = bytearray()
        i = 0
        while i < len(data):
            b = data[i]
            if b != IAC:
                out.append(b)
                i += 1
                continue
            if i + 1 >= len(data):
                break  # incomplete — drop
            cmd = data[i + 1]
            if cmd == IAC:
                out.append(IAC)
                i += 2
            elif cmd in (WILL, WONT, DO, DONT):
                if i + 2 < len(data):
                    opt = data[i + 2]
                    self._handle_negotiation(cmd, opt)
                i += 3
            elif cmd == SB:
                # Skip to IAC SE
                end = data.find(bytes([IAC, SE]), i + 2)
                if end >= 0:
                    self._handle_subneg(data[i + 2:end])
                    i = end + 2
                else:
                    break
            else:
                i += 2  # 2-byte IAC command
        return out.decode("latin-1", errors="replace")

    def _handle_negotiation(self, cmd: int, opt: int) -> None:
        """Respond to WILL/WONT/DO/DONT option requests."""
        if self._writer is None:
            return
        if cmd == DO and opt == OPT_TERM_TYPE:
            # Server wants terminal type — agree
            self._writer.write(bytes([IAC, WILL, OPT_TERM_TYPE]))
        elif cmd == DO and opt in (OPT_ECHO, OPT_SGA, OPT_NAWS):
            self._writer.write(bytes([IAC, WONT, opt]))
        elif cmd == WILL and opt in (OPT_ECHO, OPT_SGA):
            self._writer.write(bytes([IAC, DO, opt]))

    def _handle_subneg(self, data: bytes) -> None:
        """Respond to subnegotiation requests (e.g. terminal type query)."""
        if self._writer is None or len(data) < 2:
            return
        opt, req = data[0], data[1]
        if opt == OPT_TERM_TYPE and req == 0x01:  # SEND
            # IAC SB TERM-TYPE IS "xterm" IAC SE
            self._writer.write(
                bytes([IAC, SB, OPT_TERM_TYPE, 0x00]) + _TERMINAL_TYPE + bytes([IAC, SE])
            )

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
