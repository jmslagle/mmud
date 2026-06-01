from mmud.data.rooms import Room, load_rooms


def test_load_returns_dict(data_dir):
    rooms = load_rooms(data_dir / "ROOMS.MD")
    assert len(rooms) > 50


def test_full_format_room(data_dir):
    rooms = load_rooms(data_dir / "ROOMS.MD")
    # Key by 4-letter code
    assert "AALY" in rooms
    room = rooms["AALY"]
    assert room.hex_id == "CAB00180"
    assert room.region == "Ancient Ruin"
    assert room.name == "Ancient Ruin Dark Alley"


def test_partial_format_room(data_dir):
    rooms = load_rooms(data_dir / "ROOMS.MD")
    assert "MOAT" in rooms
    moat = rooms["MOAT"]
    assert moat.region == "Dark-Elf City"
    assert moat.name == "Dark-elf Castle Moat"
