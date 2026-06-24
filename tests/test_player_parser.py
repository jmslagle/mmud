from mmud.parser.player_parser import (
    PlayerExamineParser, parse_arrival, parse_departure, parse_looking_at)
from mmud.automation.players import PlayerLookDecider
from mmud.config.schema import PvpConfig, PlayerRule
from mmud.state.game_state import GameState


def test_examine_parser_extracts_race_class():
    p = PlayerExamineParser()
    assert p.feed("[ Horis ]") is None
    rec = p.feed("Horis is a solid, well built Dark-Elf Gypsy with no hair and black eyes.  He")
    assert rec == {"name": "Horis", "race": "Dark-Elf", "class": "Gypsy"}


def test_presence_transitions():
    assert parse_arrival("You notice Horis sneak in from the north.") == "Horis"
    assert parse_arrival("Krang walks in from the south.") == "Krang"
    assert parse_departure("You notice Horis sneaking out to the north.") == "Horis"
    assert parse_looking_at("Horis is looking at you.") == "Horis"
    assert parse_arrival("The kobold thief lunges at you!") is None


def _state_with_player(name="Horis"):
    gs = GameState()
    gs.players_present = [name]
    return gs


def test_look_decider_sends_l_for_unknown_nonfriend():
    d = PlayerLookDecider(PvpConfig(look_players=True), [], now=lambda: 0.0)
    gs = _state_with_player()
    assert d.decide(gs) == "l Horis"
    # Begins a LOOKING task; won't re-look the same player.
    from mmud.state.tasks import TaskType
    assert gs.task.type is TaskType.LOOKING
    gs.complete_task()
    assert d.decide(gs) is None


def test_look_decider_skips_friend_and_when_disabled():
    friend = PlayerLookDecider(PvpConfig(look_players=True),
                               [PlayerRule(name="Horis", friend=True)], now=lambda: 0.0)
    assert friend.decide(_state_with_player()) is None
    off = PlayerLookDecider(PvpConfig(look_players=False), [], now=lambda: 0.0)
    assert off.decide(_state_with_player()) is None


def test_look_decider_skips_during_combat():
    d = PlayerLookDecider(PvpConfig(look_players=True), [], now=lambda: 0.0)
    gs = _state_with_player()
    gs.set_combat(True)
    assert d.decide(gs) is None
