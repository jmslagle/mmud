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
