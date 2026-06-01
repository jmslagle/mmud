# tests/test_room_parser.py
from mmud.data.rooms import Room
from mmud.parser.room_parser import RoomParser

def _rooms(*entries):
    return {
        code: Room(code=code, hex_id="", hex_id2="", flags=(0,0,0), region="", name=name)
        for code, name in entries
    }

def test_detect_exact_room_name():
    parser = RoomParser(_rooms(("HOME", "The Homely Hearth")))
    assert parser.detect_room("The Homely Hearth") == "HOME"

def test_detect_room_name_case_insensitive():
    parser = RoomParser(_rooms(("HOME", "The Homely Hearth")))
    assert parser.detect_room("the homely hearth") == "HOME"

def test_detect_room_name_strips_whitespace():
    parser = RoomParser(_rooms(("DSTR", "Dagger Street, Eastern End")))
    assert parser.detect_room("  Dagger Street, Eastern End  ") == "DSTR"

def test_unknown_line_returns_none():
    parser = RoomParser(_rooms(("HOME", "The Homely Hearth")))
    assert parser.detect_room("You notice 37 silver nobles here.") is None
    assert parser.detect_room("Obvious exits: north, east") is None
    assert parser.detect_room("") is None

def test_extract_monsters_you_notice():
    parser = RoomParser({})
    monsters = parser.extract_monsters("You notice 2 orc warriors and 1 goblin scout here.")
    assert len(monsters) >= 1
    combined = " ".join(monsters)
    assert "orc" in combined or "goblin" in combined

def test_extract_monsters_is_here():
    parser = RoomParser({})
    monsters = parser.extract_monsters("A huge dragon is here.")
    assert len(monsters) == 1
    assert "huge dragon" in monsters[0]

def test_extract_monsters_empty_line():
    parser = RoomParser({})
    assert parser.extract_monsters("You notice 37 silver nobles here.") == []
    assert parser.extract_monsters("Obvious exits: north") == []
    assert parser.extract_monsters("Sneaking...") == []
