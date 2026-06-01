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
