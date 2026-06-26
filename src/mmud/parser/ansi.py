"""In-line ANSI terminal rendering for MajorMud output.

MajorMud is a full-screen BBS door: it highlights exit hotkeys and redraws
prompts by moving the cursor backward and over-printing (e.g. it prints a
lowercase hotkey ``n`` then over-writes it with a highlighted ``North``). An
append-only log that merely *strips* escape codes shows artefacts like
``nNorth``. `render_line` replays the cursor moves on a single line so the
final visible text is correct, optionally preserving SGR colour codes.
"""
from __future__ import annotations
import re

_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")
_CSI_RE = re.compile(r"\x1b\[([0-9;?]*)([@-~])")


def render_line(raw: str, *, color: bool = False) -> str:
    """Replay in-line cursor controls on `raw`, returning the visible text.

    Handles backspace (0x08), carriage return, and the CSI cursor moves
    MajorMud uses: cursor back/forward (``D``/``C``), absolute column
    (``G``/`` ` ``) and erase-to-end-of-line (``K``). SGR colour runs are kept
    when ``color`` is true (for display) and dropped otherwise (for parsing).
    Plain text with no control codes is returned unchanged.
    """
    cells: list[tuple[str, str]] = []   # (char, active SGR code when written)
    cursor = 0
    style = ""
    i, n = 0, len(raw)
    while i < n:
        ch = raw[i]
        if ch == "\x1b" and i + 1 < n and raw[i + 1] == "[":
            m = _CSI_RE.match(raw, i)
            if not m:
                i += 1
                continue
            params, final = m.group(1), m.group(2)
            i = m.end()
            if final == "m":
                style = m.group(0) if color else ""
            elif final == "D":                       # cursor back
                cursor = max(0, cursor - (int(params) if params else 1))
            elif final == "C":                       # cursor forward
                cursor += int(params) if params else 1
            elif final in ("G", "`"):                # cursor to column (1-based)
                cursor = max(0, (int(params) if params else 1) - 1)
            elif final == "K":                       # erase to end of line
                del cells[cursor:]
            # other CSI codes (cursor up/down, etc.) are ignored on one line
            continue
        if ch == "\x08":                             # backspace
            cursor = max(0, cursor - 1)
            i += 1
            continue
        if ch == "\r":
            cursor = 0
            i += 1
            continue
        if ch == "\n":
            i += 1
            continue
        # printable: overwrite at cursor, padding with spaces if past the end
        while len(cells) < cursor:
            cells.append((" ", ""))
        if cursor < len(cells):
            cells[cursor] = (ch, style)
        else:
            cells.append((ch, style))
        cursor += 1
        i += 1

    if not color:
        return "".join(c for c, _ in cells)
    out: list[str] = []
    cur = ""                        # default style; no leading code emitted
    for c, st in cells:
        if st != cur:
            out.append(st if st else "\x1b[0m")
            cur = st
        out.append(c)
    return "".join(out)


def visible_text(raw: str) -> str:
    """The final on-screen text of a line — cursor moves applied, colour gone."""
    return render_line(raw, color=False)


def line_fg(raw: str) -> str:
    """Foreground-colour key (e.g. '1;36' = bold cyan, '33' = yellow) in effect at the
    line's first visible character, or '' if the text carries no SGR colour. Used to
    identify room titles by colour — MegaMud's `room_title_parse` keys on the title's
    display attribute (`state+0x7deb`)."""
    fg = ""
    bold = False
    i, n = 0, len(raw)
    while i < n:
        ch = raw[i]
        if ch == "\x1b" and i + 1 < n and raw[i + 1] == "[":
            m = _CSI_RE.match(raw, i)
            if not m:
                i += 1
                continue
            i = m.end()
            if m.group(2) == "m":
                params = m.group(1)
                for p in (params.split(";") if params else ["0"]):
                    code = int(p) if p.isdigit() else 0
                    if code == 0:
                        fg, bold = "", False
                    elif code == 1:
                        bold = True
                    elif code == 22:
                        bold = False
                    elif code == 39:
                        fg = ""
                    elif 30 <= code <= 37 or 90 <= code <= 97:
                        fg = str(code)
            continue
        if ch in ("\x08", "\r", "\n", " "):
            i += 1
            continue
        if fg and bold:
            return f"1;{fg}"
        return fg or ("1" if bold else "")
    return ""
