# Navigation — room id, routing, and path following

## Room id = the 32-bit hash (the keystone)

`ROOMS.MD` `HexID1` is MegaMud's 32-bit **room id**. It is NOT derivable from the
abbreviated room label — `ROOMS.MD` stores short names ("Sovereign St Nth") while the
server sends full titles ("Sovereign Street, Northern End"), so name-only detection
fails for most rooms.

Ghidra-confirmed algorithm (`room_title_parse @0x475e20`, `room_exit_parse @0x425290`):

```
room_id = ((title_hash & 0xFFF) << 20) | exit_bits
title_hash = Σ (i+1) * ord(ch)   over the LIVE room title, 1-based index, 32-bit
exit_bits  = 20-bit obvious-exits field: 2 bits per direction in order
             N,S,E,W,NE,NW,SE,SW,U,D   (open=1, closed=2)
             one fixup: 0xB7200050 -> 0xB7200055
```

- Implemented in `exits_parser.title_hash` / `room_id` + `RoomParser.detect_room_from_block`
  (hashes each recent display line against the exits and matches `ROOMS.MD` HexID1 —
  self-validating). The bot resolves the room on the "Obvious exits:" line and sets
  `current_hex`.
- Verified vs `ROOMS.MD` bytes (Bank `D4E00091`, Sovereign `89C00055`) and live rooms.
- `HexID2` is **room flags**, not a hash.
- **`title_hash` is only 12 bits** (`& 0xFFF`), so the room id collides heavily across
  the ~4423 corpus rooms (only ~525 are in `ROOMS.MD`). The 543 ids actually in
  `ROOMS.MD` happen to be unique, but live rooms outside it collide. This collision is
  the root cause of nearly every navigation problem below.

## Routing: use the code graph, NOT a hash BFS

BFS over the (room-id, command) graph invents unwalkable shortcuts because one hash =
many rooms (e.g. `EB400050` 'w' → 5 different rooms; 2373 multi-dest edges). It once
produced a bogus 18-step Bank→Crypt that diverged at the first collision.

**Fix:** `navigation/code_route.find_code_route(from_code, to_code, paths, rooms)`
chains the recorded `.MP` paths over the **room-CODE** graph (1190 paths as
`from_code → to_code` edges; each leg is a real walked sequence), concatenating legs
into `RouteSteps`. Per-step destination hash still confirms position as we go. Real
Bank→CRY1 = 29 steps; MAGS→CRY1 = 23. Used by `LoopRunner` approach and
`navigate_to_room` (goto). The hash BFS (`RoomGraph.find_path`) is retired for routing.

