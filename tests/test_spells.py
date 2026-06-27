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


class _Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def test_bless_interval_respected():
    cfg = SpellsConfig(bless=[BlessSpell(cmd="bless", mana_pct=0.50, interval_s=600)])
    gs = GameState(); gs.set_mana(90, 100)
    clk = _Clock()
    engine = SpellEngine(cfg, now=clk)
    assert engine.decide(gs) == "bless"   # first cast
    clk.t += 60                            # 60s < 600s interval
    assert engine.decide(gs) is None       # not due yet


def test_bless_recast_after_interval():
    cfg = SpellsConfig(bless=[BlessSpell(cmd="bless", mana_pct=0.50, interval_s=600)])
    gs = GameState(); gs.set_mana(90, 100)
    clk = _Clock()
    engine = SpellEngine(cfg, now=clk)
    engine.decide(gs)
    clk.t += 600                           # interval elapsed
    assert engine.decide(gs) == "bless"


def test_bless_interval_auto_derived_from_spell_duration():
    # interval_s=0 -> derive from SPELLS.MD duration (minutes) at 85%: blur=4min
    # -> 204s.
    cfg = SpellsConfig(bless=[BlessSpell(cmd="blur", mana_pct=0.50, interval_s=0)])
    gs = GameState(); gs.set_mana(90, 100)
    clk = _Clock()
    engine = SpellEngine(cfg, bless_durations={"blur": 4}, now=clk)
    assert engine.decide(gs) == "blur"
    clk.t += 180                           # 180s < 204s
    assert engine.decide(gs) is None
    clk.t += 40                            # 220s > 204s
    assert engine.decide(gs) == "blur"


def test_bless_recast_immediately_on_fade_message():
    cfg = SpellsConfig(bless=[BlessSpell(cmd="c blur", mana_pct=0.50, interval_s=600,
                                         refresh_on=r"vision (?:returns|clears)")])
    gs = GameState(); gs.set_mana(90, 100)
    clk = _Clock()
    engine = SpellEngine(cfg, now=clk)
    assert engine.decide(gs) == "c blur"   # cast
    clk.t += 30                            # well within the interval
    assert engine.decide(gs) is None       # not due on the timer
    engine.on_line("Your vision returns to normal.")   # buff faded
    assert engine.decide(gs) == "c blur"   # recast at once


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
    from mmud.state.game_state import MonsterSighting
    cfg = SpellsConfig(attack="magic missile")
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(80, 100)
    gs.monsters_present = [MonsterSighting(name="orc")]
    engine = SpellEngine(cfg)
    cmd = engine.decide(gs)
    assert cmd == "magic missile orc"


def test_cast_count_resets_on_kill_not_just_empty_room():
    # MegaMud (combat_flee_or_hide_decide @0x407f70) resets the main attack cast counter
    # on EVERY kill, so it re-casts up to MaxCastCnt against each NEW monster — not
    # MaxCastCnt total per room. Resetting only when the room empties made the bot melee
    # everything with full mana after the first few casts ("wonky").
    from mmud.state.game_state import MonsterSighting
    cfg = SpellsConfig(attack="fjet", max_cast_count=2)
    gs = GameState()
    gs.set_combat(True)
    gs.set_hp(80, 100)
    gs.set_mana(80, 100)            # well above the mana floor
    gs.monsters_present = [MonsterSighting(name="orc")]
    engine = SpellEngine(cfg, mana_attack_pct=0.2)
    assert engine.decide(gs) == "fjet orc"     # cast 1
    assert engine.decide(gs) == "fjet orc"     # cast 2
    assert engine.decide(gs) is None           # cap reached -> melee
    # A kill (room still has the next monster, still in combat) must reset the cap.
    engine.on_kill()
    gs.monsters_present = [MonsterSighting(name="rat")]
    assert engine.decide(gs) == "fjet rat"     # casts the new target, not stuck meleeing


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


def test_attack_spell_skips_good_npc():
    # kill-type 2 (shopkeeper/guard) -> never auto-nuked, out of combat
    cfg = SpellsConfig(attack="magic missile")
    gs = GameState(); gs.set_hp(80, 100); gs.set_mana(80, 100); gs.set_combat(False)
    gs.monsters_present = [MonsterSighting(name="happy guardsman", kill_type=2)]
    assert SpellEngine(cfg).decide(gs) is None


def test_attack_spell_skips_neutral_unless_attack_neutral():
    cfg = SpellsConfig(attack="magic missile")
    gs = GameState(); gs.set_hp(80, 100); gs.set_mana(80, 100); gs.set_combat(False)
    gs.monsters_present = [MonsterSighting(name="giant rat", kill_type=3)]
    assert SpellEngine(cfg).decide(gs) is None
    assert SpellEngine(cfg, attack_neutral=True).decide(gs) == "magic missile giant rat"


