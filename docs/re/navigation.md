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
into `RouteStep`s. Per-step destination hash still confirms position as we go. Real
Bank→CRY1 = 29 steps; MAGS→CRY1 = 23. Used by `LoopRunner` approach and
`navigate_to_room` (goto). The hash BFS (`RoomGraph.find_path`) is retired for routing.

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

- **Broad seen-set.** `on_arrival` gets `seen_hexes = {room_id(line) for line in
  room_block}` — every block line (title + each description line) is hashed, all
  sharing the room's exit-bits, so a long description yields ~25 candidate hashes.
  This is the collision amplifier. (MegaMud uses ONE id; narrowing us to the title
  line is the open follow-up.)
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

## NPC look filter
A proper-named "Also here" entry that is a catalogued monster (`monster_db.find` hit,
e.g. "Lady Sentara", kill-type 2) is an NPC, not a player → tracked as a
non-attackable sighting, never looked-at/spied. Mirrors `room_entity_classify_all`.

## Open follow-ups
- **One room id from the title line** instead of hashing every block line (~25
  candidates) — the highest-leverage fix; aligns us with MegaMud and sharply cuts
  collisions, improving both travel and goto start detection.
- Port MegaMud's ±1 peek, 3-mismatch counter + full-path id search, "Lost!" stop, and
  `.MP` self-correction.
- Full 32-bit exit-hash room lookup needs the upper base-id source (`gs+0x2e9c`); this
  server sends no "In room:" id line.
