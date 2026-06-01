from mmud.state.game_state import GameState
from mmud.combat.combat import CombatEngine


def test_attacks_when_in_combat():
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    ce = CombatEngine()
    cmd = ce.decide(gs)
    assert cmd == "attack"


def test_flees_when_critically_low_hp():
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(10, 100)   # 10% HP
    ce = CombatEngine(flee_threshold=0.15)
    cmd = ce.decide(gs)
    assert cmd == "flee"


def test_no_command_when_not_in_combat_and_healthy():
    gs = GameState()
    gs.set_combat(False)
    gs.set_hp(100, 100)
    ce = CombatEngine()
    cmd = ce.decide(gs)
    assert cmd is None


def test_rests_when_not_in_combat_and_low_hp():
    gs = GameState()
    gs.set_combat(False)
    gs.set_hp(30, 100)
    ce = CombatEngine(rest_threshold=0.5)
    cmd = ce.decide(gs)
    assert cmd == "rest"
