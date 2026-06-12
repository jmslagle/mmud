import asyncio

import pytest

from mmud.net.connection import (
    MudConnection,
    IAC, WILL, WONT, DO, DONT, SB, SE,
    OPT_ECHO, OPT_TERM_TYPE,
)


class FakeReader:
    """Minimal asyncio.StreamReader stand-in for readlines()/readline()."""

    def __init__(self, chunks):
        # chunks: list of bytes objects; an empty bytes b"" signals EOF.
        self._chunks = list(chunks)

    async def read(self, _n):
        if self._chunks:
            return self._chunks.pop(0)
        return b""  # EOF

    async def readline(self):
        return self._chunks.pop(0) if self._chunks else b""


class FakeWriter:
    """Captures bytes written so IAC negotiation replies can be asserted."""

    def __init__(self):
        self.written = bytearray()

    def write(self, data):
        self.written.extend(data)

    async def drain(self):
        return None


def _conn(reader=None, writer=None):
    c = MudConnection("host", 23)
    c._reader = reader
    c._writer = writer
    return c


def test_plain_text_passes_through():
    c = _conn()
    assert c._strip_iac(b"hello world\n") == "hello world\n"


def test_iac_negotiation_sequence_is_stripped():
    c = _conn(writer=FakeWriter())
    data = b"pre" + bytes([IAC, WILL, OPT_ECHO]) + b"post"
    assert c._strip_iac(data) == "prepost"


def test_escaped_iac_iac_collapses_to_single_ff_byte():
    c = _conn()
    out = c._strip_iac(b"a" + bytes([IAC, IAC]) + b"b")
    assert out == "a\xffb"
    assert out.encode("latin-1") == b"a\xffb"


def test_subnegotiation_block_is_stripped():
    c = _conn(writer=FakeWriter())
    data = (
        b"x"
        + bytes([IAC, SB, OPT_TERM_TYPE, 0x01, IAC, SE])
        + b"y"
    )
    assert c._strip_iac(data) == "xy"


def test_do_term_type_triggers_will_reply():
    w = FakeWriter()
    c = _conn(writer=w)
    c._strip_iac(bytes([IAC, DO, OPT_TERM_TYPE]))
    assert bytes(w.written) == bytes([IAC, WILL, OPT_TERM_TYPE])


def test_do_echo_triggers_wont_reply():
    w = FakeWriter()
    c = _conn(writer=w)
    c._strip_iac(bytes([IAC, DO, OPT_ECHO]))
    assert bytes(w.written) == bytes([IAC, WONT, OPT_ECHO])


def test_negotiation_without_writer_does_not_crash():
    c = _conn(writer=None)
    # _handle_negotiation early-returns when no writer; just strips.
    assert c._strip_iac(bytes([IAC, DO, OPT_TERM_TYPE])) == ""


def _collect_lines(reader, limit):
    async def run():
        c = _conn(reader=reader)
        out = []
        async for line in c.readlines():
            out.append(line)
            if len(out) >= limit:
                break
        return out
    return asyncio.run(run())


def test_readlines_frames_on_newline():
    reader = FakeReader([b"line one\nline two\n"])
    assert _collect_lines(reader, 2) == ["line one\n", "line two\n"]


def test_readlines_splits_chunk_spanning_lines():
    # A single read returns multiple complete lines plus a partial remainder.
    reader = FakeReader([b"alpha\nbeta\ngamm", b"a\n"])
    assert _collect_lines(reader, 3) == ["alpha\n", "beta\n", "gamma\n"]


def test_readlines_emits_buffered_line_on_eof():
    # No trailing newline; server closes -> remaining buffer is flushed.
    reader = FakeReader([b"prompt:"])
    assert _collect_lines(reader, 1) == ["prompt:"]


def test_readlines_strips_iac_in_framed_line():
    reader = FakeReader([b"hi" + bytes([IAC, WILL, OPT_ECHO]) + b"there\n"])
    c = _conn(reader=reader, writer=FakeWriter())

    async def run():
        async for line in c.readlines():
            return line

    assert asyncio.run(run()) == "hithere\n"


def test_send_appends_crlf():
    w = FakeWriter()
    c = _conn(writer=w)
    asyncio.run(c.send("look"))
    assert bytes(w.written) == b"look\r\n"


def test_send_raw_writes_verbatim_no_newline():
    w = FakeWriter()
    c = _conn(writer=w)
    asyncio.run(c.send_raw("a"))
    asyncio.run(c.send_raw("\x1b[A"))   # an arrow-key sequence
    assert bytes(w.written) == b"a\x1b[A"   # no appended CRLF


def test_send_raw_without_writer_is_noop():
    c = _conn(writer=None)
    asyncio.run(c.send_raw("x"))   # must not raise
