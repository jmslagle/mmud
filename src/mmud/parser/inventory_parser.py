from __future__ import annotations
import re
from mmud.state.inventory import Inventory, WEALTH_RATES

_CARRYING_RE = re.compile(r"^You are carrying\s+(.*)$", re.IGNORECASE)
_WEARING_RE = re.compile(r"^You are wearing\s+(.*)$", re.IGNORECASE)
# "You have the following keys:  brass key, bone key, 8 black star keys." — keys are
# carried items (a 'brass key' path gate is satisfied by holding one).
_KEYS_RE = re.compile(r"^You have the following keys:\s*(.*)$", re.IGNORECASE)
_NOKEYS_RE = re.compile(r"^You have no keys\.?$", re.IGNORECASE)
_WEALTH_RE = re.compile(
    r"^Wealth:\s+(\d+)\s+(copper|silver|gold|platinum|runic)", re.IGNORECASE)
# The server spells it "Encumbrance"; the MegaMud binary hard-codes the misspelt
# "Encumberance" — accept either so we never miss the finalising line.
_ENCUMBRANCE_RE = re.compile(
    r"^Encumb[er]+ance:\s+(\d+)/(\d+)\s*-\s*(\w+)\s*\[(\d+)%\]", re.IGNORECASE)
_COUNT_ITEM_RE = re.compile(r"^(\d+)\s+(.*)$")
_ARTICLE_RE = re.compile(r"^(?:a|an|the|some)\s+", re.IGNORECASE)
_COIN_RE = re.compile(
    r"^(\d+)\s+(copper|silver|gold|platinum|runic)\b", re.IGNORECASE)
_SLOT_RE = re.compile(r"\s+\([^)]*\)\s*$")          # trailing " (Neck)", " (Weapon Hand)"


class InventoryParser:
    """Accumulates the multi-line `inv`/`i` response; returns the completed Inventory
    when the Encumbrance line arrives, else None.

    Mirrors MegaMud's inventory_parse_response @0x0043d650: the carrying/wearing list
    is comma-wrapped across lines with NO leading-space marker, item names are split on
    ',' and '.' ONLY (never ' and ', so 'rope and grapple' stays intact), worn gear is
    inlined with a '(Slot)' suffix, and the keys line lists more carried items. We
    accumulate each section's full text across its wrapped lines, then split when the
    section ends (a new header / Wealth / Encumbrance / prompt)."""

    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._carried: dict[str, int] = {}
        self._worn: list[str] = []
        self._coins: dict[str, int] = {}
        self._wealth_copper = 0              # the "Wealth:" total (copper-equiv), if reported
        self._buf = ""                       # accumulated text of the current section
        self._section: str | None = None     # "carrying" | "wearing" | None

    def _flush(self) -> None:
        """Split the accumulated section text into items, now that it's complete."""
        text, self._buf = self._buf, ""
        if not (self._section and text.strip()):
            return
        for raw in text.split(","):
            raw = raw.strip().rstrip(".").strip()
            if not raw:
                continue
            if cm := _COIN_RE.match(raw):
                self._coins[cm.group(2).lower()] = int(cm.group(1))
                continue
            worn = bool(_SLOT_RE.search(raw))
            name = _SLOT_RE.sub("", raw).strip()      # drop the "(Slot)" suffix
            count = 1
            if m := _COUNT_ITEM_RE.match(name):
                count, name = int(m.group(1)), m.group(2)
            name = _ARTICLE_RE.sub("", name).strip().lower()
            if not name:
                continue
            if worn or self._section == "wearing":
                self._worn.append(name)
            else:
                self._carried[name] = self._carried.get(name, 0) + count

    def feed(self, line: str) -> Inventory | None:
        line = line.rstrip()
        if m := _CARRYING_RE.match(line):
            self._flush(); self._section = "carrying"; self._buf = m.group(1)
            return None
        if m := _WEARING_RE.match(line):
            self._flush(); self._section = "wearing"; self._buf = m.group(1)
            return None
        if m := _KEYS_RE.match(line):
            # Treat the keys list as a (possibly wrapped) carrying sub-list.
            self._flush(); self._section = "carrying"; self._buf = m.group(1)
            return None
        if _NOKEYS_RE.match(line):
            self._flush(); self._section = None
            return None
        if m := _WEALTH_RE.match(line):
            # The "Wealth:" line is the TOTAL (copper-equivalent), not a coin denomination —
            # storing it in `coins` polluted the carried map (we tried to drop phantom copper
            # we never had) and double-counted wealth. Keep it as a separate total.
            self._flush(); self._section = None
            self._wealth_copper = int(m.group(1)) * WEALTH_RATES.get(m.group(2).lower(), 1)
            return None
        if m := _ENCUMBRANCE_RE.match(line):
            self._flush()
            inv = Inventory(
                carried_counts=dict(self._carried),
                worn=list(self._worn),
                coins=dict(self._coins),
                encumbrance_pct=int(m.group(4)),
                encumbrance_level=m.group(3).lower(),
                encumbrance_cur=int(m.group(1)),
                encumbrance_max=int(m.group(2)),
                wealth_copper=self._wealth_copper,
            )
            self._reset()
            return inv
        # A wrapped continuation of the current section (no leading-space needed). A
        # prompt or blank line ends the section without finalising the inventory.
        if self._section:
            if not line or line.startswith("["):
                self._flush(); self._section = None
                return None
            self._buf += " " + line
            return None
        return None
