# Plan: B1 — finish the one-id path-follow (±1 peek, miss-counter, true Lost!)

## Context

CAVWLOOP grinds correctly now (Fix A killed the permanent false-SJLM relocate cycle), but in
the dense identical-room cave ("Stone Tunnel"/"Dark Cavern", all sharing a title hash, differing
only by exit bits) the loop cursor still **drifts off-by-one**, then a subsequent move is invalid
("no exit"/"bad direction") → the bot goes **"lost → wandering → re-route"**. Live evidence
(routing #3, clean log): `2` `lost (bad direction) -> wandering` events + `3` `off-route ->
relocate: Routing N steps` re-routes in one approach; `0` SJLM false-relocates (Fix A holds).
It converges via re-anchoring on the next ROOMS.MD-named room, but it's not a clean traversal.

MegaMud avoids this with a conservative one-id follow (`path_follow_step_decide @0x405b60`,
`path_find_current_step @0x42bf40`, RE'd in `docs/re/navigation.md:84-108`): position is ONE
room id; a single mismatch only bumps a miss counter (`state+0x152d`); it does a **±1 peek**
(cursor±1 exact-id match) for a missed/extra room; a **full path search only after 3 misses**
("Resynced from path step %d to %d"); if the id is found nowhere → **Lost! STOP** (it does NOT
blind-wander). Wildcards `0x99999999`/`0xffffffff` skip matching.

We implement tactics 1-2 (advance-one-per-arrival, no eager hash-jump) + a confident-name
re-anchor; **not ported:** the ±1 peek, the 3-miss counter, and a real id-based Lost stop. The
goal: cave laps traverse cleanly (no per-step lost→wander→re-route churn).

## Files

- `src/mmud/automation/travel.py` — `TravelDecider.on_arrival` (~212-291), `decide`, `set_route`,
  the `_MAX_WANDER` wander give-up.
- `src/mmud/automation/loop_runner.py` — `recover()` (~144), `_giveup()`, `_MAX_WANDER`.
- `src/mmud/bot.py` — `_parse_exits` already narrows to the title-coloured `seen_hexes` (Fix A
  groundwork); `_handle_nav_failure`/`_parse_nav_failure` → `loop_runner.recover()` (the
  "lost (bad direction)" path); `_maybe_relocate`.
- Tests: `tests/test_travel.py` (the existing on_arrival/redisplay/resync tests are the
  regression guard — keep them green).

## Approach (incremental, TDD; keep every existing test_travel green between steps)

### Step 1 — single-id arrivals (finish title-colour narrowing)
Confirm `_parse_exits` always passes the title-coloured single id as `seen_hexes` when the title
colour is known (Fix A already gates confident matches on it). Where the title colour isn't known
yet, keep the block-set fallback. Net: `on_arrival` reasons over ONE id per room in the cave, not
a colliding set. *Test:* arrivals in a learned-colour area produce a 1-element `seen_hexes`.

### Step 2 — ±1 peek before the optimistic advance  (the core fix)
In `on_arrival`, when `on_track` is empty and it's not a redisplay, BEFORE the optimistic advance
(`current_hex = step.chosen; cursor += 1`), peek:
- if `seen_hexes` ⊇ `steps[cursor+1].expect` → we overshot one room: advance cursor by **2**,
  reset the miss counter (we're re-synced one ahead).
- elif `seen_hexes` ⊇ `steps[cursor-1].expect` → we under-shot / re-displayed the prior room:
  do NOT advance (stay), reset miss counter.
- else → it's a genuine mismatch (Step 3).
*Tests:* a route where the fed arrival matches cursor+1 → cursor jumps +2, no lost; matches
cursor-1 → cursor holds; on-track still advances +1 (existing tests).

### Step 3 — 3-miss counter + true Lost! (replace the eager lost→wander)
Add `self._misses` (init in `__init__`, reset to 0 in `set_route` and on any on_track / peek /
confident hit). On a genuine mismatch (Step 2 "else"): increment `self._misses`; if `> 2` do the
existing optimistic advance AND post a `TravelLost`-style signal (or set a flag) so the bot can
STOP rather than wander. Wire `bot._handle_nav_failure` so a loop desync past the miss threshold
calls `loop_runner.stop()` + a clear "Lost!" status instead of `recover()`/wander (MegaMud doesn't
blind-wander — `navigation.md:96-108`). Keep a bounded wander only as the last resort if
configured. *Tests:* >3 consecutive non-matching arrivals → Lost!/stop fires, cursor stops
marching; a single miss does NOT (no premature lost).

### Step 4 — make the wander give-up cumulative (defense-in-depth)
In `loop_runner`, track re-engage attempts since the last completed lap (reset when `travel.lap`
increases); exceed K (3-5) → `_giveup()` instead of re-arming. Closes the hole where `set_route`
resets `_wander_moves=0` so the maze never trips `_MAX_WANDER`. *Test:* repeated collision
re-engages → giveup after K, not never.

## Verification

- `python -m pytest -q` green (esp. all `tests/test_travel.py` — the regression guard).
- Live: restart raist on CAVWLOOP with a clean log; over one approach+lap expect **0**
  `lost (bad direction)` and **0** mid-run re-routes through the cave (vs 2+3 today), the cursor
  advancing monotonically, and a clean `Looping CAVWLOOP lap 1` transition. SJLM false-relocate
  stays 0 (don't regress Fix A).

## Risk / notes
- The travel cursor is the single most delicate nav component — do this in its own focused
  session, one step at a time, re-running `test_travel.py` after each. Do NOT combine with other
  changes. The ±1 peek must not fire on hash COLLISIONS that aren't actually cursor±1 (gate on the
  single title id from Step 1, not the block set).
