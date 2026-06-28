from mmud.automation.items import LootMonitor, GetDecider
from mmud.automation.decision import PRIO_ITEMS
from mmud.config.schema import ItemsConfig
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType


def test_loot_monitor_sees_ground_items():
    m = LootMonitor()
    gs = GameState()
    m.process_line("You notice a rusty sword here.", gs)
    assert "rusty sword" in gs.ground_items


def test_loot_monitor_sees_coins():
    m = LootMonitor()
    gs = GameState()
    m.process_line("You notice 23 copper farthings here.", gs)
    assert ("copper", 23) in gs.ground_coins.items()


def test_loot_monitor_ignores_monsters():
    m = LootMonitor(is_monster=lambda name: name == "orc")
    gs = GameState()
    m.process_line("You notice an orc here.", gs)
    assert gs.ground_items == []


def test_get_decider_picks_up_item():
    gs = GameState()
    gs.ground_items.append("rusty sword")
    d = GetDecider(ItemsConfig(auto_get=True), now=lambda: 5.0)
    assert d.decide(gs) == "get rusty sword"
    assert gs.task.type is TaskType.GETTING
    assert gs.task.priority == PRIO_ITEMS
    assert "rusty sword" not in gs.ground_items   # claimed


def test_get_decider_respects_auto_get_off():
    gs = GameState()
    gs.ground_items.append("rusty sword")
    assert GetDecider(ItemsConfig(auto_get=False), now=lambda: 5.0).decide(gs) is None


def test_get_decider_picks_configured_item_even_when_auto_get_off():
    # Selective pickup: grab named items (e.g. quest keys) without auto-getting all.
    gs = GameState()
    gs.ground_items.append("a black star key")
    gs.ground_items.append("rusty sword")
    d = GetDecider(ItemsConfig(auto_get=False, get_items=["black star key"]),
                   now=lambda: 5.0)
    assert d.decide(gs) == "get a black star key"   # case-insensitive substring
    assert "rusty sword" in gs.ground_items          # non-listed item left alone


def test_get_items_match_is_case_insensitive_substring():
    gs = GameState()
    gs.ground_items.append("Ancient Black Star Key of Doom")
    d = GetDecider(ItemsConfig(auto_get=False, get_items=["black star key"]),
                   now=lambda: 5.0)
    assert d.decide(gs) == "get Ancient Black Star Key of Doom"


def test_get_decider_collects_configured_coins():
    gs = GameState()
    gs.ground_coins["copper"] = 23
    d = GetDecider(ItemsConfig(auto_cash=True, collect_copper=True), now=lambda: 5.0)
    assert d.decide(gs) == "get 23 copper"   # amount included (server GET syntax)
    assert "copper" not in gs.ground_coins
    assert gs.task.payload.get("coin") is True   # tagged so failure won't blacklist


def test_cash_cmd_is_fixed_get_amount_denom():
    # MegaMud hardcodes the get-currency verb (ref §3): always "get {amount} {denom}",
    # not a user-editable template.
    gs = GameState()
    gs.ground_coins["silver"] = 13
    d = GetDecider(ItemsConfig(auto_cash=True, collect_silver=True), now=lambda: 5.0)
    assert d.decide(gs) == "get 13 silver"


def test_coin_get_is_tagged_coin_not_blacklistable():
    # Coin pickups are tagged coin=True so a transient "you don't see" failure
    # never blacklists the denomination (coins reappear; items don't).
    gs = GameState()
    gs.ground_coins["silver"] = 13
    d = GetDecider(ItemsConfig(auto_cash=True, collect_silver=True), now=lambda: 5.0)
    d.decide(gs)
    assert gs.task.payload == {"item": "silver", "coin": True}


def test_get_decider_skips_unwanted_denomination():
    gs = GameState()
    gs.ground_coins["runic"] = 1
    d = GetDecider(ItemsConfig(auto_cash=True, collect_runic=False), now=lambda: 5.0)
    assert d.decide(gs) is None


def test_get_decider_skips_in_combat():
    gs = GameState()
    gs.set_combat(True)
    gs.ground_items.append("rusty sword")
    assert GetDecider(ItemsConfig(auto_get=True), now=lambda: 5.0).decide(gs) is None


def test_ungettable_marking():
    gs = GameState()
    d = GetDecider(ItemsConfig(auto_get=True), now=lambda: 5.0)
    gs.ground_items.append("fountain")
    assert d.decide(gs) == "get fountain"
    d.mark_ungettable("fountain")
    gs.ground_items.append("fountain")
    assert d.decide(gs) is None


def test_loot_monitor_strips_leading_count():
    from mmud.automation.items import LootMonitor
    gs = GameState()
    LootMonitor().process_line("You notice 2 log raft here.", gs)
    assert gs.ground_items == ["log raft"]      # count stripped, not "2 log raft"


def test_loot_monitor_strips_count_and_article():
    from mmud.automation.items import LootMonitor
    gs = GameState()
    LootMonitor().process_line("You notice a rusty sword here.", gs)
    assert gs.ground_items == ["rusty sword"]


def test_get_fail_re_matches_server_syntax_error():
    from mmud.automation.items import _GET_FAIL_RE
    assert _GET_FAIL_RE.search("Syntax: GET {Amount} {Currency}")
    assert _GET_FAIL_RE.search("Syntax: GET 2 {Currency}")
    assert _GET_FAIL_RE.search("You can't get that.")
    assert _GET_FAIL_RE.search("You don't see that here.")
    assert not _GET_FAIL_RE.search("You get a rusty sword.")