def test_attack_spell_casts_on_hostile():
    cfg = SpellsConfig(attack="magic missile")
    gs = GameState(); gs.set_hp(80, 100); gs.set_mana(80, 100); gs.set_combat(False)
    gs.monsters_present = [MonsterSighting(name="kobold thief", kill_type=4)]
    assert SpellEngine(cfg).decide(gs) == "magic missile kobold thief"


def test_no_bare_cast_when_in_combat_but_no_monster():
    # in_combat can linger for a beat after the last kill with an empty roster;
    # the spell engine must NOT cast a targetless "magic missile".
    cfg = SpellsConfig(attack="magic missile")
    gs = GameState(); gs.set_hp(80, 100); gs.set_mana(80, 100); gs.set_combat(True)
    gs.monsters_present = []
    assert SpellEngine(cfg).decide(gs) is None


def test_attack_spell_skips_cast_below_mana_floor():
    # MegaMud: cast only if mana% >= ManaAttack% (floor); below it -> melee
    # (SpellEngine declines so the combat engine swings).
    cfg = SpellsConfig(attack="magic missile")
    gs = GameState(); gs.set_hp(80, 100); gs.set_mana(5, 100); gs.set_combat(True)
    gs.monsters_present = [MonsterSighting(name="orc", kill_type=4)]
    assert SpellEngine(cfg, mana_attack_pct=0.20).decide(gs) is None    # 5% < 20%
    gs.set_mana(80, 100)
    assert SpellEngine(cfg, mana_attack_pct=0.20).decide(gs) == "magic missile orc"


def test_attack_spell_stops_after_max_cast_count_then_melee():
    cfg = SpellsConfig(attack="magic missile", max_cast_count=2)
    gs = GameState(); gs.set_hp(80, 100); gs.set_mana(80, 100); gs.set_combat(True)
    gs.monsters_present = [MonsterSighting(name="orc", kill_type=4)]
    eng = SpellEngine(cfg, mana_attack_pct=0.20)
    assert eng.decide(gs) == "magic missile orc"   # cast 1
    assert eng.decide(gs) == "magic missile orc"   # cast 2
    cmd = eng.decide(gs)                            # cap reached -> melee
    assert cmd in (None, cfg.melee_weapon_cmd or None)


def test_attack_spell_fights_back_in_combat_even_npc():
    cfg = SpellsConfig(attack="magic missile")
    gs = GameState(); gs.set_hp(80, 100); gs.set_mana(80, 100); gs.set_combat(True)
    gs.monsters_present = [MonsterSighting(name="happy guardsman", kill_type=2)]
    assert SpellEngine(cfg).decide(gs) == "magic missile happy guardsman"


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
    assert eng.decide(gs) == "cast zap orc"
    assert eng.decide(gs) == "cast zap orc"
    assert eng.decide(gs) == "arm warhammer"
    assert eng.decide(gs) is None          # melee decider's turn now


def test_counter_resets_and_swaps_back_after_combat():
    cfg = SpellsConfig(attack="cast zap", max_cast_count=1,
                       cast_weapon_cmd="arm staff", melee_weapon_cmd="arm warhammer")
    eng = SpellEngine(cfg)
    gs = _combat_state()
    assert eng.decide(gs) == "cast zap orc"
    assert eng.decide(gs) == "arm warhammer"
    gs.set_combat(False); gs.monsters_present.clear()
    assert eng.decide(gs) == "arm staff"   # swap back once, out of combat
    assert eng.decide(gs) is None


def test_unlimited_when_zero():
    cfg = SpellsConfig(attack="cast zap", max_cast_count=0)
    eng = SpellEngine(cfg)
    gs = _combat_state()
    for _ in range(10):
        assert eng.decide(gs) == "cast zap orc"


def test_multi_attack_chains_after_primary_attack():
    cfg = SpellsConfig(attack="cast zap", multi_attack="cast bolt")
    eng = SpellEngine(cfg)
    gs = _combat_state()
    assert eng.decide(gs) == "cast zap orc"     # primary: targeted
    assert eng.decide(gs) == "cast bolt"        # multi/AoE: bare
    assert eng.decide(gs) == "cast zap orc"
    assert eng.decide(gs) == "cast bolt"


