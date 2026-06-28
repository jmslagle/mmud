# `loot_item_collect` @ `0x409880`

Auto-loot/auto-cash decision: should we pick up this ground item or coin stack, and if so
issue the GET (preceded by `open` for a container). The **DontBeHeavy/DontBeMedium weight
cap is applied here — it gates PICKUP, not movement.**

> Address note: this project's Ghidra DB names the routine `0x409880`; a second RE pass
> located the live loot decision at **`0x409a80`** (caller `loot_collect_decide @0x409980`,
> itself from `game_ai_do_something`). The algorithm below is identical either way.

State offsets: `current_weight = +0x31a8`, `max_weight = +0x31ac`, `encumbrance_level = +0x31b0`
(1=Light..3=Heavy, parsed from the server line — see `inventory_parse_response`),
`inv_count = +0x3178`, `inv_array = +0x317c`, flags `DontBeHeavy = +0x322c`,
`DontBeMedium = +0x3230`, `DropCoins = +0x3238`, coin "want" gates
`WantCopper/Silver/Gold/Plat/Runic = +0x3218/+0x321c/+0x3220/+0x3224/+0x3228`,
`AutoCash = +0x4ce4`, `AutoGet = +0x4ce8`. Funds: `current_funds = +0x3180` (carried
copper-equiv, recomputed by `item_get_result_parse @0x43e4e0`), `required_funds = +0x3188`.

**Pickup ORDER is highest-value-first.** The room-entity list is kept sorted by a priority
score (`room_entity_priority_sort @0x45a390`) — currency scores by unit value
(runic>plat>gold>silver>copper), monsters/players ahead of items — and `loot_collect_decide`
walks it front-to-back. So gold is always attempted before silver, regardless of the order
coins were noticed or dropped.

```c
// bVar16 = item is NEEDED: path-required (flag 0x1000000), matches the needed-item name
//   (+0x31b4), OR current_funds(+0x3180) < required_funds(+0x3188) for a currency item.
//   CRITICAL: required_funds(+0x3188) is a TRANSIENT travel-toll requirement — normally 0,
//   set only by travel_check_cash_requirement @0x42a5e0 while routing a cash-gated exit and
//   cleared on every room change. It is NOT the bank/hoard threshold (that is MinWealth
//   @+0x3244, [Cash] section). So coins are "needed"/cap-bypassing ONLY during a toll step;
//   normally they obey the DontBeHeavy/DontBeMedium cap like any item.
// iVar11 = weight this pickup adds:
//   coins:  (amount + 2) / 3        // ceil(amount/3); 3 coins per weight unit
//   items:  item_record[+0x6c]      // catalogued item weight

int max = state[+0x31ac];            // max weight
int cap = max;                       // effective cap starts at max
if (state[+0x322c] /*DontBeHeavy*/ && !needed) cap = (max * 0x43) / 100;   // 67%
if (state[+0x3230] /*DontBeMedium*/ && !needed) cap = (max * 0x21) / 100;  // 33%  (Medium wins)

if ( cap < state[+0x31a8] + item_weight        // current + add > cap
     || (state[+0x31a8] == cap && full && item_weight == 0) ) {
    if (is_coin) {
        // 1. try to free room by dropping cheaper coins for this better one:
        if (cash_upgrade_coins_decide(state, coin_rec, amount,
                                      (state[+0x31a8] - cap) + item_weight))
            return 1;                          // dropped lower coins; turn consumed
        // 2. else PARTIAL pickup — take only as many coins as fit:
        int fit_coins = (cap - state[+0x31a8]) * 3;   // 3 coins per weight unit
        amount = min(amount, fit_coins);
        item_weight = amount / 3;
    }
    if (amount < 1 || cap < state[+0x31a8] + item_weight) {
        status_log("Not getting %s because it would take us past our maximum encumberance", name);
        return 0;                              // nothing fits — skip, do NOT pick up
    }
}
// fits: send "g <N> <name>" for a coin stack (partial amount), "g <name>" / "open" for items
```

**Behaviour.** Caps how much we *pick up*: 67% of max with DontBeHeavy, 33% with DontBeMedium
(stricter wins); needed items ignore the reduction (still bounded by true max). Highest-value
coins are attempted first; a coin stack that won't fully fit triggers a DropCoins upgrade and
otherwise a **partial** grab of what fits (items just skip). There is **no** movement gate —
overweight movement is only the server's reactive `"You are too heavy to move"`, handled as a
blocked exit in `room_door_response_parse @0x426307`.

**Ported to.** `src/mmud/automation/items.py` — `GetDecider._cap` / `_item_fits` /
`_coin_weight` and the coin/item loops in `decide` (value-descending coin order + partial
pickup; coins are NOT bypassed by `max_wealth`). Movement is decoupled: `TravelDecider.decide`
no longer checks weight; `"You are too heavy to move"` is in `bot._NAV_FAIL_RE` →
`TravelDecider.on_move_failed`. See [`cash_upgrade_coins_decide`](cash_upgrade_coins_decide.md).
