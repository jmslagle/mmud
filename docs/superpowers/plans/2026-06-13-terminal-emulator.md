# Terminal Emulator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Follow TDD strictly: write the failing test, run it (confirm RED), write the *minimal* implementation, run again (confirm GREEN), commit. Never paste a placeholder — every code block in this plan is complete and final.

**Goal:** MajorMUD/Worldgroup is a full-screen ANSI BBS app (in-game editor, menus, "scroll" displays) that positions the cursor to arbitrary row/col and redraws in place. The current append-only displays — the TUI `GameOutput` (a `RichLog`) and the web `Terminal.tsx` (`ansi-to-html` on per-line text) — plus the per-line cursor renderer in `src/mmud/parser/ansi.py` cannot render cross-line full-screen redraws. This plan adds a **real screen-buffer terminal emulator** to both frontends.

**Architecture (the three confirmed decisions — design to these, do NOT re-litigate):**

1. **Hybrid emulation.** The connection's RAW byte stream (post-telnet-IAC strip, pre-line-framing) is the shared contract. Server-side **pyte** drives the TUI; **xterm.js** drives the web Terminal — both fed the same raw stream.
2. **Full TUI terminal view.** Replace the append-only `RichLog` `GameOutput` with a pyte-backed terminal widget (live screen + scrollback), rendering colour from pyte's per-cell buffer.
3. **Display/semantics split (the key architecture).** Raw bytes drive the terminal DISPLAY (pyte / xterm.js). The EXISTING line parsing keeps driving SEMANTICS — `GameEventBus` events, stats, automation, and the conversations/players/stats panels stay line/event-driven and **UNCHANGED**. `_process_line` and `LineReceived` are untouched as a *semantics* pipeline; only the *display* consumers move to emulation. Parsing migration to screen-based reads is a LATER, optional phase (Task 6 documents it; it is NOT done now).

**Tech Stack:** Python 3.11+, `pyte` 0.8.2 (new dep), `rich` (already present via textual), Textual (already present). Web: `@xterm/xterm` (new npm dep), React 18, vitest (already present). Tests: pytest + pytest-asyncio (`asyncio_mode = "auto"`), FastAPI `TestClient`.

**Behavior invariant:** The full suite (~569 tests) must stay green. The emulator is *additive*: `LineReceived` is still emitted for semantics even though the TUI/web stop consuming it for *display*. Char mode (Tab → focus → raw keystrokes via `send_raw`) must survive the `GameOutput` → `TerminalView` swap.

---

## Tooling facts (verified — quote these, don't improvise)

- **pyte 0.8.2** (PyPI). API used in this plan:
  - `screen = pyte.HistoryScreen(columns, lines, history=N, ratio=0.5)`
  - `stream = pyte.Stream(screen)`
  - `stream.feed(text)` — accepts a **str** (feed the IAC-stripped latin-1 text).
  - `screen.display` → `list[str]` of clean visible rows (length == lines).
  - `screen.buffer` → dict-like grid; `screen.buffer[y][x]` is a `Char` with attributes `.data .fg .bg .bold .italics .underscore .reverse`. Colours are names (`"default"`, `"red"`, …) or 6-hex strings (`"ff8800"`) for 256/truecolor.
  - `screen.cursor.x`, `screen.cursor.y`.
  - `screen.dirty` → a `set[int]` of changed line indices; **clear it after rendering** (`screen.dirty.clear()`).
  - HistoryScreen scrollback: `screen.history` (with `.top` / `.bottom` deques), `screen.prev_page()`, `screen.next_page()`.
  - pyte expects `TERM=linux` semantics; it does **not** auto-resize.
- **xterm.js** (npm `@xterm/xterm`): `term.write(data)` consumes raw ANSI; handles full-screen, colours, scrollback natively. CSS comes from `@xterm/xterm/css/xterm.css`.

## Screen size / NAWS

`src/mmud/net/connection.py` handles `OPT_NAWS` (0x19) by **declining** it: `_handle_negotiation` replies `IAC WONT NAWS` to `DO NAWS`, and never sends a NAWS subnegotiation. So the bot never advertises a window size. **Use a fixed 80×24** screen for the emulator (the classic BBS default MajorMUD assumes). Make `columns`/`lines` constructor params of `TerminalEmulator` (defaults 80/24) so a future NAWS phase can wire them, but do not add NAWS now.

---

## File Map

```
pyproject.toml                                  MODIFY — add pyte dep
src/mmud/terminal.py                            NEW    — TerminalEmulator (pyte wrapper)
src/mmud/net/connection.py                      MODIFY — on_raw tap, cross-chunk IAC tail
src/mmud/events.py                              MODIFY — add RawOutput, ScreenUpdated
src/mmud/bot.py                                 MODIFY — own TerminalEmulator, feed it, emit events
src/mmud/tui/widgets/terminal_view.py          NEW    — pyte-backed Textual widget
src/mmud/tui/app.py                             MODIFY — swap GameOutput -> TerminalView
src/mmud/web/server.py                          MODIFY — broadcast RawOutput
src/mmud/web/frontend/package.json             MODIFY — add @xterm/xterm
src/mmud/web/frontend/src/components/Terminal.tsx  REWRITE — xterm.js component
src/mmud/web/frontend/src/useWebSocket.ts      MODIFY — route RawOutput via callback ref
tests/test_terminal.py                          NEW
tests/test_connection.py                        MODIFY — raw tap + split-IAC tests
tests/test_events.py                            MODIFY — RawOutput/ScreenUpdated dataclass tests
tests/test_bot.py                               MODIFY — emulator wiring via transcript harness
tests/test_tui_widgets.py                       MODIFY — TerminalView render + char-mode tests
tests/test_web_serialize.py                     MODIFY — cover RawOutput/ScreenUpdated
tests/test_web_endpoints.py                     MODIFY — RawOutput broadcast over /ws
src/mmud/web/frontend/src/Terminal.test.ts      NEW    — vitest RawOutput routing
README.md                                       MODIFY — terminal emulation note + Phase 2 plan
```

---

