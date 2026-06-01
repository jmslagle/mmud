from mmud.data.messages import MessagePattern
from mmud.parser.matcher import PatternMatcher, MatchResult


def make_pattern(name, flags, apply_msg, remove_msg=""):
    return MessagePattern(name=name, flags=flags, third_field=0,
                          apply_message=apply_msg, remove_message=remove_msg)


def test_no_match():
    m = PatternMatcher([make_pattern("acid hits", 0, "Acid burns {target} for {dmg} damage!")])
    assert m.match("Nothing happened.") is None


def test_apply_match():
    m = PatternMatcher([make_pattern("acid hits", 0, "Acid burns {target} for {dmg} damage!")])
    result = m.match("Acid burns Goblin Warrior for 15 damage!")
    assert result is not None
    assert result.pattern.name == "acid hits"
    assert result.is_apply is True
    assert result.captures["target"] == "Goblin Warrior"
    assert result.captures["dmg"] == "15"


def test_remove_match():
    m = PatternMatcher([make_pattern("chain", 0x10, "You are caught in a chain!", "You get back on your feet.")])
    result = m.match("You get back on your feet.")
    assert result is not None
    assert result.is_apply is False
    assert result.pattern.name == "chain"


def test_literal_match_no_captures():
    m = PatternMatcher([make_pattern("chain", 0x10, "You are caught in a chain!")])
    result = m.match("You are caught in a chain!")
    assert result is not None
    assert result.captures == {}


def test_match_first_wins():
    p1 = make_pattern("a", 0, "You are hit!")
    p2 = make_pattern("b", 0, "You are hit!")
    m = PatternMatcher([p1, p2])
    result = m.match("You are hit!")
    assert result.pattern.name == "a"
