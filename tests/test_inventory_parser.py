from mmud.parser.inventory_parser import InventoryParser

INV_LINES = [
    "You are carrying a torch, a brass key, 2 iron rations.",
    "You are wearing chainmail armour, a leather helm.",
    "Wealth: 153 copper farthings",
    "Encumbrance: 45/120 - Light [37%]",
]


def _parse(lines):
    p = InventoryParser()
    result = None
    for line in lines:
        result = p.feed(line) or result
    return result


def test_full_inv_block():
    inv = _parse(INV_LINES)
    assert inv is not None
    assert "torch" in inv.carried
    assert ("iron rations", 2) in [(i, c) for i, c in inv.carried_counts.items()]
    assert "chainmail armour" in inv.worn
    assert inv.coins["copper"] == 153
    assert inv.encumbrance_pct == 37
    assert inv.encumbrance_level == "light"


def test_incomplete_block_returns_none():
    p = InventoryParser()
    assert p.feed("You are carrying a torch.") is None   # no encumbrance line yet


def test_multiline_carrying_wrap():
    inv = _parse([
        "You are carrying a torch, a brass key,",
        "  2 iron rations, a healing potion.",
        "Encumbrance: 10/120 - None [8%]",
    ])
    assert "healing potion" in inv.carried


def test_no_wealth_line():
    inv = _parse(["You are carrying a torch.",
                  "Encumbrance: 10/120 - None [8%]"])
    assert inv.coins == {}


def test_unrelated_lines_ignored():
    p = InventoryParser()
    assert p.feed("[HP=100/100]:") is None
    assert p.feed("An orc swings at you!") is None