### Task 1 — `pyte` dependency + `TerminalEmulator`

**Files:**
- Modify: `pyproject.toml`
- Create: `src/mmud/terminal.py`
- Test: `tests/test_terminal.py`

- [ ] **Step 1: Add the dependency and install**

Edit `pyproject.toml`, changing the `dependencies` line:

```toml
dependencies = ["textual>=0.62.0", "tomlkit>=0.12.0", "pyte>=0.8.2"]
```

Then install it:

```
pip install -e .
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_terminal.py`:

```python
from __future__ import annotations
from rich.text import Text
from mmud.terminal import TerminalEmulator


def test_default_size_is_80x24():
    term = TerminalEmulator()
    rows = term.display()
    assert len(rows) == 24
    assert all(len(r) == 80 for r in rows)


def test_plain_text_appears_on_screen():
    term = TerminalEmulator()
    term.feed("Hello MUD!")
    assert term.display()[0].startswith("Hello MUD!")


def test_cursor_positioned_overwrite_redraws_in_place():
    # CSI row;col H homes the cursor; the second write overwrites the first.
    term = TerminalEmulator()
    term.feed("\x1b[1;1Hfirst")
    term.feed("\x1b[1;1Hsecond")
    assert term.display()[0].startswith("second")


def test_cursor_reports_x_y():
    term = TerminalEmulator()
    term.feed("\x1b[3;5H")        # row 3, col 5 (1-based)
    x, y = term.cursor()
    assert (x, y) == (4, 2)       # pyte cursor is 0-based


def test_take_dirty_returns_and_clears():
    term = TerminalEmulator()
    term.feed("line zero")
    dirty = term.take_dirty()
    assert 0 in dirty
    assert term.take_dirty() == set()   # cleared after first take


def test_render_line_carries_colour_and_bold():
    term = TerminalEmulator()
    term.feed("\x1b[1;31mRED\x1b[0m")    # bold red
    text = term.render_line(0)
    assert isinstance(text, Text)
    assert text.plain.startswith("RED")
    # first cell is bold red
    span = text.spans[0]
    style = span.style
    assert style.bold is True
    assert style.color is not None and style.color.name == "red"


def test_rich_lines_returns_one_text_per_row():
    term = TerminalEmulator()
    term.feed("abc")
    lines = term.rich_lines()
    assert len(lines) == 24
    assert all(isinstance(t, Text) for t in lines)
    assert lines[0].plain.startswith("abc")
```

- [ ] **Step 3: Run it — confirm RED**

```
python -m pytest tests/test_terminal.py -q
```

- [ ] **Step 4: Implement `TerminalEmulator`**

Create `src/mmud/terminal.py`:

```python
"""Server-side terminal emulator for full-screen MajorMUD/Worldgroup display.

Wraps pyte's HistoryScreen + Stream. MajorMUD is a full-screen ANSI BBS door:
the in-game editor, menus and "scroll" displays position the cursor to arbitrary
row/col and redraw in place, which an append-only log cannot show. Raw bytes
(IAC-stripped, pre-line-framing) feed this emulator for DISPLAY; the existing
line parser keeps driving SEMANTICS independently.
"""
from __future__ import annotations

import pyte
from rich.style import Style
from rich.text import Text

# Map pyte colour names to Rich-friendly names. pyte emits ANSI colour names
# ("red", "brightblue" style "brown" etc.) or 6-hex strings for 256/truecolor.
# "default" means "no explicit colour" -> let Rich use the terminal default.
_PYTE_COLOR_ALIASES = {
    "brown": "yellow",       # pyte calls SGR 33 "brown"
    "brightblack": "bright_black",
    "brightred": "bright_red",
    "brightgreen": "bright_green",
    "brightbrown": "bright_yellow",
    "brightblue": "bright_blue",
    "brightmagenta": "bright_magenta",
    "brightcyan": "bright_cyan",
    "brightwhite": "bright_white",
}


def _rich_color(name: str) -> str | None:
    """Translate a pyte colour token to a Rich colour spec, or None for default."""
    if not name or name == "default":
        return None
    if len(name) == 6 and all(c in "0123456789abcdefABCDEF" for c in name):
        return "#" + name
    return _PYTE_COLOR_ALIASES.get(name, name)


class TerminalEmulator:
    """A fixed-size screen buffer fed raw ANSI text.

    Size defaults to 80x24 (the BBS default MajorMUD assumes; the bot declines
    telnet NAWS, so the server never learns a real window size). columns/lines
    are params so a future NAWS phase can resize.
    """

    def __init__(self, columns: int = 80, lines: int = 24, history: int = 2000) -> None:
        self.columns = columns
        self.lines = lines
        self._screen = pyte.HistoryScreen(columns, lines, history=history, ratio=0.5)
        self._stream = pyte.Stream(self._screen)

    def feed(self, text: str) -> None:
        """Feed raw ANSI text (already IAC-stripped) into the screen."""
        self._stream.feed(text)

    def display(self) -> list[str]:
        """Clean visible rows (length == lines, each padded to columns)."""
        return list(self._screen.display)

    def cursor(self) -> tuple[int, int]:
        """0-based (x, y) cursor position."""
        return (self._screen.cursor.x, self._screen.cursor.y)

    def take_dirty(self) -> set[int]:
        """Return the set of changed line indices and clear it."""
        dirty = set(self._screen.dirty)
        self._screen.dirty.clear()
        return dirty

    def render_line(self, y: int) -> Text:
        """Render screen row `y` as a Rich Text with per-cell colour/attributes."""
        row = self._screen.buffer[y]
        text = Text()
        for x in range(self.columns):
            char = row[x]
            style = Style(
                color=_rich_color(char.fg),
                bgcolor=_rich_color(char.bg),
                bold=bool(char.bold),
                italic=bool(char.italics),
                underline=bool(char.underscore),
                reverse=bool(char.reverse),
            )
            text.append(char.data or " ", style=style)
        return text

    def rich_lines(self) -> list[Text]:
        """All `lines` rows rendered as Rich Text (top to bottom)."""
        return [self.render_line(y) for y in range(self.lines)]

    def prev_page(self) -> None:
        """Scroll the scrollback view up one page (PageUp)."""
        self._screen.prev_page()

    def next_page(self) -> None:
        """Scroll the scrollback view down one page (PageDown)."""
        self._screen.next_page()
```

