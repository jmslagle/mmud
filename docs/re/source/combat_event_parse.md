# `combat_event_parse` @ `0x4176b0`

Per-line combat-event parser (called from `pattern_match_dispatch`). Handles monster
kills, player/party death, and the cast-counter resets. **There is no per-monster death
string** — the 210-byte MONSTERS.MD record has no death-message field (`name[31]@0x02`,
short-names `@0x34/0x39`, then id/flags/combat_rating/level/exp/alignment/hp — nothing
else). A kill is recognised by the **`You gain N experience.`** line, and the dying
monster is identified **by position (room-entity slot 0 = the pinned current target)**,
not by name and not by the death sentence.

**Game-state offsets**

| offset | meaning |
|---|---|
| `gs+0x1ed4` | room-entity count |
| `gs+0x1ee0` | room-entity ptr-array (slot 0 = pinned current target) |
| `gs+0x54dc` | current-target name |
| `gs+0x56ec` | "re-scan room" request flag |
| `gs+0x5368` | total xp · `gs+0x94f0` kill count |
| `gs+0x4d60..0x4d73` | cast counters (zeroed in the kill epilogue) |

**Decisive branches** (each matched per-line via `pattern_match_remove`):

```c
/* (1) Your kill — AUTHORITATIVE. "You gain " + " experience" */
if (match("You gain ") && find(" experience")) {
    n = atoi(after "You gain ");
    gs->xp(0x5368) += n;  gs->kills(0x94f0) += 1;
    combat_damage_stats_update();              /* clears cast counters + 0x9584 */
    room_entity_slot_remove(gs, 0);            /* <-- remove the PINNED target (slot 0) */
    str_copy(gs->target_name /*0x54dc*/, "");  /* clear current target */
    task_state_set(gs, 0);                      /* back to decide state */
    gs->rescan(0x56ec) = 1;                     /* re-evaluate room next cycle */
}

/* (2) Maxed character, no XP — same kill epilogue */
else if (match("You have progressed too far without training")) { /* ...same as (1)... */ }

/* (3) "<name> is dead." — does NOT remove a slot; just force a room re-scan */
else if (match(" is dead.")) {
    room_entity_flags_clear_seen(gs);
    gs->rescan(0x56ec) = 1;  task_state_set(gs, 0);
}

/* (4) "<name> drops to the ground!" — PLAYER/PARTY death, NOT a monster kill */
else if (match(" drops to the ground!")) {
    name = strncpy(before the phrase);
    if (name == gs->player_name /*0x5334*/) self_death_hangup();
    else if (name == gs->target_name)       /* current target */ ...;
    else party_member_remove(name);
}
```

Slot 0 is the current target because `room_entity_priority_pin @0x45a660` sets the
target's priority (`+8`) to 999 and `room_entity_priority_sort @0x45a390` bubble-sorts
descending. `room_entity_slot_remove @0x45a850` frees `array[0]`, shifts down, decrements
the count — **removal is by index 0, never by name**, so two same-named monsters are
handled correctly (it removes the one you were attacking). The separate by-name removal
(`room_entity_movement_parse @0x4589c0`) is for departures / `"You do not see "`.

## Behaviour (and the port)
- **`You gain N experience.`** is the authoritative kill → remove the current target,
  clear the target name, request a room re-scan. (Our `_parse_who_and_exp` already does
  this — it's the primary, correct mechanism.)
- **`You have progressed too far without training`** → also a kill (maxed, no XP).
- **`<name> is dead.`** → don't name-remove; force a re-read of `Also here:`.
- **`<name> drops to the ground!`** → player/party death, NOT a monster kill.
- The varied flavor death lines ("collapses without a sound", "falls to the ground, and
  is still") are **ignored** — do NOT build a generic death regex to match them.
- MegaMud parses per-line but its cast/melee *decision* runs on the AI tick reading the
  current slot 0 — so it never casts a target the exp line already cleared. Our per-line
  decide races the kill (casts on the damage line just before the exp line) — see
  docs/re/combat.md "decision cadence".

**Ported to:** `bot._parse_who_and_exp` (exp kill), `bot._parse_monster_removal`,
`room_parser` death/departure regexes. See [`../parsing.md`](../parsing.md).
