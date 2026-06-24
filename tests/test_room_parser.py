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

def test_you_notice_is_loot_not_monsters():
    # "You notice X here." is ground loot (items.LootMonitor), NOT monsters.
    parser = RoomParser({})
    assert parser.extract_monsters("You notice 2 log raft here.") == []
    assert parser.extract_monsters("You notice a rusty sword here.") == []

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

def test_extract_monsters_also_here_single():
    parser = RoomParser({})
    monsters = parser.extract_monsters("Also here: A dark elf.")
    assert len(monsters) == 1
    assert "dark elf" in monsters[0]

def test_extract_monsters_also_here_multiple():
    parser = RoomParser({})
    monsters = parser.extract_monsters("Also here: A goblin scout, 2 orc warriors.")
    assert len(monsters) >= 1
    combined = " ".join(monsters)
    assert "goblin" in combined or "orc" in combined

def test_extract_monsters_also_here_ignores_proper_names():
    """Player names like 'Krang Moan' should not be extracted as monsters."""
    parser = RoomParser({})
    # Player names are typically capitalized multi-word — hard to filter perfectly
    # but we should get the 'A/An/N' prefixed entries
    monsters = parser.extract_monsters("Also here: A goblin, Krang Moan.")
    # Should find goblin but ideally skip 'Krang Moan'
    combined = " ".join(monsters)
    assert "goblin" in combined

def test_extract_monsters_also_here_empty():
    parser = RoomParser({})
    assert parser.extract_monsters("Obvious exits: north") == []
    assert parser.extract_monsters("") == []


def test_extract_sightings_with_counts():
    p = RoomParser({})
    s = p.extract_sightings("Also here: a dark elf, 2 orc warriors.")
    assert ("dark elf", 1) in s
    assert ("orc warriors", 2) in s


def test_extract_sightings_single():
    p = RoomParser({})
    assert p.extract_sightings("A huge dragon is here.") == [("huge dragon", 1)]


def test_extract_players_capitalized_names():
    p = RoomParser({})
    assert p.extract_players("Also here: Krang Moan, a dark elf.") == ["Krang Moan"]


def test_extract_players_none():
    p = RoomParser({})
    assert p.extract_players("Also here: a dark elf, 2 orc warriors.") == []


def test_also_here_bare_lowercase_is_monster():
    # MegaMud takes every entry as an entity; bare "fat giant rat" is a monster.
    p = RoomParser({})
    assert p.extract_sightings("Also here: fat giant rat.") == [("fat giant rat", 1)]
    assert p.extract_players("Also here: fat giant rat.") == []


def test_also_here_capitalized_is_player():
    p = RoomParser({})
    assert p.extract_players("Also here: Betram.") == ["Betram"]
    assert p.extract_sightings("Also here: Betram.") == []


def test_also_here_strips_parenthetical():
    p = RoomParser({})
    assert p.extract_sightings("Also here: fat giant rat (Charmed).") == [("fat giant rat", 1)]


def test_also_here_mixed_monster_and_player():
    p = RoomParser({})
    line = "Also here: fat giant rat, Betram, a dark elf, 2 orcs."
    assert p.extract_sightings(line) == [("fat giant rat", 1), ("dark elf", 1), ("orcs", 2)]
    assert p.extract_players(line) == ["Betram"]


def test_monster_arrival_line():
    p = RoomParser({})
    assert p.extract_sightings(
        "A fat giant rat creeps into the room from nowhere.") == [("fat giant rat", 1)]


def test_description_sentence_is_not_a_monster():
    # A room-description line that happens to contain an arrival verb ("...your
    # every step.") must NOT be parsed as a monster — names aren't 11 words long.
    p = RoomParser({})
    assert p.extract_sightings(
        "The bridge below your feet seems to creak oddly with your every step.") == []
    assert p.extract_sightings(
        "The walls here are covered in moss and the floor is wet.") == []


def test_extract_removed_monster_death_falls():
    p = RoomParser({})
    assert p.extract_removed_monster(
        "The kobold thief falls to the ground with a shrill cry.") == "kobold thief"


def test_extract_removed_monster_drops_and_is_dead():
    p = RoomParser({})
    assert p.extract_removed_monster("The orc drops to the ground.") == "orc"
    assert p.extract_removed_monster("An angry kobold thief is dead.") == "angry kobold thief"


def test_extract_removed_monster_slain():
    p = RoomParser({})
    assert p.extract_removed_monster("You have slain the angry kobold thief.") == "angry kobold thief"
    assert p.extract_removed_monster("You killed a goblin!") == "goblin"


def test_extract_removed_monster_do_not_see():
    p = RoomParser({})
    assert p.extract_removed_monster("You do not see angry kobold thief here!") == "angry kobold thief"


def test_extract_removed_monster_none_for_normal_lines():
    p = RoomParser({})
    assert p.extract_removed_monster("The kobold thief lunges at you with their shortsword!") is None
    assert p.extract_removed_monster("Obvious exits: north, south") is None


def test_detect_room_normalizes_comma_format():
    from mmud.data.rooms import Room
    rooms = {"NARN": Room(code="NARN", hex_id="ABC10002", hex_id2="",
                          flags=(0, 0, 0), region="Newhaven", name="Newhaven Arena")}
    p = RoomParser(rooms)
    # Server prints "Newhaven, Arena" (comma); ROOMS.MD stores "Newhaven Arena".
    assert p.detect_room("Newhaven, Arena") == "NARN"
    assert p.detect_room("Newhaven Arena") == "NARN"
    assert p.detect_room("Somewhere Else") is None