> **Note on `screen.buffer[y][x]`:** pyte's buffer is a `defaultdict`; indexing a never-written cell yields a default blank `Char` (`.data == " "`, `.fg == .bg == "default"`, flags False), so `render_line` is safe across the whole 80×24 grid.

- [ ] **Step 5: Run — confirm GREEN**

```
python -m pytest tests/test_terminal.py -q
```

- [ ] **Step 6: Commit**

```
git add pyproject.toml src/mmud/terminal.py tests/test_terminal.py
git commit -m "feat: TerminalEmulator — pyte-backed 80x24 screen buffer with Rich rendering"
```

---

### Task 2 — Connection raw-stream tap (post-IAC, pre-line-framing)

The emulator needs the IAC-stripped byte stream **before** line framing, including all escape sequences. Add an `on_raw: Callable[[str], None] | None` hook the read loop calls with each IAC-stripped chunk, while `readlines()` keeps yielding lines exactly as before. IAC sequences can span chunk boundaries, so keep a pending tail.

**Files:**
- Modify: `src/mmud/net/connection.py`
- Test: `tests/test_connection.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_connection.py`:

```python
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
    assert "".join(raw_chunks) == "hithere"
```

- [ ] **Step 2: Run — confirm RED**

```
python -m pytest tests/test_connection.py -q
```

- [ ] **Step 3: Implement the tap + streaming IAC strip**

In `src/mmud/net/connection.py`:

Add `Callable` to the typing import (line 4):

```python
from typing import AsyncIterator, Callable
```

Add `on_raw` in `__init__` (after `self._writer = None`):

```python
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self.on_raw: Callable[[str], None] | None = None
        self._iac_pending = b""   # incomplete IAC sequence carried across chunks
```

Add a new streaming variant of `_strip_iac` that returns `(text, pending_tail)` and is used by the read loop. The existing `_strip_iac` (used by `readline()` and the many existing unit tests) stays UNCHANGED. Insert this method directly after `_strip_iac`:

```python
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
```

Now rewrite `readlines()` to strip per-chunk via `_strip_iac_stream`, feed the raw tap, then line-frame on the *decoded* text. Replace the whole `readlines` method body with:

```python
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
                idle += 1
                if buf.strip():
                    if _PROMPT_TAIL_RE.search(buf) or idle >= _IDLE_FLUSH_TICKS:
                        yield buf
                        buf = ""
                        idle = 0
                continue

            idle = 0
            if not chunk:
                if self._iac_pending:
                    self._iac_pending = b""   # drop a dangling partial on close
                if buf:
                    yield buf
                break

            text, self._iac_pending = self._strip_iac_stream(self._iac_pending + chunk)
            if text and self.on_raw is not None:
                self.on_raw(text)
            buf += text

            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                yield line + "\n"
```

> **Why this preserves existing behavior:** lines are still framed on `\n` and still include the trailing `\n`; `_strip_iac_stream` calls the same `_handle_negotiation`/`_handle_subneg` responders. The previous code split bytes then called `_strip_iac` per line; now we strip first then split text — identical output for whole sequences, and now correct for split ones. The existing `_strip_iac` and all its tests are untouched. The EOF/prompt-flush tests still hold (`test_readlines_emits_buffered_line_on_eof`, `test_prompt_partial_flushes_on_timeout`).

- [ ] **Step 4: Run — confirm GREEN (whole connection suite)**

```
python -m pytest tests/test_connection.py -q
```

- [ ] **Step 5: Commit**

```
git add src/mmud/net/connection.py tests/test_connection.py
git commit -m "feat: connection raw-stream tap (on_raw) with cross-chunk IAC handling"
```

---

### Task 3 — Events + bot wiring

Add `RawOutput(data: str)` and `ScreenUpdated()` events. The bot constructs a `TerminalEmulator`, sets `_conn.on_raw` to feed it + emit `RawOutput(data)`, and emits `ScreenUpdated()` after feeding. `_process_line` and `LineReceived` stay exactly as-is (semantics).

**Files:**
- Modify: `src/mmud/events.py`
- Modify: `src/mmud/bot.py`
- Test: `tests/test_events.py`, `tests/test_bot.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_events.py`:

```python
def test_raw_output_event_fields():
    from mmud.events import RawOutput
    e = RawOutput(data="\x1b[1;1Hhi")
    assert e.data == "\x1b[1;1Hhi"


def test_screen_updated_event_constructs():
    from mmud.events import ScreenUpdated
    e = ScreenUpdated()
    assert isinstance(e, ScreenUpdated)


def test_raw_output_and_screen_updated_dispatch_on_bus():
    from mmud.events import GameEventBus, RawOutput, ScreenUpdated
    bus = GameEventBus()
    seen: list[object] = []
    bus.subscribe(RawOutput, seen.append)
    bus.subscribe(ScreenUpdated, seen.append)
    bus.post(RawOutput(data="x"))
    bus.post(ScreenUpdated())
    assert len(seen) == 2
    assert isinstance(seen[0], RawOutput)
    assert isinstance(seen[1], ScreenUpdated)
```

Append to `tests/test_bot.py` (uses the existing `make_transcript_bot` harness from `conftest.py`):

```python
def test_bot_feeds_terminal_emulator_and_emits_raw(make_transcript_bot=None):
    import asyncio
    from tests.conftest import make_transcript_bot
    from mmud.events import GameEventBus, RawOutput, ScreenUpdated

    bus = GameEventBus()
    raw_events: list[str] = []
    screen_events: list[object] = []
    bus.subscribe(RawOutput, lambda e: raw_events.append(e.data))
    bus.subscribe(ScreenUpdated, screen_events.append)

    bot = make_transcript_bot([], event_bus=bus)
    # The FakeConnection has no on_raw plumbing; drive the bot's hook directly,
    # exactly as the real readlines() loop would per chunk.
    bot._feed_raw("\x1b[1;1Hello")

    assert raw_events == ["\x1b[1;1Hello"]
    assert len(screen_events) == 1
    # The emulator received the bytes (cursor-home + text shows on row 0).
    assert bot._terminal.display()[0].startswith("ello")  # 'H' consumed by CSI? no:
```

