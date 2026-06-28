# `cash_upgrade_coins_decide` @ `0x409fc0`

When a higher-value coin stack won't fit under the pickup cap, drop the cheapest carried
coins (strictly cheaper than the target) to free weight for it. Gated by the `DropCoins`
flag. Called from the coin branch of [`loot_item_collect`](loot_item_collect.md).

State offsets: `max_weight = +0x31ac`, `DropCoins = +0x3238`. `currency_item_value_get`
returns a coin's unit value; currency records carry flag `0x8000000`.

```c
// param_3 = overage to free (weight units); param_4 = amount of the target coin we want.
if ( state[+0x3238] /*DropCoins*/ && state[+0x31ac] != 0
     && (target_val = currency_item_value_get(state, target_coin)) , param_4 > 0 ) {
  do {
    // scan inventory for the LOWEST unit-value currency whose value < target_val
    lowest = find_cheapest_currency_below(state, target_val);   // record flag 0x8000000
    if (lowest == -1) break;                                    // nothing cheaper to sacrifice
    int n = min(lowest.stackQty * 3, param_3, param_4);         // 3 coins per weight unit
    if (n > 0) {
      status_log("Dropping coins to get bigger currency");
      net_send("drop %d %s", n, lowest.name);
      // recompute remaining overage; loop to drop more / a next-cheapest coin if needed
    }
  } while (remaining_overage > 0);
  if (dropped_any) { state[+0x31ac] = 0; return 1; }   // mark weight stale -> retrigger pickup
}
return 0;                                                // disabled / nothing cheaper -> caller skips
```

**Behaviour.** Frees room for a better coin by dropping the cheapest cheaper coins
(`drop N <coin>`), never coins of equal/greater value, never more than needed. Marks weight
stale so the next pass re-evaluates and grabs the upgrade. If `DropCoins` is off or there's
no cheaper coin, returns 0 and the caller simply skips the pickup.

**Ported to.** `src/mmud/automation/items.py` — `GetDecider._coin_upgrade_drop` (cheapest-first
via `WEALTH_RATES`, optimistic local weight reduction so we don't re-drop before the inventory
refreshes, leaves the target coin on the ground for the next turn).
