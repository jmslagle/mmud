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


def test_get_decider_collects_configured_coins():
    gs = GameState()
    gs.ground_coins["copper"] = 23
    d = GetDecider(ItemsConfig(auto_cash=True, collect_copper=True), now=lambda: 5.0)
    assert d.decide(gs) == "get copper"
    assert "copper" not in gs.ground_coins


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