> **Implementation note for the worker:** the assertion's exact visible text depends on pyte's parse of `\x1b[1;1Hello` — `\x1b[1;1H` is the cursor-home CSI, then `ello` prints (the `H` is the CSI final byte). Run the impl, observe `bot._terminal.display()[0]`, and set the assertion to the real prefix (`"ello"`). This is the one place to adapt the literal to pyte's output; keep the structure.

- [ ] **Step 2: Run — confirm RED**

```
python -m pytest tests/test_events.py tests/test_bot.py -q
```

- [ ] **Step 3: Add the events**

Append to `src/mmud/events.py` (after `ConfigChanged`, before `GameEventBus`):

```python
@dataclass
class RawOutput:
    data: str   # raw IAC-stripped server text (ANSI intact) for the terminal emulator


@dataclass
class ScreenUpdated:
    pass        # signal: the terminal emulator's screen changed; re-render
```

- [ ] **Step 4: Wire the bot**

In `src/mmud/bot.py`, extend the events import (the existing multi-line import at lines 10-15):

```python
from mmud.events import (
    GameEventBus, LineReceived, HpChanged, MpChanged,
    EffectApplied, EffectRemoved, CombatChanged, RoomChanged, MonstersSeen,
    ConversationReceived, PlayerSeen, SessionStatUpdated, TaskChanged,
    ConditionChanged, HangupTriggered, DbImported, DbCollision,
    RawOutput, ScreenUpdated,
)
```

Add the emulator import near the other top-of-file imports (after `from mmud.net.connection import MudConnection`):

```python
from mmud.terminal import TerminalEmulator
```

In `MudBot.__init__`, right after `self._conn = MudConnection(host, port)` (line 99), create the emulator and install the hook:

```python
        self._conn = MudConnection(host, port)
        self._terminal = TerminalEmulator()
        self._conn.on_raw = self._feed_raw
```

Add the `_feed_raw` method (place it next to `_emit`, after the `_emit` method around line 254):

```python
    def _feed_raw(self, data: str) -> None:
        """Connection raw-stream tap: drive the terminal emulator (DISPLAY) and
        broadcast the raw chunk to xterm.js. Independent of _process_line, which
        keeps driving SEMANTICS (events/stats/automation) from framed lines.
        """
        self._terminal.feed(data)
        self._emit(RawOutput(data=data))
        self._emit(ScreenUpdated())
```

> The bot constructs `MudConnection` itself, so `on_raw` is always installed for the real connection. The transcript harness swaps in a `FakeConnection` (no `on_raw`), which is why tests call `bot._feed_raw(...)` directly. `_process_line` and `LineReceived` are unchanged.

- [ ] **Step 5: Run — confirm GREEN**

```
python -m pytest tests/test_events.py tests/test_bot.py -q
```

- [ ] **Step 6: Commit**

```
git add src/mmud/events.py src/mmud/bot.py tests/test_events.py tests/test_bot.py
git commit -m "feat: bot owns TerminalEmulator; raw tap emits RawOutput + ScreenUpdated"
```

---

### Task 4 — TUI `TerminalView` widget (replaces `GameOutput`)

A new pyte-backed widget that renders the emulator's screen (per-cell colour, cursor, scrollback on PageUp/Down), focusable with the SAME char-mode raw-key behaviour as today's `GameOutput`. We **keep `GameOutput`'s `RawInput` message contract and `raw_for_key` logic** so `app.py`'s `on_game_output_raw_input` / `send_raw` path and the existing pure `raw_for_key` test keep working — `TerminalView` reuses that exact mapping.

**Files:**
- Create: `src/mmud/tui/widgets/terminal_view.py`
- Modify: `src/mmud/tui/app.py`
- Test: `tests/test_tui_widgets.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui_widgets.py`:

```python
from mmud.tui.widgets.terminal_view import TerminalView
from mmud.terminal import TerminalEmulator


class _TermApp(App):
    def compose(self) -> ComposeResult:
        yield TerminalView()


@pytest.mark.asyncio
async def test_terminal_view_renders_emulator_screen():
    app = _TermApp()
    async with app.run_test() as pilot:
        view = app.query_one(TerminalView)
        view.attach_emulator(TerminalEmulator())
        view._emulator.feed("Hello MUD!")
        view.refresh_screen()
        await pilot.pause(0.1)
        assert "Hello MUD!" in view.screen_text()


def test_terminal_view_raw_for_key_matches_game_output():
    # Char-mode key mapping is identical to the old GameOutput contract.
    view = TerminalView()
    assert view.raw_for_key(_key("a", "a")) == "a"
    assert view.raw_for_key(_key("enter")) == "\r"
    assert view.raw_for_key(_key("up")) == "\x1b[A"
    assert view.raw_for_key(_key("shift+tab")) is None
    assert view.raw_for_key(_key("ctrl+k")) is None
    assert view.raw_for_key(_key("f1")) is None


@pytest.mark.asyncio
async def test_terminal_view_char_mode_sends_raw():
    class _StubConn:
        def __init__(self): self.raw = []
        async def send_raw(self, data): self.raw.append(data)

    class _StubBot:
        def __init__(self): self._conn = _StubConn()

    config = MudConfig()
    app = MegaMudApp(config=config, host="localhost", port=4000)
    async with app.run_test() as pilot:
        app._bot = _StubBot()
        view = app.query_one(TerminalView)
        view.focus()
        await pilot.pause()
        assert view.has_focus
        await pilot.press("a", "enter", "up")
        await pilot.pause()
        assert app._bot._conn.raw == ["a", "\r", "\x1b[A"]
        assert app.query_one("#command-input", Input).value == ""


@pytest.mark.asyncio
async def test_app_screen_updated_rerenders_terminal():
    config = MudConfig()
    app = MegaMudApp(config=config, host="localhost", port=4000)
    async with app.run_test() as pilot:
        view = app.query_one(TerminalView)
        view._emulator.feed("ALIVE")
        app._bus.post(__import__("mmud.events", fromlist=["ScreenUpdated"]).ScreenUpdated())
        await pilot.pause(0.1)
        assert "ALIVE" in view.screen_text()


@pytest.mark.asyncio
async def test_tab_from_command_line_focuses_terminal_view():
    config = MudConfig()
    app = MegaMudApp(config=config, host="localhost", port=4000)
    async with app.run_test() as pilot:
        app.query_one("#command-input", Input).focus()
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert app.query_one(TerminalView).has_focus
```