**Weight by STEPS, not legs (2026-06-26).** `find_code_route` originally did a plain
BFS minimising the number of *legs* (named-room hops) — so it chained a few enormous
legs (River St → Pier → Silver River → Dragon's Teeth → …) to reach the slum-side
Orc Mansion (`ORCM`), a ~150-step detour around a ~65-step slum walk (STSQ → SOVN →
SOAK → SNOB → SLMC → SLMG → SLMW → ORCM). Now it's **Dijkstra weighted by leg step
count**, so it picks the fewest-*moves* route.

**Item-gated legs are excluded from auto-routing (2026-06-26).** The `.MP` summary
line carries a **required-item** field (field 5: `from_hex:to_hex:count:-1:0:ITEM::`).
92/1198 legs need an item — boats (`wooden skiff`), keys to locked zones, `climbing
harness`, `rope and grapple`, `swamp boots`, `potion of levitation`, `room ticket`,
`waterskin`, … The river route to ORCM used `BOAT→ISLB` which needs the **wooden
skiff** — crossing without it nearly drowned a low-level char. We don't model
carrying/using transport items, so `GamePath.requires` is parsed and `build_code_edges`
**skips any leg with `requires` UNLESS the bot holds that item** — land routes by
default, item legs unlocked when carried. (Keyword-gated steps like
`[use black star key e]` live inside loop BODIES, which are self-loops and unaffected.)

**Held-item routing + missing-item diagnosis (2026-06-26).** A blanket skip made
item-*only*-reachable areas permanently unreachable: the **Cave Worm Area (CAVW)** has
exactly one walkable entrance, `BHDC→CAVW`, gated by **rope and grapple** (the other
candidate, `OBCW→CAVW`, is itself unreachable). Sitting in the Bank (SBNK) and starting
the CAVW loop, the loop runner found no route → fell into the wander branch reporting a
misleading "Position unknown" and wandered forever. Fixes:
- `build_code_edges(paths, held_items=…)` and `find_code_route(…, held_items=…)` include
  an item leg when `held_items` covers its item (lenient match: lowercased, strip a
  trailing `*` marker + leading article, substring either way — so `rope and grapple`
  matches `a coil of rope and grapple`). The bot passes `inventory.carried | worn`.
- `missing_route_items(from, to, paths, held_items=…)` → `[]` reachable now, `[items]`
  the gates on the **fewest-gate** route (gate-penalised Dijkstra, so it reports only
  what's truly needed — e.g. `['rope and grapple']`, not a black-star-key shortcut the
  user can skip), `None` if unreachable even with every item.
- `LoopRunner.start()` (and `navigate_to_room`): when a KNOWN room has no route but the
  best route is item-gated, it **stops and names the item** ("Can't reach CAVW from
  SBNK: need rope and grapple") via `on_lost(reason)` → objective, instead of wandering.

`navigate_to_room` builds the route from `state.current_room` (the last
**name-detected** room). If the bot is standing in an undetected room, that start is
**stale** — see "Stale start position" below.

## How MegaMud follows a path (and avoids getting lost in identical-room chains)

`path_follow_step_decide @0x405b60`, `path_find_current_step @0x42bf40`. Position is
**one** current room id (`state+0xba6`), compared to each step's expected id.

1. **Follow the recorded command sequence step-by-step.** One id per room.
2. **Tolerate mismatches.** A single id mismatch does nothing but bump a counter
   (`state+0x152d`). The first mismatch just waits — it does **not** resync.
3. **Quick ±1 realign.** Peek the next step (cursor +1) and previous step (cursor −1)
   for an exact id match — handles a missed/extra room.
4. **Full resync only after 3 mismatches** (`0x152d > 2`): `path_find_current_step`
   searches the whole active path for the current id (near the current step first),
   then a secondary path. Logs "Resynced from path step %d to %d".
5. **If found nowhere → "Lost!"** (`state+0x1588=1`, status `0x11`) and STOP. It does
   not blindly wander.
6. **Self-corrects path data.** Uncertain steps (flags `0x80`/`0x100`) get their id
   overwritten with the observed one, and the corrected `.MP` is written back to disk
   ("Path step updated"). "Uncertain room" check: if the move direction isn't even a
   valid exit, escalate.
7. **Wildcards.** Id `0x99999999` = "don't match, just follow the command";
   `0xffffffff` = uncertain/any. `sys_goto_*` special ids teleport-route to towns.

The key takeaway: MegaMud is **conservative** — it follows the commands and only
relocates once genuinely lost. Eager resync-on-any-hash-match is what desyncs in
chains of identical rooms.

## Our travel decider (`automation/travel.py`) — what we mirror

We advance **one step per arrival** (follow the command) and re-anchor only on a
**confidently name-detected** room. The hard-won rules, each a fixed bug:

- **Seen-set narrowed (2026-06-26).** `on_arrival` gets `seen_hexes = {room_id(line)
  for line in room_block}`. The bug: `_room_block` was the last **30 lines of ALL
  output** (combat, loot, async), only reset at the exits line — so after a fight it
  held ~27 garbage lines → ~27 candidate hashes → false route/wander matches. Fix:
  reset `_room_block` at each **prompt** (`[HP=..]:` — a turn boundary), so it holds
  only the current room display (title + items + also-here) → ~3-5 hashes. This is
  the practical version of MegaMud's "one id per room" (`room_title_parse @0x475e20`
  computes `title_hash<<20` from the single title line, identified by its bold/colour
  attribute `state+0x7deb==0x0e`). NOTE: genuinely identical rooms (same title AND
  same exits — e.g. the `2B000055` graveyard maze rooms) still collide by design;
  MegaMud has the same limit and relies on the command sequence + the give-up stop.
- **No eager hash-jump (chains).** We do NOT resync the cursor to a nearby step on a
  bare hash match. In a run of identical rooms (Temple St, the cemetery), a later
  step's dest hash routinely appears in an earlier room's candidate set; jumping on it
  desynced the cursor and turned the route early into a dead end. Advance one step;
  a real dead-end surfaces as a nav failure ("no exit") → `on_move_failed` → blocked.
- **Confident re-anchor.** `on_arrival(..., confident_hex=)` — the bot passes the hex
  of a `ROOMS.MD` name-detected room (high confidence). Travel resyncs FORWARD to the
  matching waypoint even far ahead. This recovers from a stale start and skips
  un-needed steps; named anchors (STSQ, SADG, WALT) act as resync points. Forward-only
  preserves the loop guard.
- **Departure re-display guard (one-shot).** After a move, the room being LEFT can
  re-display its "Obvious exits" (the auto-sneak prefix or an idle refresh racing the
  move). Treated as an arrival, it advanced the cursor and desynced the whole route.
  Recognise it by the **departure room's hash SET** (`_from_seen`, captured at
  `decide` from `state.last_room_hexes`) — not just `current_hex`, which is often
  stale at route start — and ignore it once.
