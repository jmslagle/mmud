# Terminal — ANSI emulation, NAWS, the screen-size probe

MajorMUD is a full-screen ANSI BBS door: the in-game editor, menus and "scroll"
displays position the cursor to arbitrary row/col and redraw in place. Our TUI feeds
raw bytes (IAC-stripped, pre-line-framing) into a `pyte HistoryScreen`
(`src/mmud/terminal.py` `TerminalEmulator`), rendered by `TerminalView` (a Static).
**DISPLAY only** — SEMANTICS still flow through the line parser independently.

## MegaMud's ANSI/VT100 set (`ansi_escape_parse @0x45d830`)

Byte-by-byte state machine. Sequences handled:

| Seq | Action |
|-----|--------|
| `ESC[A/B/C/D` | cursor up/down/right/left (rel) |
| `ESC[H` / `ESC[f` | cursor position absolute (clamps row ≤ `0x3c`=60, col ≤ `0x84`=132) |
| `ESC[2J` | erase display (`ansi_clear_screen`) |
| `ESC[K` | erase to end of line |
| `ESC[m` | SGR colour/attribute (up to 4 params) |
| `ESC[6n` | **device status report** → cursor-position reply (see below) |
| `ESC[r` | set scrolling region |
| `ESC[s` / `ESC[u` | save / restore cursor |
| `ESC D` / `ESC M` | scroll up/down one line |

## The grid is sized to the pane (not fixed 80×24)

A Static defaults to auto-height, so the box sat 24 rows tall in a taller pane.
`TerminalView` uses `DEFAULT_CSS height: 1fr`, and `on_resize`/`attach_emulator` call
`_fit_emulator` → `TerminalEmulator.resize(lines)` to the pane's content height
(columns stay 80; min 24). Mouse wheel + PageUp/PageDown scroll pyte history.

The char-mode focus highlight must be an **always-present border, recoloured on focus**
— not an `outline` (it draws over the content edge → clipped column 0, e.g.
"Crypt"→"rypt") and not a focus-only border (it would resize the grid mid-edit).

## How the server learns our screen size

There are two mechanisms. **This server uses telnet NAWS, not `ESC[6n`** — but we
implement both.

### Telnet NAWS (what "Realm of Legends" actually uses)
The live server never sends `ESC[6n` (zero DSR probes in the log even with the editor
open). It negotiates screen size via **NAWS**. The connection used to **decline** it
(`DO NAWS → WONT`), so the server assumed a default size mismatched to our pane-sized
grid: the editor form was drawn by scrolling (landed at the BOTTOM of the tall grid)
while absolute-positioned field values (stat numbers) landed at the TOP → "way wonky"
duplicated fragments.

**Fix:** accept NAWS and report our real size. `connection.py`:
`DO NAWS → WILL NAWS` + `_write_naws()` sends `IAC SB NAWS w_hi w_lo h_hi h_lo IAC SE`
(0xFF bytes inside the subneg are doubled), re-sent on resize. Wired:
`MudBot.set_terminal_size(cols, rows)` resizes the emulator + `conn.set_size`;
`_run_session` pushes the size at connect; `TerminalView._fit_emulator` routes the
resize through the bot. The server now formats the editor for our actual screen → aligned.

### `ESC[6n` Device Status Report (the binary mechanism; kept for servers that probe)
MegaMud detects size the classic way: home the cursor to a huge position
(`ESC[99;99H`, clamped to the grid corner) then send `ESC[6n`; the client must reply
`ESC[row;colR` (1-based cursor). Ghidra: `ansi_escape_parse` case `0x6e` with param 6
calls `ansi_cursor_pos_report @0x40eb10`, which `wsprintfA`s `ESC[%d;%dR`
(fmt `@0x4b685c`; row = `state+0x3c`, col = `+0x38`, both +1) and sends it back via
`net_buffer_receive`.

We strip telnet IAC but fed everything else to pyte, which never answers DSR. **Fix:**
`MudBot._dsr_reply(data)` returns `f"\x1b[{y+1};{x+1}R"` from the emulator's clamped
cursor when `\x1b[6n` is in the chunk; `_feed_raw` schedules `conn.send_raw(reply)`.
Harmless on servers (like this one) that never probe.