> **Removing obsolete `GameOutput` tests:** delete the now-defunct `_GameApp`, `test_game_output_displays_line`, `test_game_output_raw_for_key_translation`, `test_char_mode_sends_raw_when_game_output_focused`, and `test_tab_from_command_line_focuses_main_window` from `tests/test_tui_widgets.py` — they reference `GameOutput`, which `app.py` no longer composes. Their behaviours are re-covered by the `TerminalView` tests above. Keep the `GameOutput` import only if other tests still need it; otherwise drop it.

- [ ] **Step 2: Run — confirm RED**

```
python -m pytest tests/test_tui_widgets.py -q
```

- [ ] **Step 3: Implement `TerminalView`**

Create `src/mmud/tui/widgets/terminal_view.py`:

```python
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
from rich.text import Text
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
```

- [ ] **Step 4: Rewire `app.py`**

In `src/mmud/tui/app.py`:

Replace the `GameOutput` import (line 17):

```python
from mmud.tui.widgets.terminal_view import TerminalView
```

Add `ScreenUpdated` to the events import (lines 12-15):

```python
from mmud.events import (
    GameEventBus, LineReceived, HpChanged, MpChanged,
    ConversationReceived, PlayerSeen, SessionStatUpdated, ScreenUpdated,
)
```

In `compose()` replace the `GameOutput` line:

```python
    def compose(self) -> ComposeResult:
        with Horizontal(id="main-area"):
            yield TerminalView(id="game-output")
            yield RightPanel(
                default_tab=self._config.ui.default_tab,
                id="right-panel",
            )
        yield StatsBar(id="stats-bar")
        yield Input(placeholder="Enter command...", id="command-input")
```

Rename the char-mode handler to match the new widget's `RawInput` message (Textual derives the handler name from the message's namespace — `TerminalView.RawInput` → `on_terminal_view_raw_input`). Replace `on_game_output_raw_input`:

```python
    def on_terminal_view_raw_input(self, message: TerminalView.RawInput) -> None:
        """Character mode: a keystroke captured by the focused TerminalView is
        forwarded raw to the server (no newline) for the in-game editor."""
        if self._bot is not None:
            self.run_worker(self._bot._conn.send_raw(message.data))
```

In `on_key`, replace the `GameOutput` focus guard and the PageUp/PageDown block (lines 95-105). The TerminalView now handles its own scrollback while focused, so app-level PageUp/Down is no longer needed:

```python
    def on_key(self, event: Key) -> None:
        """Route all keystrokes to the command input (telnet-like behavior)."""
        # In character mode the focused TerminalView already claimed the key
        # (TerminalView.on_key stops it); nothing to do here.
        if self.query_one(TerminalView).has_focus:
            return

        # Numpad macros (MACROS.MD) — fire as movement hotkeys.
        if (cmd := self._macro_keys.get(event.key)) is not None:
            if self._bot is not None:
                self.run_worker(self._bot._conn.send(cmd))
            event.prevent_default()
            return

        inp = self.query_one("#command-input", Input)
        if inp.has_focus:
            return  # Input already has it, nothing to do

        # Don't steal Ctrl/Alt/F-key bindings
        if event.key.startswith(("ctrl+", "alt+", "f")) or event.key in ("escape",):
            return

        # Route printable characters to the Input, inserting them directly
        if event.is_printable and event.character:
            inp.focus()
            inp.insert_text_at_cursor(event.character)
            event.prevent_default()
```

In `_wire_bus`, replace the `LineReceived → GameOutput` subscription with a `ScreenUpdated → TerminalView` re-render, and attach the bot's emulator. Replace the first lines of `_wire_bus`:

```python
    def _wire_bus(self) -> None:
        term = self.query_one(TerminalView)
        stats = self.query_one("#stats-bar", StatsBar)

        # DISPLAY: the bot's TerminalEmulator drives the screen. Re-render on
        # each ScreenUpdated. (LineReceived still fires for SEMANTICS consumers,
        # but the terminal no longer renders from it.)
        self._bus.subscribe(
            ScreenUpdated,
            lambda e: term.refresh_screen(),
        )
        self._bus.subscribe(
            HpChanged,
            lambda e: stats.post_message(StatsBar.HpUpdate(hp=e.hp, max_hp=e.max_hp)),
        )
```

(Leave the rest of `_wire_bus` — MpChanged, ConversationReceived, PlayerSeen, SessionStatUpdated — unchanged.)

`LineReceived` is no longer used by `app.py`; drop it from the import line to avoid an unused-import lint:

```python
from mmud.events import (
    GameEventBus, HpChanged, MpChanged,
    ConversationReceived, PlayerSeen, SessionStatUpdated, ScreenUpdated,
)
```

After the bot is created in `action_toggle_connect`, bind its emulator to the view so re-renders show live state. Insert right after `self._bot_task = asyncio.create_task(self._bot.run())`:

```python
            self.query_one(TerminalView).attach_emulator(self._bot._terminal)
```

Finally, in `_handle_bot_command`, the `out = self.query_one(GameOutput)` and `out.post_message(GameOutput.NewLine(...))` calls write bot feedback lines into the display. `TerminalView` has no `NewLine`. Route bot-command feedback through the emulator instead by writing the text into it. Replace the body's `out = self.query_one(GameOutput)` with a small helper and replace each `out.post_message(GameOutput.NewLine(text))` with `self._echo(text)`. Add this helper method:

