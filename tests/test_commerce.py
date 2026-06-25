from mmud.automation.commerce import CommerceEngine, deposit_copper
from mmud.config.schema import CommerceConfig, ItemsConfig
from mmud.state.game_state import GameState
from mmud.state.inventory import Inventory
from mmud.state.tasks import TaskType


def test_deposit_copper_sums_denominations():
    line = "You deposit 61 gold crowns, 292 silver nobles, 999 copper farthings."
    assert deposit_copper(line) == 61 * 100 + 292 * 10 + 999


def test_deposit_copper_single_denomination():
    assert deposit_copper("You deposit 5 copper farthings.") == 5


def test_deposit_copper_ignores_non_deposit_lines():
    assert deposit_copper("On deposit: 68157 copper farthings [681.57 gold crowns]") is None
    assert deposit_copper("withdraw or deposit their hard-earned cash.") is None


class _Harness:
    """Fake bot callables; records navigation/resume calls."""

    def __init__(self, nav_reply="Navigating to BANK (3 steps)",
                 looping=False, traveling=False):
        self.navigated: list[str] = []
        self.resumed = 0
        self._nav_reply = nav_reply
        self.looping = looping
        self.traveling = traveling

    def navigate(self, code):
        self.navigated.append(code)
        return self._nav_reply

    def make(self, commerce_cfg, items_cfg=None):
        return CommerceEngine(
            commerce_cfg, items_cfg or ItemsConfig(),
            navigate=self.navigate,
            resume_loop=lambda: setattr(self, "resumed", self.resumed + 1),
            loop_running=lambda: self.looping,
            travel_active=lambda: self.traveling,
        )


def _rich_state(copper=500, room="HOME"):
    gs = GameState()
    gs.set_room(room)
    gs.inventory = Inventory(coins={"copper": copper})
    gs.inventory_dirty = False
    return gs


def test_deposit_trigger_navigates_to_bank():
    h = _Harness()
    eng = h.make(CommerceConfig(bank_room="BANK"),
                 ItemsConfig(max_wealth=100, min_wealth=10))
    gs = _rich_state(copper=500)
    assert eng.decide(gs) is None            # detour armed, travel does the moving
    assert h.navigated == ["BANK"]


def test_no_trigger_when_under_max_wealth():
    h = _Harness()
    eng = h.make(CommerceConfig(bank_room="BANK"),
                 ItemsConfig(max_wealth=1000, min_wealth=10))
    assert eng.decide(_rich_state(copper=500)) is None
    assert h.navigated == []


def test_no_trigger_when_inventory_dirty():
    h = _Harness()
    eng = h.make(CommerceConfig(bank_room="BANK"),
                 ItemsConfig(max_wealth=100, min_wealth=10))
    gs = _rich_state(copper=500)
    gs.inventory_dirty = True                # stale data: wait for refresh
    assert eng.decide(gs) is None
    assert h.navigated == []


def test_no_trigger_while_traveling():
    h = _Harness(traveling=True)
    eng = h.make(CommerceConfig(bank_room="BANK"),
                 ItemsConfig(max_wealth=100, min_wealth=10))
    assert eng.decide(_rich_state(copper=500)) is None
    assert h.navigated == []


def test_failed_navigation_disables_trigger():
    h = _Harness(nav_reply="No known route to BANK")
    eng = h.make(CommerceConfig(bank_room="BANK"),
                 ItemsConfig(max_wealth=100, min_wealth=10))
    gs = _rich_state(copper=500)
    assert eng.decide(gs) is None
    assert eng.decide(gs) is None            # not retried forever
    assert h.navigated == ["BANK"]           # exactly one attempt


def test_deposit_work_on_arrival_then_resume():
    h = _Harness(looping=True)
    eng = h.make(CommerceConfig(bank_room="BANK"),
                 ItemsConfig(max_wealth=100, min_wealth=10))
    gs = _rich_state(copper=500)
    eng.decide(gs)                           # arm detour
    gs.set_room("BANK")                      # arrived
    assert eng.decide(gs) == "deposit 490 copper"   # 500 - min_wealth(10)
    assert gs.inventory_dirty is False       # dirty only at END of work
    assert eng.decide(gs) is None            # work done -> idle
    assert gs.inventory_dirty is True        # forces re-sync; blocks re-trigger
    assert h.resumed == 1                    # loop restarted


def test_withdraw_when_poor():
    h = _Harness()
    eng = h.make(CommerceConfig(bank_room="BANK"),
                 ItemsConfig(max_wealth=0, min_wealth=1000))
    gs = _rich_state(copper=50)
    eng.decide(gs)
    gs.set_room("BANK")
    assert eng.decide(gs) == "withdraw 950 copper"


def test_sell_detour_one_item_per_decide():
    h = _Harness()
    eng = h.make(CommerceConfig(shop_room="SHOP", sell_items=["rusty sword", "orc ear"]))
    gs = _rich_state(copper=0)
    gs.inventory = Inventory(carried_counts={"rusty sword": 1, "torch": 1,
                                             "orc ear": 2})
    gs.inventory_dirty = False
    eng.decide(gs)
    assert h.navigated == ["SHOP"]
    gs.set_room("SHOP")
    assert eng.decide(gs) == "sell rusty sword"
    assert eng.decide(gs) == "sell orc ear"
    assert eng.decide(gs) is None


def test_buy_missing_items():
    h = _Harness()
    eng = h.make(CommerceConfig(shop_room="SHOP", buy_items=["torch", "rations"]))
    gs = _rich_state(copper=100)
    gs.inventory = Inventory(carried_counts={"torch": 1})
    gs.inventory_dirty = False
    eng.decide(gs)
    gs.set_room("SHOP")
    assert eng.decide(gs) == "buy rations"
    assert eng.decide(gs) is None


def test_train_detour_uses_training_task():
    h = _Harness()
    eng = h.make(CommerceConfig(train_room="TRNR", auto_train=True))
    gs = _rich_state(copper=0)
    eng.on_line("You have enough experience to advance a level!")
    eng.decide(gs)
    assert h.navigated == ["TRNR"]
    gs.set_room("TRNR")
    assert eng.decide(gs) == "train"
    assert gs.task.type is TaskType.TRAINING
    eng.on_line("You advance to level 5!")   # clears the ready flag
    gs.complete_task()
    assert eng.decide(gs) is None
