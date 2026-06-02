import time
from mmud.automation.spells import SpellEngine
from mmud.config.schema import SpellsConfig, BlessSpell
from mmud.state.game_state import GameState


def test_bless_cast_when_mana_sufficient():
    cfg = SpellsConfig(bless=[BlessSpell(cmd="bless", mana_pct=0.80)])
    gs = GameState()
    gs.set_mana(90, 100)   # 90% mana
    engine = SpellEngine(cfg)
    cmd = engine.decide(gs)
    assert cmd == "bless"


def test_bless_skipped_when_mana_low():
    cfg = SpellsConfig(bless=[BlessSpell(cmd="bless", mana_pct=0.80)])
    gs = GameState()
    gs.set_mana(70, 100)   # 70% mana < 80% threshold
    engine = SpellEngine(cfg)
    assert engine.decide(gs) is None


def test_bless_cooldown_respected():
    cfg = SpellsConfig(bless=[BlessSpell(cmd="bless", mana_pct=0.50)])
    gs = GameState()
    gs.set_mana(90, 100)
    engine = SpellEngine(cfg)
    engine.decide(gs)       # cast once — sets cooldown
    engine.tick()           # advance 1 tick (<<600)
    assert engine.decide(gs) is None  # still on cooldown


def test_bless_cooldown_expires():
    cfg = SpellsConfig(bless=[BlessSpell(cmd="bless", mana_pct=0.50)])
    gs = GameState()
    gs.set_mana(90, 100)
    engine = SpellEngine(cfg)
    engine.decide(gs)            # cast
    for _ in range(600):         # advance 600 ticks
        engine.tick()
    cmd = engine.decide(gs)      # should cast again
    assert cmd == "bless"


def test_heal_spell_cast_below_threshold():
    cfg = SpellsConfig(heal="cure light wounds", heal_hp_pct=0.50)
    gs = GameState()
    gs.set_hp(40, 100)     # 40% < 50% threshold
    gs.set_mana(80, 100)
    gs.set_combat(False)
    engine = SpellEngine(cfg)
    cmd = engine.decide(gs)
    assert cmd == "cure light wounds"


def test_no_heal_when_hp_sufficient():
    cfg = SpellsConfig(heal="cure light wounds", heal_hp_pct=0.50)
    gs = GameState()
    gs.set_hp(70, 100)     # 70% > 50% threshold
    gs.set_mana(80, 100)
    engine = SpellEngine(cfg)
    assert engine.decide(gs) is None


def test_attack_spell_in_combat():
    cfg = SpellsConfig(attack="magic missile")
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(80, 100)
    gs.monsters_present = ["orc"]
    engine = SpellEngine(cfg)
    cmd = engine.decide(gs)
    assert cmd == "magic missile"


def test_mana_heal_when_mana_low():
    cfg = SpellsConfig(mana_heal="meditate", mana_heal_pct=0.30)
    gs = GameState()
    gs.set_mana(20, 100)  # 20% < 30%
    engine = SpellEngine(cfg)
    assert engine.decide(gs) == "meditate"


def test_mana_heal_skipped_in_combat():
    cfg = SpellsConfig(mana_heal="meditate", mana_heal_pct=0.30)
    gs = GameState()
    gs.set_mana(20, 100)
    gs.set_combat(True)
    engine = SpellEngine(cfg)
    assert engine.decide(gs) != "meditate"


def test_pre_attack_when_monster_seen():
    cfg = SpellsConfig(pre_attack="true strike")
    gs = GameState()
    gs.set_combat(False)
    gs.set_hp(80, 100)
    gs.set_mana(80, 100)
    gs.monsters_present = ["orc"]
    engine = SpellEngine(cfg)
    assert engine.decide(gs) == "true strike"


def test_pre_attack_skipped_when_no_monsters():
    cfg = SpellsConfig(pre_attack="true strike")
    gs = GameState()
    gs.monsters_present = []
    engine = SpellEngine(cfg)
    assert engine.decide(gs) is None
