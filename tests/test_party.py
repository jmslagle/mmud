from mmud.automation.party import PartyDecider, InviteMonitor
from mmud.automation.decision import PRIO_PARTY
from mmud.config.schema import PartyBless, PartyConfig, PlayerRule
from mmud.parser.party_parser import PartyMember
from mmud.state.game_state import GameState
from mmud.state.inventory import Inventory
from mmud.state.tasks import TaskType


def _decider(cfg=None, rules=(), t=100.0):
    holder = {"t": t}
    d = PartyDecider(cfg or PartyConfig(), list(rules), now=lambda: holder["t"])
    return d, holder


def _state(*members):
    gs = GameState()
    gs.party = list(members)
    gs.inventory_dirty = False
    return gs


def test_heals_lowest_member():
    # hp 45/35: below heal_hp_pct (50) but above wait_hp_pct (30) so the
    # wait protocol stays quiet and the heal fires.
    d, _ = _decider(PartyConfig(heal_spell="cast heal", heal_hp_pct=0.50))
    gs = _state(PartyMember(name="Krang", hp_pct=45),
                PartyMember(name="Beeze", hp_pct=35))
    assert d.decide(gs) == "cast heal Beeze"
    assert gs.task.type is TaskType.CASTING
    assert gs.task.priority == PRIO_PARTY


def test_dont_heal_rule_respected():
    # hp 40: below heal_hp_pct (50) but above wait_hp_pct (30) — isolates the
    # heal-exclusion path so dont_heal is what suppresses the action.
    d, _ = _decider(PartyConfig(heal_spell="cast heal", heal_hp_pct=0.50),
                    rules=[PlayerRule(name="Beeze", dont_heal=True)])
    gs = _state(PartyMember(name="Beeze", hp_pct=40))
    assert d.decide(gs) is None


def test_wait_then_resume():
    # status_cmd engages party automation (the wait protocol is gated on
    # heal_spell-or-status_cmd so pure-default configs stay inert).
    cfg = PartyConfig(wait_hp_pct=0.30, wait_cmd="wait", resume_cmd="go",
                      wait_max_seconds=30, status_cmd="par",
                      status_interval_s=9999)
    d, _ = _decider(cfg)
    gs = _state(PartyMember(name="Krang", hp_pct=10))
    assert d.decide(gs) == "wait"
    assert gs.task.type is TaskType.WAITING
    assert d.decide(gs) is None              # already waiting
    gs.party = [PartyMember(name="Krang", hp_pct=90)]
    assert d.decide(gs) == "go"              # recovered: resume
    assert not gs.task.is_active


def test_bless_slot_cooldown():
    cfg = PartyConfig(bless=[PartyBless(cmd="cast pbless", wait_seconds=60)])
    d, holder = _decider(cfg, t=100.0)
    gs = _state(PartyMember(name="Krang"))
    assert d.decide(gs) == "cast pbless"
    assert d.decide(gs) is None              # cooling down
    holder["t"] = 161.0
    assert d.decide(gs) == "cast pbless"


def test_share_cash_one_denom_per_decide():
    cfg = PartyConfig(share_cash=True)
    d, _ = _decider(cfg)
    gs = _state(PartyMember(name="Krang"))
    gs.inventory = Inventory(coins={"copper": 90, "gold": 2})
    assert d.decide(gs) in ("share 2 gold", "share 90 copper")
    first = gs.inventory_dirty
    assert first is False                    # dirty only after the last share
    second = d.decide(gs)
    assert second is not None and second.startswith("share")
    assert d.decide(gs) is None
    assert gs.inventory_dirty is True        # blocks re-share until refresh


def test_status_refresh_interval():
    cfg = PartyConfig(status_cmd="par", status_interval_s=60)
    d, holder = _decider(cfg, t=100.0)
    gs = _state()                            # works even before a party exists
    assert d.decide(gs) == "par"
    assert d.decide(gs) is None
    holder["t"] = 161.0
    assert d.decide(gs) == "par"


def test_quiet_without_config():
    d, _ = _decider(PartyConfig())
    gs = _state(PartyMember(name="Krang", hp_pct=10))
    assert d.decide(gs) is None


def test_invite_monitor_friends_only():
    m = InviteMonitor([PlayerRule(name="Krang", friend=True)])
    assert m.check("Krang has invited you to join his party.") == "join Krang"
    assert m.check("Sneaky has invited you to join her party.") is None
    assert m.check("Just a normal line") is None
