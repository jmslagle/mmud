"""Test binary data probing for MONSTERS.MD and ITEMS.MD."""
from mmud.data.binary import extract_strings, probe_binary


def test_monster_strings(data_dir):
    """Extract strings from MONSTERS.MD and verify monster names are found."""
    strings = extract_strings(data_dir / "MONSTERS.MD", min_length=4)
    # Should find monster names
    all_text = " ".join(strings)
    assert "rat" in all_text.lower() or "orc" in all_text.lower()


def test_item_strings(data_dir):
    """Extract strings from ITEMS.MD and verify item names are found."""
    strings = extract_strings(data_dir / "ITEMS.MD", min_length=4)
    all_text = " ".join(strings)
    assert any(word in all_text.lower() for word in ["staff", "scroll", "sword", "shield"])


def test_probe_reports_structure(data_dir):
    """Probe MONSTERS.MD and verify structure report contains required fields."""
    report = probe_binary(data_dir / "MONSTERS.MD")
    assert "total_bytes" in report
    assert report["total_bytes"] > 0
    assert "string_count" in report


# ── New struct-based parser tests ─────────────────────────────────────────────

from mmud.data.binary import (
    load_monsters, load_items, load_spells, load_players,
    Monster, Item, Spell, Player,
)


def test_load_monsters_returns_records(data_dir):
    monsters = load_monsters(data_dir / "MONSTERS.MD")
    assert isinstance(monsters, list)
    assert len(monsters) > 0, "Expected at least some monsters"
    assert all(isinstance(m, Monster) for m in monsters)
    named = [m for m in monsters if m.name.strip()]
    assert len(named) > 0


def test_load_monsters_has_known_names(data_dir):
    monsters = load_monsters(data_dir / "MONSTERS.MD")
    names = {m.name.lower() for m in monsters}
    all_text = " ".join(names)
    assert "rat" in all_text or "orc" in all_text or "spider" in all_text, (
        f"Expected common monster names in: {list(names)[:10]}"
    )


def test_load_monsters_active_flag(data_dir):
    monsters = load_monsters(data_dir / "MONSTERS.MD")
    # All returned monsters should have active flag set
    for m in monsters:
        assert m.flags & 0x40000000, f"Monster {m.name!r} missing active flag: {m.flags:#010x}"
        assert not (m.flags & 0x80000000), f"Monster {m.name!r} has deleted flag set"


def test_load_items_returns_records(data_dir):
    items = load_items(data_dir / "ITEMS.MD")
    assert isinstance(items, list)
    assert len(items) > 0, "Expected at least some items"
    assert all(isinstance(i, Item) for i in items)
    named = [i for i in items if i.name.strip()]
    assert len(named) > 0


def test_load_items_has_known_names(data_dir):
    items = load_items(data_dir / "ITEMS.MD")
    all_text = " ".join(i.name.lower() for i in items)
    assert any(word in all_text for word in ["staff", "sword", "shield", "scroll", "armor", "dagger"]), (
        f"Expected common item names, got sample: {[i.name for i in items[:5]]}"
    )


def test_load_spells_returns_records(data_dir):
    spells = load_spells(data_dir / "SPELLS.MD")
    assert isinstance(spells, list)
    assert len(spells) > 0, "Expected at least some spells"
    assert all(isinstance(s, Spell) for s in spells)
    named = [s for s in spells if s.full_name.strip()]
    assert len(named) > 0


def test_load_spells_has_known_names(data_dir):
    spells = load_spells(data_dir / "SPELLS.MD")
    all_text = " ".join(s.full_name.lower() for s in spells)
    assert any(word in all_text for word in ["magic", "heal", "fire", "bless", "curse", "missile"]), (
        f"Expected common spell names, got sample: {[s.full_name for s in spells[:5]]}"
    )


def test_load_players_does_not_crash(data_dir):
    # PLAYERS.MD may not exist or may be empty (no saved players in this extraction)
    players_path = data_dir / "PLAYERS.MD"
    players = load_players(players_path)
    assert isinstance(players, list)


def test_monster_record_size_aligns(data_dir):
    import pathlib
    data = (data_dir / "MONSTERS.MD").read_bytes()
    # File should be (1 + N) * 1024 bytes where N is the page count from the header
    total_pages = len(data) // 1024
    remainder = len(data) % 1024
    print(f"MONSTERS.MD: {len(data)} bytes, {total_pages} pages of 1024, remainder={remainder}")
    assert remainder == 0, f"File size not a multiple of 1024: {len(data)}"


def test_item_record_size_aligns(data_dir):
    data = (data_dir / "ITEMS.MD").read_bytes()
    total_pages = len(data) // 1024
    remainder = len(data) % 1024
    print(f"ITEMS.MD: {len(data)} bytes, {total_pages} pages of 1024, remainder={remainder}")
    assert remainder == 0, f"File size not a multiple of 1024: {len(data)}"


def test_monster_count_reasonable(data_dir):
    monsters = load_monsters(data_dir / "MONSTERS.MD")
    print(f"MONSTERS.MD: loaded {len(monsters)} active monsters")
    # The extraction has ~700 monster entries (2 per page in 350+ data pages)
    assert len(monsters) > 100, f"Expected >100 monsters, got {len(monsters)}"


def test_item_count_reasonable(data_dir):
    items = load_items(data_dir / "ITEMS.MD")
    print(f"ITEMS.MD: loaded {len(items)} active items")
    assert len(items) > 100, f"Expected >100 items, got {len(items)}"


def test_spell_count_reasonable(data_dir):
    spells = load_spells(data_dir / "SPELLS.MD")
    print(f"SPELLS.MD: loaded {len(spells)} active spells")
    assert len(spells) > 50, f"Expected >50 spells, got {len(spells)}"
