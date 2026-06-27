# `game_ai_do_something` @ `0x402b20`

MegaMud's "DoSomething" — the priority decision chain, run **once per turn** at the
prompt boundary (called from `network_receive_dispatch @0x45d520` only when the READY bit
is set). It evaluates action categories in fixed order and **returns on the first action
taken — at most ONE logical action per turn**.

```c
int game_ai_do_something(GameState *gs) {
    if ((gs[0x14fd] & 1) == 0) return 0;     /* not READY (no prompt turn) -> do nothing */
    int did = 0;
    if (did == 0) did = room_redisplay_if_stale(gs);     /* step 7: bare "\r" */
    if (did == 0) did = queued_command_dequeue_send(gs); /* step 8: drain ONE queued cmd */
    if (did == 0) did = ...;                              /* ... see order below ... */
    return (did != 0);
}
```

**Priority order** (each `if (did==0) did = X_decide(gs);`):
1. step 7  — re-display room (`\r`) if room data stale
2. **step 8 — `queued_command_dequeue_send`** — drain ONE deferred command
3. rest (party gate), sys-stat
4. step 0xB — `combat_backstab_prepare`
5. setup burst, stats refresh, inventory `i`, online list
6. 0x10 scheduler → 0x12 cash discard → 0x13 loot → 0x14 auto-equip → 0x15 script →
   0x16 party heal → 0x17 party buff → **0x18 cast_configured_spell** → 0x19 invite →
   **0x1A `combat_flee_or_hide_decide`** → 0x1C lookup → 0x1D track/backstab →
   0x20 `combat_rest_decide` → 0x21 bless → 0x22-25 bank/shop →
   **0x26 `combat_engage_or_move_decide`** → 0x27 search → 0x28 stash →
   **0x29 `navigation_step_decide` → 0x2A `path_follow_step_decide`** → 0x2B hide/backstab

**Two outgoing paths:**
- **Immediate ring** (`net_buffer_receive @0x41c4c0` → ring `gs+0x85ed`, flushed by the
  comms thread `net_send_queue_flush @0x41c940`): ONE chosen action may write a small
  fixed multi-line burst here (e.g. low-HP → `break`/`sys goto`/dest/`\r`/`rest`). **No
  time gate** — the wrapper just writes bytes.
- **Deferred queue** (`queued_command_enqueue` → array `DAT_004da180`, count
  `DAT_004d7914`): drained **one entry per turn** by `queued_command_dequeue_send
  @0x46c020` (step 8 returns 1, consuming the whole turn). So a multi-command burst (e.g.
  the login/setup sequence) trickles out one line per prompt, not all at once.

## Behaviour
- ONE decision per turn (returns on first action). Per-command cooldowns live inside the
  individual deciders (the ~4 s `combat_spell_cast` gate; rest/sneak/hide debounced by
  their own flags/task-state), NOT a global throttle.
- The chain runs only when READY (set by the bare prompt — see
  [`network_receive_dispatch.md`](network_receive_dispatch.md)). Lock-step on the prompt
  is what prevents flooding ("Why don't you slow down?").

**Ported to:** `bot._next_command` + `DecisionEngine` (the priority chain already mirrors
this order). The gap is *cadence*: we must run it once per prompt turn, not per line. See
[`../timing.md`](../timing.md).
