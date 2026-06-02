# tests/test_conversation_parser.py
from mmud.parser.conversation_parser import ConversationParser

def test_bracket_tell():
    p = ConversationParser()
    r = p.parse("[BumbleBee tells you] hey there!")
    assert r is not None
    assert r.channel == "tell"
    assert r.sender == "BumbleBee"
    assert r.text == "hey there!"

def test_bracket_shout():
    p = ConversationParser()
    r = p.parse("[Shout] DarkStar: LFG dungeon!")
    assert r is not None
    assert r.channel == "shout"
    assert r.sender == "DarkStar"
    assert r.text == "LFG dungeon!"

def test_bracket_party():
    p = ConversationParser()
    r = p.parse("[Party] Krang: I need heal")
    assert r is not None
    assert r.channel == "party"
    assert r.sender == "Krang"

def test_bracket_gossip():
    p = ConversationParser()
    r = p.parse("[Gossip] Navar: anyone farming RHU?")
    assert r is not None
    assert r.channel == "gossip"
    assert r.sender == "Navar"

def test_old_tell_format():
    p = ConversationParser()
    r = p.parse("BumbleBee tells you, 'hello friend'")
    assert r is not None
    assert r.channel == "tell"
    assert r.sender == "BumbleBee"
    assert "hello" in r.text

def test_non_conversation_returns_none():
    p = ConversationParser()
    assert p.parse("Obvious exits: north, east") is None
    assert p.parse("You notice 3 orcs here.") is None
    assert p.parse("[HP=141/216]:e") is None
    assert p.parse("") is None

def test_own_echo_skipped():
    p = ConversationParser()
    assert p.parse("You say, 'attack orc'") is None
    assert p.parse("You shout, 'help!'") is None