def test_begin_does_not_set_inventory_dirty():
    # so RefreshDecider can't preempt the GETTING task before the get resolves
    gs = GameState()
    gs.ground_items.append("rusty sword")
    GetDecider(ItemsConfig(auto_get=True), now=lambda: 5.0).decide(gs)
    assert gs.inventory_dirty is False
    assert gs.task.type is TaskType.GETTING


# ---- encumbrance pickup cap (MegaMud DontBeHeavy/DontBeMedium) -------------

from mmud.state.inventory import Inventory


class _FakeItemDB:
    """Minimal name->weight stub for the pickup-cap tests."""
    def __init__(self, weights):
        self._w = {k.lower(): v for k, v in weights.items()}

    def find(self, name):
        w = self._w.get(name.lower())
        if w is None:
            return None
        from types import SimpleNamespace
        return SimpleNamespace(weight=w)


def _inv(cur, mx):
    return Inventory(encumbrance_cur=cur, encumbrance_max=mx)


def test_item_skipped_when_it_would_exceed_pickup_cap():
    # DontBeHeavy caps pickup at 67% of max (2880*67//100 = 1929). A 100-weight item at
    # cur=1900 -> 2000 > 1929 -> skip (don't get), but DON'T halt anything.
    gs = GameState()
    gs.inventory = _inv(1900, 2880)
    gs.ground_items.append("anvil")
    d = GetDecider(ItemsConfig(auto_get=True, dont_go_heavy=True),
                   item_db=_FakeItemDB({"anvil": 100}), now=lambda: 5.0)
    assert d.decide(gs) is None
    assert "anvil" in gs.ground_items          # left on the ground, not claimed


def test_item_grabbed_when_under_pickup_cap():
    gs = GameState()
    gs.inventory = _inv(100, 2880)             # far below 67% cap
    gs.ground_items.append("anvil")
    d = GetDecider(ItemsConfig(auto_get=True, dont_go_heavy=True),
                   item_db=_FakeItemDB({"anvil": 100}), now=lambda: 5.0)
    assert d.decide(gs) == "get anvil"


def test_get_items_bypass_the_weight_cap():
    # Named must-grabs (quest keys) are taken even while Heavy.
    gs = GameState()
    gs.inventory = _inv(2870, 2880)            # essentially full
    gs.ground_items.append("black star key")
    d = GetDecider(ItemsConfig(auto_get=False, dont_go_heavy=True,
                               get_items=["black star key"]),
                   item_db=_FakeItemDB({"black star key": 50}), now=lambda: 5.0)
    assert d.decide(gs) == "get black star key"


def test_no_weight_gate_before_first_inventory_read():
    # encumbrance_max == 0 -> weight unknown -> never gate (don't regress to silent skips).
    gs = GameState()
    gs.inventory = _inv(0, 0)
    gs.ground_items.append("anvil")
    d = GetDecider(ItemsConfig(auto_get=True, dont_go_heavy=True),
                   item_db=_FakeItemDB({"anvil": 9999}), now=lambda: 5.0)
    assert d.decide(gs) == "get anvil"


def test_cash_below_target_bypasses_weight_cap():
    # MegaMud: AutoCash cash BELOW the wealth target is "needed" -> bypasses DontBeHeavy.
    # So coins are still grabbed after a fight even while Heavy (the cap is for items/hoard).
    gs = GameState()
    gs.inventory = Inventory(encumbrance_cur=2870, encumbrance_max=2880,  # essentially full
                             coins={"silver": 5})                          # wealth 50
    gs.ground_coins["gold"] = 9
    d = GetDecider(ItemsConfig(auto_cash=True, collect_gold=True, dont_go_heavy=True,
                               max_wealth=100000), now=lambda: 5.0)        # 50 < target
    assert d.decide(gs) == "get 9 gold"        # grabbed despite being over the soft cap


def test_coin_skipped_when_over_cap_and_drop_disabled():
    # ABOVE the wealth target (cash no longer "needed") a coin stack that won't fit and
    # drop_coins off -> skip (don't get).
    gs = GameState()
    gs.inventory = Inventory(encumbrance_cur=1929, encumbrance_max=2880,  # at cap 1929
                             coins={"copper": 5})                          # wealth 5
    gs.ground_coins["copper"] = 3                                          # ceil->1 -> 1930 > cap
    d = GetDecider(ItemsConfig(auto_cash=True, collect_copper=True, dont_go_heavy=True,
                               drop_coins=False, max_wealth=1), now=lambda: 5.0)  # 5 >= 1
    assert d.decide(gs) is None


def test_coin_drop_to_upgrade_drops_cheapest_coin():
    # ABOVE target (hoarding): a gold stack won't fit + drop_coins on -> drop copper
    # (cheapest, < gold) to make room. Gold stays on the ground for next turn.
    gs = GameState()
    gs.inventory = Inventory(encumbrance_cur=1929, encumbrance_max=2880,
                             coins={"copper": 30, "silver": 5})            # wealth 80
    gs.ground_coins["gold"] = 9                # ceil(9/3)=3 weight; 1929+3 > 1929 cap
    d = GetDecider(ItemsConfig(auto_cash=True, collect_gold=True, dont_go_heavy=True,
                               drop_coins=True, max_wealth=1), now=lambda: 5.0)  # 80 >= 1
    cmd = d.decide(gs)
    assert cmd is not None and cmd.startswith("drop ") and "copper" in cmd  # cheapest
    assert "gold" in gs.ground_coins           # not picked up yet; retry next turn
