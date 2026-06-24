from mmud.parser.who_parser import WhoParser

def test_parse_who_entry_full():
    parser = WhoParser()
    result = parser.parse_line("Spawn DaPrawn        L21  Criminal  The Lords of T.")
    assert result is not None
    assert result.name == "Spawn DaPrawn"
    assert "21" in result.level
    assert result.rep == "Criminal"

def test_parse_who_entry_no_gang():
    parser = WhoParser()
    result = parser.parse_line("BumbleBee            L5-9 Neutral")
    assert result is not None
    assert result.name == "BumbleBee"
    assert "5" in result.level

def test_parse_non_who_line():
    parser = WhoParser()
    assert parser.parse_line("Obvious exits: north") is None
    assert parser.parse_line("") is None
    assert parser.parse_line("Online Players") is None

def test_xp_line_detection():
    parser = WhoParser()
    exp = parser.parse_exp_line("Exp: 52497")
    assert exp == 52497

def test_level_line_detection():
    parser = WhoParser()
    level = parser.parse_level_line("Level: 21")
    assert level == 21

def test_combined_exp_command_line():
    # The in-game `exp` command prints exp, level, and needed on ONE line; all
    # three must be extractable (absolute exp not swallowed by "Exp needed").
    parser = WhoParser()
    line = "Exp: 11801 Level: 4 Exp needed for next level: 6349 (18150) [65%]"
    assert parser.parse_exp_line(line) == 11801
    assert parser.parse_level_line(line) == 4
    assert parser.parse_exp_needed_line(line) == 6349
    assert parser.parse_exp_line("Exp needed for next level: 6349") is None
