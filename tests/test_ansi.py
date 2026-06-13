from mmud.parser.ansi import render_line, visible_text


def test_plain_text_unchanged():
    assert visible_text("Obvious exits: North, East") == "Obvious exits: North, East"


def test_cursor_back_overwrites_hotkey():
    # MajorMud prints lowercase hotkey then over-writes with the highlighted word
    assert visible_text("n\x1b[1DNorth") == "North"
    assert visible_text("e\x1b[1DEast, w\x1b[1DWest") == "East, West"


def test_backspace_moves_cursor_then_overwrites():
    # Real terminals treat BS as cursor-left only (not destructive delete).
    assert visible_text("North\x08\x08X") == "NorXh"


def test_carriage_return_overwrites_from_column_0():
    # A shorter CR-redraw with no erase leaves trailing old chars — exactly the
    # duplicated-prompt artefact seen on screen. With \x1b[K it is clean.
    assert visible_text("[HP=10/100]\r[HP=9/100]") == "[HP=9/100]]"
    assert visible_text("[HP=10/100]\r[HP=9/100]\x1b[K") == "[HP=9/100]"


def test_cursor_forward_pads_spaces():
    assert visible_text("ab\x1b[3Ccd") == "ab   cd"


def test_erase_to_eol():
    assert visible_text("Hello world\x1b[6D\x1b[K") == "Hello"


def test_sgr_stripped_for_parsing():
    assert visible_text("\x1b[1;33mNorth\x1b[0m") == "North"


def test_color_preserved_for_display():
    out = render_line("\x1b[33mNorth\x1b[0m", color=True)
    assert "North" in out
    assert "\x1b[33m" in out          # colour kept
    # and an overwrite still resolves under colour
    assert "North" in render_line("n\x1b[1D\x1b[33mNorth\x1b[0m", color=True)
    assert "nN" not in render_line("n\x1b[1D\x1b[33mNorth\x1b[0m", color=True)
