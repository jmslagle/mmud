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
    assert inv.encumbrance_cur == 45     # raw current/max weight, for the pickup cap
    assert inv.encumbrance_max == 120


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


# The live "Realm of Legends" `i` output: ONE comma-wrapped "You are carrying" list
# that inlines worn gear with "(Slot)" tags, a keys line, Wealth, Encumbrance. The
# wrapped continuation lines have NO leading space, and item names may contain "and"
# ("rope and grapple"). MegaMud (inventory_parse_response @0x0043d650) splits on ","/"."
# only — never " and " — and rejoins wraps, so the name survives.
LIVE_INV = [
    "You are carrying 2 platinum pieces, 70 gold crowns, 539 silver nobles, 5",
    "copper farthings, ethereal amulet (Neck), gold jeweled ring (Finger), silver",
    "rimmed hat (Head), chain gauntlets (Hands), chainmail boots (Feet), chainmail",
    "leggings (Legs), chainmail hauberk (Torso), greatcloak (Back), flametongue",
    "(Weapon Hand), rope and grapple",
    "You have the following keys:  brass key, bone key, 8 black star keys.",
    "Wealth: 32395 copper farthings",
    "Encumbrance: 1789/2880 - Medium [62%]",
]


def test_live_wrapped_inventory_keeps_multiword_and_item():
    inv = _parse(LIVE_INV)
    assert inv is not None
    # the bug: "rope and grapple" must NOT be split on " and ", and must survive the
    # no-leading-space wrap (it's on the last carry line).
    assert "rope and grapple" in inv.carried


def test_live_inventory_parses_slots_keys_and_wrap_rejoin():
    inv = _parse(LIVE_INV)
    held = set(inv.carried) | set(inv.worn)
    assert "rope and grapple" in held
    assert "flametongue" in held                 # slot "(Weapon Hand)" stripped
    assert "chainmail hauberk" in held           # rejoined across the wrap
    assert "brass key" in inv.carried            # keys line parsed as carried
    assert ("black star keys", 8) in inv.carried_counts.items()
    assert inv.encumbrance_level == "medium" and inv.encumbrance_pct == 62