```python
    def _echo(self, text: str) -> None:
        """Write a local bot-feedback line into the terminal emulator + redraw."""
        view = self.query_one(TerminalView)
        view._emulator.feed("\r\n" + text)
        view.refresh_screen()
```

Then in `_handle_bot_command`, delete the `out = self.query_one(GameOutput)` line and replace every `out.post_message(GameOutput.NewLine(X))` with `self._echo(X)`. For example:

```python
        if verb in ("loop", "l"):
            if self._bot is None:
                self._echo("[bot] Not connected")
                return
            msg = self._bot.start_loop(arg)
            self._echo(f"[bot] {msg}")
            running = self._bot._loop_runner and self._bot._loop_runner.running
            self.sub_title = (
                f"{self._host}:{self._port} [looping]" if running
                else f"{self._host}:{self._port} [connected]"
            )
```

> Apply the same `out.post_message(GameOutput.NewLine(...))` → `self._echo(...)` substitution for every remaining branch in `_handle_bot_command` (`stop`, `goto`, `paths`, `status`, `help`, the unknown-command fallthrough). When connected, `self._bot._terminal` IS the view's emulator (bound in `action_toggle_connect`), so feedback lands on the live screen; before connect it lands on the view's standalone emulator. Both render via `refresh_screen()`.

- [ ] **Step 5: Run — confirm GREEN**

```
python -m pytest tests/test_tui_widgets.py -q
```

- [ ] **Step 6: Delete the dead `GameOutput` widget**

`GameOutput` is no longer imported anywhere in `src/`. Confirm and remove it:

```
grep -rn "GameOutput" src/ tests/
git rm src/mmud/tui/widgets/game_output.py
```

(If the grep shows any remaining `src/` reference, fix that reference first. Test-file references should already be gone from Step 1.)

- [ ] **Step 7: Run the full TUI + app suite — confirm GREEN**

```
python -m pytest tests/test_tui_widgets.py -q
```

- [ ] **Step 8: Commit**

```
git add src/mmud/tui/widgets/terminal_view.py src/mmud/tui/app.py tests/test_tui_widgets.py
git rm src/mmud/tui/widgets/game_output.py
git commit -m "feat: TUI TerminalView (pyte-backed) replaces RichLog GameOutput; char mode preserved"
```

---

### Task 5 — Web: broadcast `RawOutput` + xterm.js frontend

Backend: add `RawOutput` to the broadcast set (`serialize_event` already handles any dataclass). Frontend: add `@xterm/xterm`, replace `Terminal.tsx` with an xterm.js terminal that `term.write(ev.data)` on `RawOutput`, and route `RawOutput` outside the `panelReducer` (xterm owns its own buffer) via a callback ref. Other panels (Conversations/Players/Stats) keep their existing events.

**Files:**
- Modify: `src/mmud/web/server.py`
- Modify: `tests/test_web_serialize.py`, `tests/test_web_endpoints.py`
- Modify: `src/mmud/web/frontend/package.json`
- Rewrite: `src/mmud/web/frontend/src/components/Terminal.tsx`
- Modify: `src/mmud/web/frontend/src/useWebSocket.ts`
- Create: `src/mmud/web/frontend/src/Terminal.test.ts`

- [ ] **Step 1: Write the failing backend tests**

In `tests/test_web_serialize.py`, add two cases to the `CASES` list (so `test_serialize_event` covers them AND `test_every_event_type_is_covered` — which asserts every uppercase event in `mmud.events` is covered — keeps passing). Add after the `TravelEnded` case:

```python
    (ev.RawOutput("\x1b[1;1Hhi"), {"type": "RawOutput", "data": "\x1b[1;1Hhi"}),
    (ev.ScreenUpdated(), {"type": "ScreenUpdated"}),
```

> `ScreenUpdated` has no fields, so `dataclasses.asdict` yields `{}` and `serialize_event` returns `{"type": "ScreenUpdated"}`.

In `tests/test_web_endpoints.py`, add a broadcast test (mirrors `test_ws_broadcasts_posted_event`):

```python
def test_ws_broadcasts_raw_output(client, fake_bot):
    from mmud.events import RawOutput
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "Snapshot"
        fake_bot._bus.post(RawOutput(data="\x1b[2J"))
        msg = ws.receive_json()
        assert msg == {"type": "RawOutput", "data": "\x1b[2J"}
```

- [ ] **Step 2: Run — confirm RED**

```
python -m pytest tests/test_web_serialize.py tests/test_web_endpoints.py -q
```

- [ ] **Step 3: Add `RawOutput` to the broadcast set**

