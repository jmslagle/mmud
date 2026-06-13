from mmud.state.inventory import Inventory, RefreshDecider, WEALTH_RATES
from mmud.automation.decision import PRIO_REFRESH
from mmud.state.game_state import GameState
from mmud.state.tasks import TaskType


def test_wealth_total_copper_equivalent():
    inv = Inventory(coins={"copper": 50, "silver": 2, "gold": 1})
    # 50 + 2*10 + 1*100
    assert inv.wealth_total() == 170


def test_wealth_rates_cover_all_denominations():
    assert set(WEALTH_RATES) == {"copper", "silver", "gold", "platinum", "runic"}


def test_gamestate_starts_with_clean_inventory():
    # Deviation from plan: inventory starts CLEAN (not dirty) so an idle bot does
    # not poll `inv` unprompted; the bot marks it dirty on combat-end / get / equip.
    gs = GameState()
    assert gs.inventory_dirty is False
    assert isinstance(gs.inventory, Inventory)


def test_refresh_decider_issues_inv_when_dirty():
    gs = GameState()
    gs.inventory_dirty = True
    d = RefreshDecider(now=lambda: 10.0)
    assert d.decide(gs) == "inv"
    assert gs.task.type is TaskType.WAITING
    assert gs.task.priority == PRIO_REFRESH


def test_refresh_decider_quiet_when_clean():
    gs = GameState()
    gs.inventory_dirty = False
    assert RefreshDecider(now=lambda: 10.0).decide(gs) is None


def test_refresh_decider_quiet_in_combat():
    gs = GameState()
    gs.inventory_dirty = True
    gs.set_combat(True)
    assert RefreshDecider(now=lambda: 10.0).decide(gs) is None


def test_refresh_decider_uses_configured_command():
    from mmud.state.inventory import RefreshDecider
    from mmud.state.game_state import GameState
    gs = GameState()
    gs.inventory_dirty = True
    assert RefreshDecider("i").decide(gs) == "i"


def test_refresh_decider_defaults_to_inv():
    from mmud.state.inventory import RefreshDecider
    from mmud.state.game_state import GameState
    gs = GameState()
    gs.inventory_dirty = True
    assert RefreshDecider().decide(gs) == "inv"
