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


def test_resize_changes_line_count_keeps_columns():
    # The grid follows the TUI pane height (declining NAWS, the server still
    # formats for 80 columns, so only `lines` varies). A taller grid means the
    # server's top-aligned full-screen editor never scrolls off the top.
    term = TerminalEmulator()
    term.resize(40)
    rows = term.display()
    assert len(rows) == 40
    assert all(len(r) == 80 for r in rows)
    assert term.lines == 40 and term.columns == 80


def test_resize_grid_is_usable_to_the_new_bottom_row():
    term = TerminalEmulator()
    term.resize(40)
    term.feed("\x1b[40;1Hbottom")     # write to the new last row (1-based)
    assert term.display()[39].startswith("bottom")


def test_prev_page_scrolls_into_history():
    term = TerminalEmulator()
    for i in range(60):
        term.feed(f"line{i}\r\n")
    before = term.display()
    term.prev_page()
    assert term.display() != before    # scrolled back into scrollback history