- **Optimistic advance.** An arrival matching no known step is trusted as a successful
  move (advance via the planned dest), since most live rooms aren't in the corpus.
- **±1 peek (B1, 2026-06-28).** Before the optimistic advance, when the single
  (title-narrowed) id is neither on-track nor a confident anchor, peek the adjacent
  steps: if it equals **step cursor+1**'s expected id (subset of `seen_hexes`) we
  overshot one room → advance the cursor by **2**; if it equals **step cursor−1**'s id
  we under-shot / the prior room re-displayed past the one-shot guard → **hold**. Gated
  on an exact-subset match of the narrowed id (not the broad block set) so a far-off
  colliding dest can't false-fire. Mirrors `path_follow_step_decide`'s quick realign.
- **3-miss counter + true Lost! (B1, 2026-06-28).** A genuine mismatch (non-empty
  `seen_hexes`, not on-track / peek / confident) bumps `_misses` (MegaMud `state+0x152d`);
  a SINGLE mismatch only counts — it does not relocate. After **3** (`> 2`) we set
  `travel.lost` and post `TravelLost`; the bot (`_handle_travel_lost`) **STOPs** the
  loop with a "Lost!" status rather than blind-wandering (MegaMud doesn't). An EMPTY
  `seen_hexes` ("no id this room") follows the command without counting a miss. Misses
  reset on any on-track / peek-hit / confident hit and in `set_route`.
- **Cumulative re-engage give-up (B1, 2026-06-28).** `LoopRunner.recover()` counts
  re-engage attempts since the last completed lap (`_MAX_REENGAGE`); a changed
  `travel.lap` resets the budget. Closes the hole where `set_route` zeroes the
  per-wander move counter so a maze that desyncs every approach re-arms forever and
  never trips `_MAX_WANDER`.

## Stale start position from undetected rooms (the Temple→WALT bug)

It IS stock MajorMUD — the map and `.MP` corpus match; there is no "phantom detour."
The real bug: the bot couldn't identify the room it was standing in. The Temple/Town
Square street rooms log `arrive room=?` (detect fails — live "Temple Street" doesn't
match `ROOMS.MD`), while Town Square logs `arrive room=STSQ`. After walking ~5 rooms
east of Temple Entrance into an undetected "Temple Street", `current_room` stayed
stale at `STMP`, so `:goto WALT` built the route FROM `STMP`. `STMPSTSQ.MP` is correct
(`STMP -e×7-> STSQ`), but from the bot's true spot (~2 west of Town Square) the 7-east
leg overshot past Town Square → dead end. The confident-resync mitigation snaps the
bot onto the route at the detectable Town Square. The deeper fix is detecting
"Temple Street"-type rooms (the abbreviated-name detect gap).

## Loop start from any room (`LoopRunner.start()`)
1. **On the loop** → resume/finish from the current index (`set_route(start_at=idx)`;
   later laps restart at `loop_from`).
2. **Known position off the loop** → `find_path(current → loop_start)`, prepended as a
   one-time approach (`set_route(loop_from=len(approach))`).
3. **Unknown / no route** → WANDER: `set_wander(loop_hexes, on_reach)` picks an exit
   each arrival (no immediate U-turn) until the arrived hash is a loop room, then
   engages. Mirrors how MegaMud wanders onto its loop.

A bad direction ("no exit") while looping = desync → drop the route and
`LoopRunner.recover()` wanders until back on a loop room. The decision engine blocks
deciders at priority ≥ an active task's priority, so a stuck task freezes travel.

**Relocate on any KNOWN off-route room — goto AND loop (2026-06-26).** Recovery used
to be loop-wander-only. Now `bot._maybe_relocate(code, hex)` runs after every
`on_arrival`: if travel is active and we confidently name-detect a ROOMS.MD room that
is NOT on the planned route, we re-path from there to the destination —
`LoopRunner.relocate(code)` for a loop (resume if on it, else fresh approach), or
`navigate_to_room(dest)` for a goto. This subsumes the wander case (a wander has no
route, so any known room re-paths). An anti-thrash guard (`_relocate_from`) avoids
re-pathing twice at the same hex; `set_route` cancels any active wander (decide()
checks wander first). The `_MAX_WANDER` give-up is still the backstop when no known
room is found.

**The graveyard trap (lost for hours, bounded 2026-06-26).** CRY1's approach crosses
the Graveyard Bridge to the crypt. The graveyard is a maze of identically-titled
rooms whose ids collide on `2B000055` — which is also a CRY1 approach step. So when
the bot desyncs at the crypt entrance (the cursor was one step behind: the room had
exits *south, down* but the step said `n` → "no exit") and drops to wander, the
graveyard rooms **false-match** the loop's `2B000055` target, so it "relocates",
re-engages, fails, and re-wanders — for SIX HOURS in one run, because the optimistic
advance also lets it "complete" fake laps without ever detecting CRY1. Mitigation:
`TravelDecider.set_wander(limit=, on_giveup=)` bounds wander to `_MAX_WANDER` (40)
moves; on exceeding it `LoopRunner._giveup()` stops the loop and the bot's
`on_lost` logs/flags it ("Lost (gave up …)") — MegaMud's "Lost!" stop. This is a
SAFETY NET, not a cure: reliably traversing the graveyard needs the one-room-id fix
(below) so the cursor doesn't desync and the wander doesn't false-match collisions.

**Phantom cross-zone relocate guard (`bot._relocate_is_phantom`, 2026-06-28).** The
relocate above blindly trusted `confident_hex`, but `confident_hex` comes from
`detect_room_from_block`, which hashes EVERY room-display line and matches the first id
in ROOMS.MD. A STRAY non-title line can hash-collide with a far-zone room: while looping
the Black House warren (near CAVW), a warren room hit DVEA's full id `F4301140` ("Dusty
Village, Eastern Entrance" in the Scorching Desert) — both share the low-20 exit pattern
`...01140`, and a description/also-here line's title-hash low-12 landed on `0xF43`. On
"Realm of Legends" almost no live room is in ROOMS.MD by name, so `_title_color` is never
confidently learned and the title-colour gate (bot.py `_parse_exits`) is skipped, letting
the collision through. The bot then relocated its position to DVEA and routed **226 steps
(DVEA→CAVW)** through the desert (loop body is only 80). Fix: before acting on a relocate,
reject it if the re-route is implausibly long. A single off-route arrival means we moved
ONE room, so `len(code_route(detected, target)) > baseline*2 + 12` (baseline = loop body
length for a loop, remaining-route length for a goto) is a phantom collision, not a real
teleport — keep following the recorded path instead. Short legitimate drifts and
equal/shorter re-routes still relocate. Tests: `test_phantom_crosszone_relocate_is_rejected`,
`test_legit_short_relocate_still_repaths` (tests/test_bot.py).

## NPC look filter
A proper-named "Also here" entry that is a catalogued monster (`monster_db.find` hit,
e.g. "Lady Sentara", kill-type 2) is an NPC, not a player → tracked as a
non-attackable sighting, never looked-at/spied. Mirrors `room_entity_classify_all`.

## Doors, locks, and traps

**Bashable-vs-locked is NOT stored in any data file — it's discovered at runtime.**
What the data *does* carry:

- **`.MP` step flags** (the middle field of `HexID:flags:command`, a 16-bit hex value)
  are NAVIGATION/exit flags, decoded by `path_follow_step_decide` / `path_exit_attempt`:
  `0x02` stop-before-enter, `0x04` rest-before, `0x08` sneak-only, `0x10` rest-after,
  `0x40` notify, `0x80` uncertain (runtime), `0x100` room-light, **`0x200` TRAP**.
  So a *trapped* exit IS marked in the path data (bit `0x200`); a *locked* door is not.
- **Keyword exits**: a `[keyword]` annotation in the command field handles exits that
  need a special command (e.g. `say password`, comma-separated multi-commands).
- **Live exit state** per direction lives at `gs+0x2ea0 + dir*4`: `5`=unlocked (needs
  `open`), `2`/`0`=closed/locked, `3`=now-open. It's seeded from the room's "Obvious
  exits" (the `open=1`/`closed=2` exit-bits) and updated by `room_door_response_parse`.

### MegaMud's escalation (`path_exit_attempt @0x406920` — the decision point)
1. **Trap** (step flag `0x200` AND CanDisarmTraps `gs+0x379c`): if not yet searched →
   `search [dir]` (task SEARCHING); if searched and under max → `disarm trap [dir]`.
2. **Unlocked (state 5)** or force-open → `open [dir]` (task OPENING).
3. **Closed/locked (state 2 or 0)**: if CanPickLocks (`gs+0x3798`) and pick attempts
   ≤ pick_max → `pi [dir]` (pick lock); **otherwise → `bash [dir]`**.
4. **Keyword** exits issue the annotated command(s).

`room_door_response_parse @0x425fe0` turns the result back into state: an `open` that
returns "is locked" → mark exit `state=2` (so the next attempt picks/bashes); "is now
open"/"was already open" → proceed; "is closed" → retry/undo; and a wall of
hard-block messages ("You may not enter", "not healthy enough", "too heavy", "not
permitted", "too good/evil to go", "no room ticket", "shimmering wall", "heat too
intense") → **path blocked, stop** (it does not bash through these).

### Which key? It's recorded in the path (keyword exit)
You don't compute the key — the `.MP` step's `[keyword]` annotation IS the unlock
command. The CAVW (Cave Worm) loop's Black House door is recorded as
`e[use black star key e]`: the path recorder captured `use black star key e` as the
exit command. We carry it via `expand_annotated` (`use black star key e`, then `e`).
In-game, `use <key> <dir>` auto-picks the key from inventory, so there's no key→door
table to maintain.

**Unlock ≠ open.** After `use black star key e` → "You successfully unlocked the
door.", the door is UNLOCKED but still CLOSED, so the move fails with **"There is a
closed door in that direction!"** — you then need `open e`, then the move. (Live log
23:29: unlock → closed-door block → `open e` → "The door is now open.")

### Our port (`automation/doors.py` `DoorMonitor`)
Reactive open→pick→bash, driven by the same response text: a blocked move →
`open [dir]` first → if it won't open, `pick` (if `can_pick_locks` and under
`pick_max`) else `bash` (if `bash_doors` and under `bash_max`) else give up. Gates and
doors share handling (`_OBSTACLE` = door|gate|portcullis|grate|drawbridge). Keyword
exits are handled in travel via `expand_annotated` (e.g. `w[search w]`).

