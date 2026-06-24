from mmud.parser.exits_parser import title_hash, room_id


def test_room_id_bank_of_godfrey():
    # Verified byte-for-byte against ROOMS.MD (SBNK) via Ghidra RE:
    # room_id = ((title_hash & 0xFFF) << 20) | exit_bits
    assert room_id("Bank of Godfrey",
                   "Obvious exits: north, east, closed gate west") == "D4E00091"


def test_room_id_sovereign_street_uses_live_title():
    # ROOMS.MD label is "Sovereign St Nth" but the hash uses the LIVE title.
    assert room_id("Sovereign Street, Northern End",
                   "Obvious exits: north, south, east, west") == "89C00055"


def test_title_hash_is_position_weighted_byte_sum():
    # Σ (i+1)*ord(ch), 1-based index
    assert title_hash("AB") == 1 * ord("A") + 2 * ord("B")


def test_room_id_none_when_not_an_exits_line():
    assert room_id("Anywhere", "This is not an exits line") is None


def test_detect_room_from_block_resolves_unmatched_name(data_dir):
    # The live title "Sovereign Street, Northern End" does NOT match the ROOMS.MD
    # label "Sovereign St Nth" by name, but the hash resolves it to SOVN. The
    # block carries junk (prompt/gossip/move-echo) around the real title.
    from mmud.data.rooms import load_rooms
    from mmud.parser.room_parser import RoomParser
    rp = RoomParser(load_rooms(data_dir / "ROOMS.MD"))
    assert rp.detect_room("Sovereign Street, Northern End") is None  # name fails
    block = ["[HP=82/MA=30]:", "A voice shouts aloud \"Read the bulletin!\"", "n",
             "Sovereign Street, Northern End", "A wide cobbled street runs here."]
    assert rp.detect_room_from_block(
        block, "Obvious exits: north, south, east, west") == "SOVN"
