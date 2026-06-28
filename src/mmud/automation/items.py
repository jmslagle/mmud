from __future__ import annotations
import re
import time
from typing import Callable
from mmud.automation.decision import PRIO_ITEMS
from mmud.config.schema import ItemsConfig
from mmud.state.game_state import GameState
from mmud.state.inventory import WEALTH_RATES
from mmud.state.tasks import TaskType

GET_TIMEOUT_S = 5.0


def _coin_weight(amount: int) -> int:
    """MegaMud's coin weight: 3 coins per weight unit -> ceil(amount/3) (loot_item_collect)."""
    return (amount + 2) // 3

# "You notice a rusty sword here." / "You notice 23 copper farthings here."
# Tune against the live server (docs/testing-plan.md).
_NOTICE_RE = re.compile(r"^You notice (.+?) here\.?$", re.IGNORECASE)
_COIN_RE = re.compile(
    r"^(\d+)\s+(copper|silver|gold|platinum|runic)\b", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"^(?:a|an|the|some)\s+", re.IGNORECASE)
# A leading quantity ("2 log raft", "3 arrows") is a COUNT, not part of the
# name — strip it so GET sends "get log raft", not "get 2 log raft" (which the
# server mis-reads as a currency amount: "Syntax: GET 2 {Currency}").
_COUNT_RE = re.compile(r"^\d+\s+")
# GET failures: the item can't be taken (scenery, fixtures). Includes this
# server's currency-only syntax error for "get <non-item>". Tune live.
_CANT_GET_RE = re.compile(r"you can'?t (?:get|take|pick up)", re.IGNORECASE)
_GET_FAIL_RE = re.compile(
    r"you can'?t (?:get|take|pick up)|"
    r"you (?:don'?t|do not) see\b|"
    r"(?:isn'?t|is not|aren'?t) here\b|"
    r"\bno .* here\b|"
    r"\bSyntax:\s*GET\b",
    re.IGNORECASE)
# GET success — broadened beyond "you took/get".
_GOT_RE = re.compile(
    r"^you (?:get|got|take|took|pick up|picked up|grab|now have)\b",
    re.IGNORECASE)


class LootMonitor:
    """Watches 'You notice ... here.' lines and records gettable things.

    `is_monster` lets the bot exclude room monsters (passed from the MonsterDB)
    so a noticed creature is not mistaken for loot.
    """

    def __init__(self, is_monster: Callable[[str], bool] | None = None) -> None:
        self._is_monster = is_monster or (lambda name: False)

    def process_line(self, line: str, state: GameState) -> None:
        m = _NOTICE_RE.match(line)
        if not m:
            return
        for raw in re.split(r",\s*|\s+and\s+", m.group(1)):
            raw = raw.strip()
            if not raw:
                continue
            if cm := _COIN_RE.match(raw):
                state.ground_coins[cm.group(2).lower()] = int(cm.group(1))
                continue
            name = _ARTICLE_RE.sub("", _COUNT_RE.sub("", raw)).lower()
            if name and not self._is_monster(name):
                state.ground_items.append(name)


