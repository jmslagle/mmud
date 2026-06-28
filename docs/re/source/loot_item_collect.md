# `loot_item_collect` @ `0x409880`

Auto-loot/auto-cash decision: should we pick up this ground item or coin stack, and if so
issue the GET (preceded by `open` for a container). The **DontBeHeavy/DontBeMedium weight
cap is applied here — it gates PICKUP, not movement.**

State offsets: `current_weight = +0x31a8`, `max_weight = +0x31ac`, `encumbrance_level = +0x31b0`
(1=Light..3=Heavy, parsed from the server line — see `inventory_parse_response`),
`inv_count = +0x3178`, `inv_array = +0x317c`, flags `DontBeHeavy = +0x322c`,
`DontBeMedium = +0x3230`, `DropCoins = +0x3238`, coin "want" gates
`WantCopper/Silver/Gold/Plat/Runic = +0x3218/+0x321c/+0x3220/+0x3224/+0x3228`,
`AutoCash = +0x4ce4`, `AutoGet = +0x4ce8`.

```c
// bVar16 = item is NEEDED (path-required, required-for-cash, or AutoCash-below-target).
// iVar11 = weight this pickup adds:
//   coins:  (amount + 2) / 3        // ceil(amount/3); 3 coins per weight unit
//   items:  item_record[+0x6c]      // catalogued item weight

int max = state[+0x31ac];            // max weight
int cap = max;                       // effective cap starts at max
if (state[+0x322c] /*DontBeHeavy*/ && !needed) cap = (max * 0x43) / 100;   // 67%
if (state[+0x3230] /*DontBeMedium*/ && !needed) cap = (max * 0x21) / 100;  // 33%  (Medium wins)

if ( cap < state[+0x31a8] + item_weight        // current + add > cap
     || (state[+0x31a8] == cap && full && item_weight == 0) ) {
    // coin branch first tries to free room by dropping cheaper coins:
    if (is_coin && cash_upgrade_coins_decide(state, coin_rec, amount,
                                             (state[+0x31a8] - cap) + item_weight))
        return 1;                              // dropped lower coins; turn consumed
    status_log("Not getting %s because it would take us past our maximum encumberance", name);
    return 0;                                  // skip — do NOT pick up
}
// fits: send "g <name>"  (or "g <N> <name>" for a coin stack; "open <name>" first if container)
```

**Behaviour.** Caps how much we *pick up*: 67% of max with DontBeHeavy, 33% with DontBeMedium
(stricter wins); needed items ignore the reduction (still bounded by true max). An item/coin
that would push us over the cap is skipped (logged). There is **no** movement gate anywhere —
overweight movement is only the server's reactive `"You are too heavy to move"`, handled as a
blocked exit in `room_door_response_parse @0x426307`.

**Ported to.** `src/mmud/automation/items.py` — `GetDecider._cap` / `_item_fits` /
`_coin_weight` and the coin/item loops in `decide`. Movement is decoupled:
`TravelDecider.decide` no longer checks weight; `"You are too heavy to move"` is in
`bot._NAV_FAIL_RE` → `TravelDecider.on_move_failed`. See [`cash_upgrade_coins_decide`](cash_upgrade_coins_decide.md).