Fixed bugs (2026-06-25):
- `DoorMonitor` now matches the move-blocked form **"There is a closed door in that
  direction!"** (`closed <obstacle> in that direction`), not just "X is closed" — that
  phrasing is what a keyed-but-still-closed door produces, and we were ignoring it.
- `_handle_doors` re-issues **only the move** after opening, not `travel.retry_current()`
  — the latter re-ran the whole annotated step and **burned another key** on an
  already-unlocked door (the live log shows repeated `use black star key e`).

**Remaining gap:** we parse `.MP` steps as `(hex_id, command)` only — we **discard the
flags field**, so we don't pre-`search`/`disarm` trapped exits (`0x200`) from path
data; we'd only react if the server reports a trap after we trip it. (We also ignore
the rest/sneak/stop step flags, though those come from config/other logic.) Wiring the
flag field through `PathStep`/`RouteStep` would let us match MegaMud's proactive trap
handling — see open follow-ups.

**Single title id by colour (2026-06-26).** The final step toward MegaMud's one-id-
per-room (`room_title_parse @0x475e20` keys on the title's attribute `state+0x7deb`).
`parser/ansi.line_fg(raw)` returns each line's fg colour key (e.g. `1;36`). The bot
stores `(line, colour)` in `_room_block`, **auto-learns** the room-title colour from a
confidently name-detected room (the block line whose hash == the detected id is the
title), then narrows `seen_hexes` to just the title-coloured line's id. Falls back to
the prompt-trimmed block set until learned or if no title-coloured line is present.
(Server-agnostic: the title colour is learned, not the hardcoded `0x0e`.) Still won't
distinguish genuinely-identical rooms — a design limit.

## Open follow-ups
- Port MegaMud's ±1 peek, 3-mismatch counter + full-path id search, "Lost!" stop, and
  `.MP` self-correction.
- Full 32-bit exit-hash room lookup needs the upper base-id source (`gs+0x2e9c`); this
  server sends no "In room:" id line.
