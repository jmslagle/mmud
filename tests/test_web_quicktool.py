from __future__ import annotations
from mmud.web.server import quicktool_command


def test_compass_directions():
    for d in ("n","ne","e","se","s","sw","w","nw","u","d"):
        assert quicktool_command(d) == d


def test_action_buttons():
    assert quicktool_command("get-all") == "get all"
    assert quicktool_command("drop-all") == "drop all"
    assert quicktool_command("equip-all") == "wear all"
    assert quicktool_command("deposit") == "deposit all"
    assert quicktool_command("search") == "search"
    assert quicktool_command("afk") == "afk"


def test_unknown_action_returns_none():
    assert quicktool_command("frobnicate") is None