class GetDecider:
    """PRIO_ITEMS slot: pick up coins then items, one GET per decide().

    Weight-aware, mirroring MegaMud's loot_item_collect @0x409880: `dont_go_heavy`/
    `dont_go_medium` cap PICKUP (not movement) at 67%/33% of max weight; items/coins
    that would exceed the cap are skipped. With `drop_coins` (DropCoins), a better coin
    that won't fit triggers dropping the cheapest cheaper coins to make room
    (cash_upgrade_coins_decide @0x409fc0). Named `get_items` always bypass the cap.
    """

    def __init__(self, config: ItemsConfig, item_db=None,
                 now: Callable[[], float] = time.monotonic,
                 on_mark: Callable[[str], None] | None = None) -> None:
        self._cfg = config
        self._item_db = item_db          # ItemDB for per-item weight (None -> don't gate items)
        self._now = now
        self._on_mark = on_mark
        self._ungettable: set[str] = set()

    def mark_ungettable(self, name: str) -> None:
        self._ungettable.add(name.lower())
        if self._on_mark is not None:
            self._on_mark(name)

    def _cap(self, state: GameState, needed: bool) -> int | None:
        """Effective pickup weight cap, or None when weight is unknown (no gate yet).
        DontBeMedium (33%) wins over DontBeHeavy (67%); needed items bypass the reduction."""
        mx = state.inventory.encumbrance_max
        if mx <= 0:
            return None
        if not needed:
            if self._cfg.dont_go_medium:
                return mx * 33 // 100
            if self._cfg.dont_go_heavy:
                return mx * 67 // 100
        return mx

    def decide(self, state: GameState) -> str | None:
        if state.in_combat:
            return None
        if state.max_hp > 0 and state.hp < 0:
            return None        # mortally wounded: "get" is rejected too — don't spam it
        cur = state.inventory.encumbrance_cur
        if self._cfg.auto_cash:
            # Coins obey the DontBeHeavy/DontBeMedium pickup cap exactly like items
            # (MegaMud loot_item_collect @0x409a80). The ONLY thing that bypasses the cap is
            # an active travel-toll requirement (state+0x3188, normally 0 — the loop never
            # routes a toll-gated exit); the wealth/bank target (max_wealth -> MegaMud's
            # MinWealth @+0x3244) drives BANKING, not pickup, so it must NOT bypass the cap.
            # Process denominations HIGHEST-VALUE FIRST (MegaMud room_entity_priority_sort)
            # so a near-full pack spends its remaining capacity on gold before silver.
            cap = self._cap(state, needed=False)
            for denom in sorted(state.ground_coins,
                                key=lambda d: WEALTH_RATES.get(d, 0), reverse=True):
                if not getattr(self._cfg, f"collect_{denom}", False):
                    del state.ground_coins[denom]   # unwanted: forget it
                    continue
                ground_amt = state.ground_coins[denom]
                amount = ground_amt
                if cap is not None and cur + _coin_weight(amount) > cap:
                    # Won't fully fit. First drop cheaper coins to make room for this better
                    # coin (DropCoins). Else take only the portion that fits (MegaMud partial
                    # pickup); if nothing fits, leave it and try the other denominations.
                    if drop := self._coin_upgrade_drop(state, denom, cur, cap, amount):
                        return drop
                    fit = (cap - cur) * 3           # 3 coins per weight unit
                    if fit < 1:
                        continue
                    amount = min(amount, fit)
                if amount >= ground_amt:
                    del state.ground_coins[denom]
                else:
                    state.ground_coins[denom] = ground_amt - amount   # partial: leave the rest
                self._begin(state, denom, coin=True)
                # MegaMud hardcodes the get-currency verb; MajorMUD GET syntax
                # is "GET {Amount} {Currency}" (amount required). Ref §3.
                return f"get {amount} {denom}"
        # Pick up loot: everything (auto_get) or just the configured items
        # (get_items — name substring, case-insensitive; e.g. "black star key").
        want = [w.lower() for w in self._cfg.get_items]
        if self._cfg.auto_get or want:
            for name in list(state.ground_items):
                if name in self._ungettable:
                    continue
                needed = any(w in name.lower() for w in want)
                if not (self._cfg.auto_get or needed):
                    continue
                if not needed and not self._item_fits(state, name, cur):
                    continue            # too heavy -> skip (left on the ground), keep moving
                state.ground_items.remove(name)
                self._begin(state, name)
                return f"get {name}"
        return None

    def _item_fits(self, state: GameState, name: str, cur: int) -> bool:
        cap = self._cap(state, needed=False)
        if cap is None or self._item_db is None:
            return True                 # no weight data -> don't block the grab
        it = self._item_db.find(name)
        if it is None:
            return True                 # unknown item -> don't block
        return cur + it.weight <= cap

    def _coin_upgrade_drop(self, state: GameState, target_denom: str,
                           cur: int, cap: int, amount: int) -> str | None:
        """Drop the cheapest carried coin worth less than `target_denom` to free weight for
        it (MegaMud cash_upgrade_coins_decide). Optimistically reduce our load so the next
        turn picks up the better coin. Returns 'drop N <coin>' or None (disabled / nothing
        cheaper to sacrifice)."""
        if not self._cfg.drop_coins:
            return None
        target_val = WEALTH_RATES.get(target_denom, 0)
        carried = state.inventory.coins
        cheaper = [(WEALTH_RATES.get(d, 0), d, n) for d, n in carried.items()
                   if n > 0 and WEALTH_RATES.get(d, 0) < target_val]
        if not cheaper:
            return None
        _val, denom, count = min(cheaper)            # lowest unit value first
        overage = (cur + _coin_weight(amount)) - cap  # weight units to free
        # MegaMud: n = min(weight_to_free*3, held_count, amount_on_ground) — never drop more
        # cheap coins than the number of better coins actually available to pick up.
        n = min(count, max(1, overage) * 3, amount)   # 3 coins per weight unit
        if n <= 0:
            return None
        # Optimistically apply the drop so we don't re-drop before the inventory refreshes.
        new_count = count - n
        state.inventory.encumbrance_cur -= _coin_weight(count) - _coin_weight(new_count)
        if new_count > 0:
            carried[denom] = new_count
        else:
            carried.pop(denom, None)
        return f"drop {n} {denom}"

    def _begin(self, state: GameState, name: str, coin: bool = False) -> None:
        # NOTE: do NOT set inventory_dirty here — that lets the higher-priority
        # RefreshDecider preempt the GETTING task and fire "inv" before the
        # get's success/failure reply arrives (so the item is never marked
        # ungettable). The bot sets inventory_dirty on a SUCCESSFUL get instead.
        # `coin` marks a currency pickup so a transient failure never blacklists
        # the denomination (coins re-appear; only real items are ungettable).
        state.begin_task(TaskType.GETTING, priority=PRIO_ITEMS,
                         timeout_s=GET_TIMEOUT_S, payload={"item": name, "coin": coin},
                         now=self._now())
