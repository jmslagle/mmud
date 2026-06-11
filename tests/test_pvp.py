from mmud.combat.pvp import PvpEngine
from mmud.automation.safety import SafetyMonitor
from mmud.config.schema import PvpConfig, PlayerRule, SafetyConfig
from mmud.state.game_state import GameState


def _engine(action="", spell="", friends=()):
    rules = [PlayerRule(name=f, friend=True) for f in friends]
    return PvpEngine(PvpConfig(action=action, spell=spell, flee_rooms=2),
                     rules, SafetyMonitor(SafetyConfig()))


def _state_with(*players):
    gs = GameState()
    gs.players_present = list(players)
    return gs


def test_no_action_configured_ignores():
    eng = _engine()
    assert eng.check(_state_with("Krang")) is None


def test_friend_is_exempt():
    eng = _engine(action="flee", friends=("Krang",))
    assert eng.check(_state_with("Krang")) is None


def test_flee_action():
    eng = _engine(action="flee")
    gs = _state_with("Krang")
    assert eng.check(gs) == "flee"
    assert gs.dequeue() == "flee"      # flee_rooms=2 -> 1 returned + 1 queued


def test_attack_action_with_spell():
    eng = _engine(action="attack", spell="cast zap")
    assert eng.check(_state_with("Krang")) == "cast zap Krang"


def test_hangup_action():
    eng = _engine(action="hangup")
    assert eng.check(_state_with("Krang")) is None
    assert eng._safety.hangup_requested


def test_custom_command_action():
    eng = _engine(action="say please leave")
    assert eng.check(_state_with("Krang")) == "say please leave"


def test_reacts_once_per_player():
    eng = _engine(action="flee")
    gs = _state_with("Krang")
    assert eng.check(gs) == "flee"
    assert eng.check(gs) is None       # same player, no spam