def test_multi_attack_respects_max_cast_count():
    # primary/multi alternation must honor the cast limit: 3 casts total
    # (fireball, mm, fireball), then the limit is hit. No melee_weapon_cmd
    # configured, so the 4th decide returns None (engine yields, no swap).
    cfg = SpellsConfig(attack="cast fireball", multi_attack="cast mm",
                       max_cast_count=3)
    eng = SpellEngine(cfg)
    gs = _combat_state()
    assert eng.decide(gs) == "cast fireball orc"   # primary: targeted
    assert eng.decide(gs) == "cast mm"             # multi/AoE: bare
    assert eng.decide(gs) == "cast fireball orc"
    assert eng.decide(gs) is None          # limit hit, no melee swap configured


def test_multi_attack_inert_when_unset():
    cfg = SpellsConfig(attack="cast zap")
    eng = SpellEngine(cfg)
    gs = _combat_state()
    for _ in range(5):
        assert eng.decide(gs) == "cast zap orc"


def test_attack_spell_initiates_when_monster_present_out_of_combat():
    from mmud.automation.spells import SpellEngine
    from mmud.config.schema import SpellsConfig
    from mmud.state.game_state import GameState, MonsterSighting
    eng = SpellEngine(SpellsConfig(attack="mmis"))
    gs = GameState(); gs.set_hp(100, 100); gs.set_mana(100, 100); gs.set_combat(False)
    gs.monsters_present = [MonsterSighting(name="orc")]
    assert eng.decide(gs) == "mmis orc"     # casts to open the fight, ON the target


def test_attack_spell_appends_target():
    # Regression: a single-target offensive spell (mmis) MUST include the target,
    # else the server replies "You must specify a target for that spell!" and the
    # bot loops forever. MegaMud's combat_spell_cast sends "{spell} {target}".
    eng = SpellEngine(SpellsConfig(attack="mmis"))
    gs = _combat_state()                     # one "orc" present, in combat
    assert eng.decide(gs) == "mmis orc"


def test_attack_spell_uses_monster_priority_target():
    # The nuke targets the same monster melee would: priority wins over order.
    eng = SpellEngine(SpellsConfig(attack="mmis"),
                      monster_priority=["goblin"], attack_order="first")
    gs = GameState(); gs.set_hp(100, 100); gs.set_mana(100, 100); gs.set_combat(True)
    gs.monsters_present = [MonsterSighting(name="orc"), MonsterSighting(name="goblin")]
    assert eng.decide(gs) == "mmis goblin"


def test_multi_attack_aoe_is_cast_bare():
    # AoE / multi-attack spells take no target (MegaMud casts them bare); only the
    # primary single-target attack gets the target appended.
    eng = SpellEngine(SpellsConfig(attack="mmis", multi_attack="cast fireball"))
    gs = _combat_state()
    assert eng.decide(gs) == "mmis orc"      # primary: targeted
    assert eng.decide(gs) == "cast fireball" # AoE: bare


def test_attack_cast_begins_casting_task_to_pace():
    # Regression (spam): each attack cast begins a CASTING task so the decision
    # engine holds the spell+melee slots for a combat round, instead of recasting
    # on every server line. Mirrors MegaMud combat_spell_cast (task 0x11 + 4s).
    from mmud.state.tasks import TaskType
    from mmud.automation.decision import PRIO_SPELLS
    eng = SpellEngine(SpellsConfig(attack="mmis"), now=lambda: 100.0)
    gs = _combat_state()
    assert eng.decide(gs) == "mmis orc"
    assert gs.task.type is TaskType.CASTING
    assert gs.task.priority == PRIO_SPELLS
    assert gs.task.deadline > 100.0          # timed, so the 1Hz ticker clears it


def test_caster_does_not_spam_or_melee_during_cast_cooldown():
    # End-to-end via the DecisionEngine: after one cast the bot must NOT recast
    # NOR fall through to melee (lower priority) until the round elapses.
    from mmud.automation.decision import DecisionEngine, PRIO_SPELLS, PRIO_COMBAT
    from mmud.combat.combat import CombatEngine
    from mmud.config.schema import CombatConfig
    clock = [100.0]
    engine = DecisionEngine()
    engine.register("spells",
                    SpellEngine(SpellsConfig(attack="mmis"), now=lambda: clock[0]),
                    PRIO_SPELLS)
    engine.register("combat", CombatEngine(CombatConfig(attack_cmd="kill")),
                    PRIO_COMBAT)
    gs = _combat_state()
    assert engine.next_command(gs) == "mmis orc"   # cast once
    assert engine.next_command(gs) is None         # paced: no recast, no melee
    # round elapses; the ticker's timeout check clears the expired CASTING task
    clock[0] += 5.0
    if gs.task.expired(clock[0]):
        gs.abort_task()
    assert engine.next_command(gs) == "mmis orc"   # casts again next round
