from mmud.automation.equip import EquipDecider
from mmud.automation.decision import PRIO_EQUIP
from mmud.data.item_db import ItemDB
from mmud.data.binary import Item
from mmud.state.game_state import GameState
from mmud.state.inventory import Inventory
from mmud.state.tasks import TaskType


def _item(name, slot):
    return Item(record_id=1, name=name, source="", suffix="",
                item_type=1, equip_slot=slot, ac_or_dmg=0, weight=0,
                value=0, extra_stat1=0, flags=0x40000000)


def _decider(items, auto=True):
    return EquipDecider(ItemDB(items), enabled=auto, now=lambda: 7.0)


def test_equips_carried_equippable():
    gs = GameState()
    gs.inventory = Inventory(carried_counts={"leather helm": 1})
    d = _decider([_item("leather helm", slot=3)])
    assert d.decide(gs) == "equip leather helm"
    assert gs.task.type is TaskType.EQUIPPING
    assert gs.task.priority == PRIO_EQUIP


def test_only_items_allow_list_restricts_equip():
    gs = GameState()
    gs.inventory = Inventory(carried_counts={"leather helm": 1, "fine broadsword": 1})
    d = EquipDecider(ItemDB([_item("leather helm", slot=3),
                             _item("fine broadsword", slot=1)]),
                     enabled=True, only_items=["broadsword"], now=lambda: 7.0)
    # only the allow-listed item is equipped; the helm is left alone
    assert d.decide(gs) == "equip fine broadsword"


def test_skips_already_worn():
    gs = GameState()
    gs.inventory = Inventory(carried_counts={"leather helm": 1},
                             worn=["leather helm"])
    d = _decider([_item("leather helm", slot=3)])
    assert d.decide(gs) is None


def test_skips_non_equippable():
    gs = GameState()
    gs.inventory = Inventory(carried_counts={"iron rations": 2})
    d = _decider([_item("iron rations", slot=0)])
    assert d.decide(gs) is None


def test_disabled():
    gs = GameState()
    gs.inventory = Inventory(carried_counts={"leather helm": 1})
    d = _decider([_item("leather helm", slot=3)], auto=False)
    assert d.decide(gs) is None


def test_skips_in_combat():
    gs = GameState()
    gs.set_combat(True)
    gs.inventory = Inventory(carried_counts={"leather helm": 1})
    assert _decider([_item("leather helm", slot=3)]).decide(gs) is None
