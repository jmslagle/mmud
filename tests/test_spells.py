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


from mmud.state.game_state import MonsterSighting


def _combat_state():
    gs = GameState()
    gs.set_hp(100, 100); gs.set_mana(100, 100); gs.set_combat(True)
    gs.monsters_present.append(MonsterSighting(name="orc"))
    return gs


def test_cast_count_limit_then_weapon_swap():
    cfg = SpellsConfig(attack="cast zap", max_cast_count=2,
                       melee_weapon_cmd="arm warhammer")
    eng = SpellEngine(cfg)
    gs = _combat_state()
    assert eng.decide(gs) == "cast zap"
    assert eng.decide(gs) == "cast zap"
    assert eng.decide(gs) == "arm warhammer"
    assert eng.decide(gs) is None          # melee decider's turn now


def test_counter_resets_and_swaps_back_after_combat():
    cfg = SpellsConfig(attack="cast zap", max_cast_count=1,
                       cast_weapon_cmd="arm staff", melee_weapon_cmd="arm warhammer")
    eng = SpellEngine(cfg)
    gs = _combat_state()
    assert eng.decide(gs) == "cast zap"
    assert eng.decide(gs) == "arm warhammer"
    gs.set_combat(False); gs.monsters_present.clear()
    assert eng.decide(gs) == "arm staff"   # swap back once, out of combat
    assert eng.decide(gs) is None


def test_unlimited_when_zero():
    cfg = SpellsConfig(attack="cast zap", max_cast_count=0)
    eng = SpellEngine(cfg)
    gs = _combat_state()
    for _ in range(10):
        assert eng.decide(gs) == "cast zap"


def test_multi_attack_chains_after_primary_attack():
    cfg = SpellsConfig(attack="cast zap", multi_attack="cast bolt")
    eng = SpellEngine(cfg)
    gs = _combat_state()
    assert eng.decide(gs) == "cast zap"
    assert eng.decide(gs) == "cast bolt"
    assert eng.decide(gs) == "cast zap"
    assert eng.decide(gs) == "cast bolt"


def test_multi_attack_respects_max_cast_count():
    # primary/multi alternation must honor the cast limit: 3 casts total
    # (fireball, mm, fireball), then the limit is hit. No melee_weapon_cmd
    # configured, so the 4th decide returns None (engine yields, no swap).
    cfg = SpellsConfig(attack="cast fireball", multi_attack="cast mm",
                       max_cast_count=3)
    eng = SpellEngine(cfg)
    gs = _combat_state()
    assert eng.decide(gs) == "cast fireball"
    assert eng.decide(gs) == "cast mm"
    assert eng.decide(gs) == "cast fireball"
    assert eng.decide(gs) is None          # limit hit, no melee swap configured


def test_multi_attack_inert_when_unset():
    cfg = SpellsConfig(attack="cast zap")
    eng = SpellEngine(cfg)
    gs = _combat_state()
    for _ in range(5):
        assert eng.decide(gs) == "cast zap"


def test_attack_spell_initiates_when_monster_present_out_of_combat():
    from mmud.automation.spells import SpellEngine
    from mmud.config.schema import SpellsConfig
    from mmud.state.game_state import GameState, MonsterSighting
    eng = SpellEngine(SpellsConfig(attack="mmis"))
    gs = GameState(); gs.set_hp(100, 100); gs.set_mana(100, 100); gs.set_combat(False)
    gs.monsters_present = [MonsterSighting(name="orc")]
    assert eng.decide(gs) == "mmis"     # casts to open the fight
