import pytest
from mmud.data.messages import MessagePattern, load_messages


def test_load_returns_list(data_dir):
    patterns = load_messages(data_dir / "MESSAGES.MD")
    assert len(patterns) > 100


def test_first_pattern_fields(data_dir):
    patterns = load_messages(data_dir / "MESSAGES.MD")
    # Find "acid hits" entry
    acid = next(p for p in patterns if p.name == "acid hits")
    assert acid.flags == 0x0000
    assert "Acid burns" in acid.apply_message
    assert "{target}" in acid.apply_message
    assert "{dmg}" in acid.apply_message


def test_pattern_with_remove_message(data_dir):
    patterns = load_messages(data_dir / "MESSAGES.MD")
    chain = next(p for p in patterns if p.name == "chain")
    assert chain.apply_message == "You are caught in a chain!"
    assert chain.remove_message == "You get back on your feet."


def test_pattern_without_remove_message(data_dir):
    patterns = load_messages(data_dir / "MESSAGES.MD")
    acid = next(p for p in patterns if p.name == "acid hits")
    assert acid.remove_message == ""
