from mmud.parser.exits_parser import parse_exits


def test_basic_exits():
    assert parse_exits("Obvious exits: north, east") == ["n", "e"]


def test_diagonals_and_vertical():
    assert parse_exits("Obvious exits: northeast, southwest, up, down") == \
        ["ne", "sw", "u", "d"]


def test_none():
    assert parse_exits("Obvious exits: none") == []


def test_non_exit_line_returns_none():
    assert parse_exits("You notice a rusty sword here.") is None
    assert parse_exits("") is None


def test_case_and_trailing_period():
    assert parse_exits("obvious exits: West, South.") == ["w", "s"]


from mmud.parser.exits_parser import exit_signature


def test_door_prefixed_exits_yield_direction():
    # Regression: "open door north" must still yield the 'n' exit (was dropped).
    assert parse_exits("Obvious exits: open door north, up") == ["n", "u"]
    assert parse_exits("Obvious exits: closed gate south, east") == ["s", "e"]


def test_exit_signature_matches_megamud_encoding():
    # Newhaven Arena (ROOMS.MD NARN id 0xABC10002): lower 20 bits = 0x10002.
    # "open door north" -> N=closed-door(2) after 3->2 normalization; up -> 1.
    assert exit_signature("Obvious exits: open door north, up") == 0x10002
    # closed door normalizes the same way (door state is door, open-or-shut).
    assert exit_signature("Obvious exits: closed door north, up") == 0x10002


def test_exit_signature_plain_dirs():
    # north=open(1) bit0-1, east=open(1) bit4-5 -> 1 | (1<<4) = 0x11
    assert exit_signature("Obvious exits: north, east") == 0x11
    assert exit_signature("Obvious exits: none") == 0
    assert exit_signature("Not an exits line") is None
