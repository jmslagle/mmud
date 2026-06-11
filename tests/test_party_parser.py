from mmud.parser.party_parser import PartyParser, PartyMember
from mmud.state.game_state import GameState


def _feed(lines):
    gs = GameState()
    p = PartyParser()
    for line in lines:
        p.feed(line, gs)
    return gs


def test_party_list_parsed():
    gs = _feed([
        "The following people are in your party:",
        "Krang          [Warrior]   [ 75] [100]",
        "Beeze Moan     [Cleric]    [100] [ 40] P",
        "Obvious exits: north",          # non-row ends the list
    ])
    assert [m.name for m in gs.party] == ["Krang", "Beeze"]
    assert gs.party[0].hp_pct == 75
    assert gs.party[0].mp_pct == 100
    assert gs.party[0].klass == "Warrior"
    assert gs.party[1].hp_pct == 100
    assert gs.party[1].is_leader is True    # trailing P flag


def test_not_in_a_party_clears():
    gs = _feed([
        "The following people are in your party:",
        "Krang          [Warrior]   [ 75] [100]",
        "You are not in a party.",
    ])
    assert gs.party == []
    assert gs.party_leader == ""


def test_following_sets_leader():
    gs = _feed(["You are following Krang."])
    assert gs.party_leader == "Krang"


def test_rows_outside_list_ignored():
    gs = _feed(["Krang          [Warrior]   [ 75] [100]"])
    assert gs.party == []                   # no header seen: not a party row


def test_list_replaces_previous():
    gs = _feed([
        "The following people are in your party:",
        "Krang          [Warrior]   [ 75] [100]",
        "[HP=100/100]:",
        "The following people are in your party:",
        "Beeze          [Cleric]    [ 50] [ 50]",
        "[HP=100/100]:",
    ])
    assert [m.name for m in gs.party] == ["Beeze"]
