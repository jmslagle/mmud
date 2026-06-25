import asyncio

import pytest

from mmud.net.connection import (
    MudConnection,
    IAC, WILL, WONT, DO, DONT, SB, SE,
    OPT_ECHO, OPT_TERM_TYPE, OPT_NAWS,
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


def test_do_naws_triggers_will_and_sends_window_size():
    # The full-screen editor only lays out correctly when the server knows our real
    # screen size. Accept NAWS (WILL) and send the current grid size, so the door
    # formats for our actual (pane-sized) grid instead of a default.
    w = FakeWriter()
    c = _conn(writer=w)
    c.set_size(80, 50)
    c._strip_iac(bytes([IAC, DO, OPT_NAWS]))
    assert bytes(w.written) == (
        bytes([IAC, WILL, OPT_NAWS])
        + bytes([IAC, SB, OPT_NAWS, 0, 80, 0, 50, IAC, SE]))


def test_set_size_resends_naws_once_active():
    w = FakeWriter()
    c = _conn(writer=w)
    c._strip_iac(bytes([IAC, DO, OPT_NAWS]))   # activate NAWS (default 80x24)
    w.written.clear()
    c.set_size(80, 40)                          # window grew -> re-report
    assert bytes(w.written) == bytes([IAC, SB, OPT_NAWS, 0, 80, 0, 40, IAC, SE])


def test_set_size_before_naws_negotiated_sends_nothing():
    w = FakeWriter()
    c = _conn(writer=w)
    c.set_size(80, 40)                          # server hasn't asked yet
    assert bytes(w.written) == b""


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


def test_prompt_partial_flushes_on_timeout():
    # A prompt (ends with ':') with no newline flushes on the idle timeout.
    import asyncio as _a
    class SlowReader:
        def __init__(self): self._n = 0
        async def read(self, _n):
            self._n += 1
            if self._n == 1:
                return b"[HP=46/MA=12]:"
            await _a.sleep(10)        # never returns more -> forces timeout
            return b""
    c = _conn(reader=SlowReader(), writer=FakeWriter())
    async def run():
        async for line in c.readlines():
            return line
    assert _a.run(_a.wait_for(run(), timeout=2.0)) == "[HP=46/MA=12]:"


def test_prompt_tail_regex_distinguishes_prompts_from_typing():
    # The timeout-flush gate: prompts (and continue/pager prompts) flush; bare
    # echoed typing characters do NOT (so char-mode echo isn't split per key).
    from mmud.net.connection import _PROMPT_TAIL_RE
    for prompt in ("[HP=46/MA=12]:", "(N)onstop, (Q)uit, or (C)ontinue?",
                   "Otherwise type \"new\":", "> ", "[HP=46/MA=12]:\x1b[0m"):
        assert _PROMPT_TAIL_RE.search(prompt), prompt
    for typed in ("l", "lo", "look", "wear padded", "You are carrying club"):
        assert not _PROMPT_TAIL_RE.search(typed), typed


def test_strip_iac_returns_pending_tail_for_split_sequence():
    # A bare trailing IAC byte (incomplete command) is held, not emitted.
    c = _conn()
    text, pending = c._strip_iac_stream(b"abc" + bytes([IAC]))
    assert text == "abc"
    assert pending == bytes([IAC])


def test_strip_iac_stream_resumes_split_sequence():
    c = _conn(writer=FakeWriter())
    text1, pending = c._strip_iac_stream(b"x" + bytes([IAC, DO]))
    assert text1 == "x"
    assert pending == bytes([IAC, DO])
    # The remainder (the option byte) completes the DO TERM_TYPE negotiation.
    text2, pending2 = c._strip_iac_stream(pending + bytes([OPT_TERM_TYPE]) + b"y")
    assert text2 == "y"
    assert pending2 == b""


def test_strip_iac_stream_holds_incomplete_subnegotiation():
    c = _conn(writer=FakeWriter())
    # SB started but no IAC SE yet -> hold the whole thing as pending.
    chunk = b"a" + bytes([IAC, SB, OPT_TERM_TYPE, 0x01])
    text, pending = c._strip_iac_stream(chunk)
    assert text == "a"
    assert pending == bytes([IAC, SB, OPT_TERM_TYPE, 0x01])


def test_readlines_calls_on_raw_with_escape_sequences():
    # The raw tap sees the FULL stream incl. ANSI escapes; line-framing unchanged.
    reader = FakeReader([b"\x1b[1;1Hhi\nbye\n"])
    c = _conn(reader=reader, writer=FakeWriter())
    raw_chunks: list[str] = []
    c.on_raw = raw_chunks.append

    async def run():
        out = []
        async for line in c.readlines():
            out.append(line)
            if len(out) >= 2:
                break
        return out

    lines = asyncio.run(run())
    assert lines == ["\x1b[1;1Hhi\n", "bye\n"]
    assert "".join(raw_chunks) == "\x1b[1;1Hhi\nbye\n"


def test_readlines_raw_tap_handles_iac_split_across_chunks():
    # IAC WILL ECHO split across two reads: stripped from BOTH lines and raw.
    reader = FakeReader([b"hi" + bytes([IAC, WILL]), bytes([OPT_ECHO]) + b"there\n"])
    c = _conn(reader=reader, writer=FakeWriter())
    raw_chunks: list[str] = []
    c.on_raw = raw_chunks.append

    async def run():
        async for line in c.readlines():
            return line

    assert asyncio.run(run()) == "hithere\n"
    # on_raw receives each stripped chunk verbatim, incl. the newline the
    # emulator needs — so the raw stream is the line text, not the framed line.
    assert "".join(raw_chunks) == "hithere\n"