In `src/mmud/web/server.py`, extend `_EVENT_TYPES` (lines 14-21). Add `ev.RawOutput` (do NOT add `ScreenUpdated` — that's a TUI-only re-render signal; the web frontend redraws from `RawOutput` itself):

```python
_EVENT_TYPES: tuple[type, ...] = (
    ev.LineReceived, ev.HpChanged, ev.MpChanged, ev.RoomChanged,
    ev.EffectApplied, ev.EffectRemoved, ev.CombatChanged,
    ev.ConversationReceived, ev.PlayerSeen, ev.PathStarted, ev.PathStepped,
    ev.SessionStatUpdated, ev.MonstersSeen, ev.TaskChanged,
    ev.ConditionChanged, ev.HangupTriggered, ev.DbImported, ev.DbCollision,
    ev.TravelResynced, ev.TravelEnded, ev.RawOutput,
)
```

- [ ] **Step 4: Run — confirm GREEN (backend)**

```
python -m pytest tests/test_web_serialize.py tests/test_web_endpoints.py -q
```

- [ ] **Step 5: Add the npm dep**

In `src/mmud/web/frontend/package.json`, add to `dependencies`:

```json
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "ansi-to-html": "^0.7.2",
    "@xterm/xterm": "^5.5.0"
  },
```

Then:

```
npm --prefix src/mmud/web/frontend install
```

> `ansi-to-html` may now be unused; leave it in `package.json` for this task to avoid churn (Task 6 / a later cleanup can remove it if no other component imports it).

- [ ] **Step 6: Write the failing vitest**

Create `src/mmud/web/frontend/src/Terminal.test.ts`:

```ts
import { describe, it, expect, vi } from "vitest";
import { routeRawOutput } from "./useWebSocket";

describe("routeRawOutput", () => {
  it("writes RawOutput.data to the terminal sink", () => {
    const write = vi.fn();
    routeRawOutput({ type: "RawOutput", data: "\x1b[2Jhi" }, write);
    expect(write).toHaveBeenCalledWith("\x1b[2Jhi");
  });

  it("ignores non-RawOutput events", () => {
    const write = vi.fn();
    routeRawOutput({ type: "HpChanged", hp: 1, max_hp: 2 }, write);
    expect(write).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 7: Run — confirm RED**

```
npm --prefix src/mmud/web/frontend run test
```

- [ ] **Step 8: Add the routing helper + wire the WS hook**

In `src/mmud/web/frontend/src/useWebSocket.ts`, add an exported `routeRawOutput` helper and a `rawSink` ref the hook calls for `RawOutput` (so xterm — which owns its own buffer — gets the stream outside the panel reducer). Replace the file with:

```ts
import { useEffect, useReducer, useRef } from "react";
import { initialPanelState, panelReducer, PanelEvent } from "./panelState";

/** Forward a RawOutput event's data to a terminal write sink. Pure + testable. */
export function routeRawOutput(
  ev: PanelEvent,
  write: (data: string) => void,
): void {
  if (ev.type === "RawOutput" && typeof ev.data === "string") {
    write(ev.data);
  }
}

export function useWebSocket(url = "/ws") {
  const [state, dispatch] = useReducer(panelReducer, initialPanelState);
  const wsRef = useRef<WebSocket | null>(null);
  // xterm.js holds its own screen buffer; RawOutput bypasses the reducer and
  // is written straight to the terminal via this sink (set by the Terminal).
  const rawSinkRef = useRef<(data: string) => void>(() => {});

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}${url}`);
    wsRef.current = ws;
    ws.onmessage = (e) => {
      const ev = JSON.parse(e.data) as PanelEvent;
      routeRawOutput(ev, (data) => rawSinkRef.current(data));
      dispatch(ev);
    };
    return () => ws.close();
  }, [url]);

  return { state, rawSinkRef };
}

export async function sendCommand(cmd: string): Promise<void> {
  await fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cmd }),
  });
}

export async function quickTool(action: string): Promise<void> {
  await fetch("/api/quicktool", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
}
```

> **Caller update:** `useWebSocket` now returns `{ state, rawSinkRef }` instead of `state`. Update `App.tsx`'s call site accordingly (Step 10).

- [ ] **Step 9: Rewrite `Terminal.tsx` as an xterm.js component**

Replace `src/mmud/web/frontend/src/components/Terminal.tsx`:

```tsx
import React, { useEffect, useRef } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { PanelState } from "../panelState";

// DISPLAY comes from the raw server stream (RawOutput) written straight into
// xterm.js, which owns its own screen buffer + scrollback. The room header /
// prompt below still read SEMANTICS from PanelState (HpChanged/RoomChanged/etc).
export function Terminal({
  state,
  rawSinkRef,
}: {
  state: PanelState;
  rawSinkRef: React.MutableRefObject<(data: string) => void>;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const term = new XTerm({
      cols: 80,
      rows: 24,
      convertEol: true,
      fontFamily: "monospace",
      theme: { background: "#000000", foreground: "#c0c0c0" },
    });
    term.open(containerRef.current);
    termRef.current = term;
    // Point the WS hook's raw sink at this terminal's write().
    rawSinkRef.current = (data: string) => term.write(data);
    return () => {
      rawSinkRef.current = () => {};
      term.dispose();
      termRef.current = null;
    };
  }, [rawSinkRef]);

  const v = state.vitals;
  return (
    <div className="terminal">
      <div className="room-header">
        {state.room.name || state.room.code} {state.vitals.inCombat ? "[COMBAT]" : ""}
      </div>
      <div className="terminal-body" ref={containerRef} />
      <div className="prompt">
        [HP={v.hp}/{v.maxHp}] [MP={v.mana}/{v.maxMana}]
      </div>
    </div>
  );
}
```

- [ ] **Step 10: Update `App.tsx` for the new hook return + Terminal props**

`useWebSocket()` now returns `{ state, rawSinkRef }`. Find the call in `src/mmud/web/frontend/src/App.tsx` and update it. The exact lines depend on the current file, so READ it first; the change is mechanical:

- Change `const state = useWebSocket();` → `const { state, rawSinkRef } = useWebSocket();`
- Change `<Terminal state={state} />` → `<Terminal state={state} rawSinkRef={rawSinkRef} />`

> If `App.tsx` destructures differently, adapt — but `routeRawOutput` and the backend are already verified by tests; this wiring is the only manual step. The `state.terminal` array (LineReceived) is no longer read by `Terminal.tsx`; leave `panelState`'s `terminal` field and its reducer case in place (harmless; still serialized) to avoid touching the panel reducer tests.

- [ ] **Step 11: Run frontend + backend tests — confirm GREEN**

```
npm --prefix src/mmud/web/frontend run test
python -m pytest tests/test_web_serialize.py tests/test_web_endpoints.py -q
```

- [ ] **Step 12: Build the frontend (typecheck guard)**

```
npm --prefix src/mmud/web/frontend run build
```

- [ ] **Step 13: Commit**

```
git add src/mmud/web/server.py tests/test_web_serialize.py tests/test_web_endpoints.py \
        src/mmud/web/frontend/package.json src/mmud/web/frontend/package-lock.json \
        src/mmud/web/frontend/src/components/Terminal.tsx \
        src/mmud/web/frontend/src/useWebSocket.ts \
        src/mmud/web/frontend/src/Terminal.test.ts \
        src/mmud/web/frontend/src/App.tsx
git commit -m "feat: web xterm.js terminal fed by RawOutput stream"
```

---

### Task 6 — Docs + phased note

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a "Terminal emulation" section to `README.md`**

Read `README.md`, find the architecture/display section, and add:

```markdown
## Terminal emulation

MajorMUD/Worldgroup is a full-screen ANSI BBS app: the in-game editor, menus,
and scroll displays position the cursor to arbitrary row/col and redraw in
place. An append-only log cannot show these cross-line redraws, so both
frontends run a real screen-buffer terminal emulator over the connection's RAW
byte stream (post-telnet-IAC, pre-line-framing):

- **TUI:** `src/mmud/terminal.py` (`TerminalEmulator`, a pyte `HistoryScreen`)
  drives `TerminalView` — a live 80×24 screen with colour from pyte's per-cell
  buffer and PageUp/PageDown scrollback. Character mode (Tab to focus, raw
  keystrokes for the in-game editor) is preserved.
- **Web:** the raw stream is broadcast as `RawOutput` events and written
  straight into an `@xterm/xterm` terminal, which owns its own buffer.

### Display / semantics split

This is the key architecture. Raw bytes drive the terminal **DISPLAY** (pyte /
xterm.js). The existing line parser keeps driving **SEMANTICS** independently:
`MudBot._process_line` still runs the full parser pipeline and emits
`LineReceived`, `HpChanged`, `RoomChanged`, `ConversationReceived`, etc., which
feed the stats/conversations/players panels and all automation. The terminal
display and the event-driven semantics are two parallel consumers of the same
connection.

### Phase 2 (future, NOT implemented)

Today the parsers read framed lines (cursor moves replayed per-line by
`src/mmud/parser/ansi.py`). A future phase can migrate the line parsers to read
the emulator's `screen.display` rows instead — cursor-proof parsing of
full-screen redraws (room panes, the editor, scroll output) — and then retire
`parser/ansi.py`. This is intentionally deferred: it touches every parser and
the whole semantics test surface, and the current per-line parsing already
passes the suite.
```

- [ ] **Step 2: Commit**

```
git add README.md
git commit -m "docs: terminal emulation (display/semantics split) + Phase 2 note"
```

---

## Final verification

Run the entire suite and confirm everything is green (the ~569 baseline plus the new tests; net count rises as tests are added and the few `GameOutput` tests are replaced):

```
python -m pytest -q
npm --prefix src/mmud/web/frontend run test
npm --prefix src/mmud/web/frontend run build
```

Then use **superpowers:finishing-a-development-branch** to decide how to integrate.

---

## Self-review checklist (the author verified these against the real code)

- **Decision 1 (hybrid emulation):** `connection.on_raw` taps the IAC-stripped, pre-line-framing stream (Task 2); the bot fans it to pyte (`TerminalEmulator.feed`) and to `RawOutput` for xterm.js (Task 3). One raw contract, two renderers. ✔
- **Decision 2 (full TUI terminal view):** `TerminalView` (pyte-backed, colour from `screen.buffer`, scrollback via `prev_page`/`next_page`) replaces the `RichLog` `GameOutput`, which is deleted (Task 4). ✔
- **Decision 3 (display/semantics split):** `_process_line` and `LineReceived` are untouched; the stats/conversations/players panels keep their existing event subscriptions. Only the terminal *display* moves to emulation (TUI subscribes `ScreenUpdated`; web writes `RawOutput`). `LineReceived` still fires but no longer drives display. Phase-2 migration is documented, not done (Task 6). ✔
- **No placeholders:** every code block is complete and final.
- **Type-consistent signatures:** `TerminalEmulator` API (`feed(str)->None`, `display()->list[str]`, `cursor()->tuple[int,int]`, `take_dirty()->set[int]`, `render_line(int)->Text`, `rich_lines()->list[Text]`, `prev_page()/next_page()->None`) is used identically in Tasks 1, 3, 4. Event field names are consistent: `RawOutput.data: str`, `ScreenUpdated` (no fields), matching `serialize_event`, `panelState`, and the web tests. `connection.on_raw: Callable[[str], None] | None` matches `bot._feed_raw(self, data: str) -> None`.
- **~569 tests stay green:** the emulator is additive. `_strip_iac` and its tests are untouched (a new `_strip_iac_stream` is added). The `GameOutput`-specific TUI tests are replaced by equivalent `TerminalView` tests. `test_every_event_type_is_covered` in `test_web_serialize.py` is kept green by adding `RawOutput`/`ScreenUpdated` to its `CASES`.
- **Char mode survives the swap:** `TerminalView` reuses `GameOutput`'s `_RAW_KEYS` + `raw_for_key` logic and emits `RawInput`; `app.py`'s handler is renamed to `on_terminal_view_raw_input` and still calls `send_raw`. Tab-focus and per-keystroke raw send are re-tested.

## Adaptations the real code forced (call-outs for the worker)

- **No `RichLog` cursor renderer for the TUI display anymore**, but `parser/ansi.py` is **NOT** removed — `bot._process_line` still calls `render_line`/`visible_text` for the semantics pipeline (`LineReceived` carries `render_line(line, color=True)`; parsing uses `visible_text`). Leave it; Phase 2 retires it.
- **NAWS is declined** by `connection._handle_negotiation` (`IAC WONT NAWS`), so there is no real window size; the emulator is fixed 80×24 (params left for a future NAWS phase).
- **`_strip_iac` is reused by `readline()` and ~8 existing tests** — do not modify it; the streaming tap uses the new sibling `_strip_iac_stream`.
- **`_handle_bot_command` wrote feedback via `GameOutput.NewLine`** — there's no append API on a screen emulator, so feedback is fed into the emulator (`_echo`) and rendered. This is the one behavioural nuance of the swap.
- **`useWebSocket` return shape changes** from `state` to `{ state, rawSinkRef }` because xterm.js holds its own buffer and must receive `RawOutput` outside the panel reducer — `App.tsx` call site must be updated (Step 10).
