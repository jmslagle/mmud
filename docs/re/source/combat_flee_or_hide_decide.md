# `combat_flee_or_hide_decide` @ `0x407f70`

The per-tick combat driver (misnamed — it does flee/hide/backstab **and** the MAIN
attack-spell cast-vs-melee decision). The Mult/Pre attack slots are decided by
`combat_spell_select_and_cast_type1 @0x409350` (state 9) and `_type2 @0x409600`
(state 10), both called from here.

**Game-state offsets**

| offset | meaning |
|---|---|
| `gs+0x5470` | task_state (`0xb`=main-attack cast, `0xd`=melee) |
| `gs+0x54dc` | current target name |
| `gs+0x5390` / `gs+0x5398` | cur_mana / max_mana |
| `gs+0x3794` | `ManaAttack%` (main mana floor, integer percent) |
| `gs+0x4d74` | `MaxCastCnt` (may be overridden per-monster from monster_rec`+0x44`) |
| `gs+0x4d70` | **main cast counter** (incremented per landed cast; RESET PER KILL) |
| `gs+0x4d78` | `AttMaxDmg` (cumulative-cast-damage cap) |
| `gs+0x9584` | cast-damage accumulator (RESET PER KILL with the counter) |
| `gs+0x519d` | melee command prefix (`"a"` / `"attack"`) |
| `gs+0x5648` | "need to act" flag (set on Combat Engaged / combat events) |

Counters **increment** in `combat_hit_result_parse @0x4191b0` (per landed cast, by slot).
Counters **reset** in `combat_event_parse @0x4176b0`:
- on a **KILL** (both `"X drops to the ground"` and `"You gain N experience"` branches):
  `gs+0x4d70 = 0` (main), `gs+0x4d6c = 0` (pre), `combat_damage_stats_update()` clears
  `gs+0x9584`. It **does NOT** touch `gs+0x4d68` (Mult) — that one is per-room.
- also zeroed on room move (`path_move_execute @0x40718c`) and room refresh
  (`ai_room_refresh_trigger @0x407dae`).
- **NOT** reset by "Combat Engaged" / "Combat Off".

```c
int combat_flee_or_hide_decide(GameState *gs) {
    /* ... flee / hide / backstab handling omitted ... */
    int max_cast = gs->MaxCastCnt;                 /* 0x4d74, or monster_rec[+0x44] */

    /* Already in main-attack cast state: keep casting only while ALL hold. */
    if (gs->task_state /*0x5470*/ == 0xb) {
        if (gs->main_cast_count /*0x4d70*/ < max_cast
            && gs->cast_dmg_accum /*0x9584*/ < gs->AttMaxDmg /*0x4d78*/
            && (gs->ManaAttack /*0x3794*/ * gs->max_mana /*0x5398*/) / 100
                   <= gs->cur_mana /*0x5390*/) {
            return 1;                               /* still casting this round; wait */
        }
        if (max_cast <= gs->main_cast_count          /* hit a cap -> melee */
            || gs->AttMaxDmg <= gs->cast_dmg_accum) {
            debug_status_log(gs, "maximum attack ...");
            goto MELEE;                             /* LAB_00408d60 */
        }
    }

    /* Mana floor — a per-round FLOOR recomputed every tick (NOT a latch): casting
     * resumes automatically once mana recovers above the floor. */
    if (gs->cur_mana < (gs->ManaAttack * gs->max_mana) / 100) {
        debug_status_log(gs, "Attacking because Mana/Kai too low ...");
        goto MELEE;
    } else {
        combat_spell_cast(gs, gs->AttackSpl, gs->target);   /* "fjet <target>" */
        task_state_set(gs, 0xb);
        return 1;
    }

MELEE: /* re-issued every action tick (and on each new target), gated by gs+0x5648;
        * leans on the server's auto-combat for round-to-round swings. */
    wsprintfA(buf, "%s %s", gs->melee_prefix /*0x519d*/, gs->target /*0x54dc*/);
    net_buffer_receive(gs, buf);                    /* sends e.g. "a <target>" */
    task_state_set(gs, 0xd);
    return 1;
}
```

## Behaviour
- Cast the main attack spell while `count < MaxCastCnt` **AND** `accumDmg < AttMaxDmg`
  **AND** `mana >= ManaAttack% * maxMana / 100`; otherwise melee that round.
- The cast counter + damage accumulator reset on **every KILL** (and room move/refresh),
  so MegaMud re-casts up to `MaxCastCnt` against **each new monster** — not `MaxCastCnt`
  total per room. The Mult-slot counter (`0x4d68`) is the only per-room one.
- `ManaAttack%` is a floor, not a latch: casting resumes when mana recovers.
- Melee is re-issued each action tick and on each new target (server auto-combat does the
  per-round swings).

## Flee / run (same function)

Before the cast/melee logic, this function also decides to RUN. **It never sends the
MajorMUD `flee` verb and there is no recall.**

```c
/* RUN trigger: arm the room counter ONCE when HP (or Mana) drops below the run %. */
if (gs->cur_hp/*0x5384*/ < gs->MaxHP/*0x538c*/ * gs->HpRun/*0x3768*/ / 100
    && gs->run_counter/*0x54b8*/ == 0 && gs->RunRooms/*0x54bc*/ > 0) {
    if (gs->break_b4_running/*0x3a20*/) net_buffer_receive(gs, "break\r");
    gs->run_counter = gs->RunRooms;        /* default 4 */
    debug_status_log(gs, "Running away because HP's are too low");
}
/* (identical for Mana: cur_mana 0x5390 < MaxMana 0x5398 * ManaRun 0x3784 / 100) */
```

The move itself is issued later by `navigation_step_decide @0x405290`:
`roam_random_exit_select @0x425900` picks a random allowed exit avoiding
`direction_get_opposite(last_dir/*0x5478*/)`, or — if `RunBackwards/*0x3a1c*/` —
retraces the path-step history (`path_step_from_history`). `path_move_execute @0x407010`
sends `"%s\r"` (the bare direction) and does `run_counter--`. `combat_rest_decide
@0x40b380` returns 0 (NO rest) while `run_counter > 0`; at 0 it sends `rest\r` and
recovers to `HpRest%`(0x375c)/`ManaRest%`(0x3778)/full. No emergency/recall tier (PvP
disconnect on `[PvP] FleeTimeout` is the only hard escape).

**Ported to:** `src/mmud/automation/spells.py` (`SpellEngine._attack_casts`, `on_kill`
reset), `src/mmud/combat/combat.py` (`CombatEngine._flee` walks out exits + rests; plus a
non-MegaMud `emergency_cmd` tier). See [`../combat.md`](../combat.md).
