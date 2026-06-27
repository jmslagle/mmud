# `network_receive_dispatch` @ `0x45d520`

The receive path that drains the server byte-stream, parses each line into state, and
then runs the AI **once** at the turn boundary. This is the function whose structure our
port must mirror: **parsing only updates state; the decision/send runs separately, gated
on the prompt.**

Driven by `WM_USER+0x99` (0x499), posted by the comms thread `network_read_thread
@0x41bad0` whenever bytes arrive (and once every ~1 s while idle via `GetTickCount`, so a
bot sitting at a prompt with nothing to do still gets a chance to act). The 1 Hz
`SetTimer(hwnd,100,1000)` (`game_timer_tick @0x44d3a0`) does **housekeeping only** (AFK,
statline, anti-detect handshake) — it never drives the AI.

**Ready flag:** bit 0 of `gs+0x53F4` (seen as `param_1[0x14fd]` where the pointer is
typed `undefined**`, so index ×4 = byte offset). Set ONLY by the prompt parser
`hp_parse_and_update @0x45e980` when the line is exactly the `[HP=...]` prompt with
nothing trailing AND the input queue is drained:

```c
/* hp_parse_and_update: after stripping the matched "[HP=...]" off the line, */
if ((iVar11 == -2)                       /* strlen(line)==0 -> bare prompt */
    && (*(int*)(gs+0x53f8) == 0)         /* pending-response counter == 0 */
    && (*(int*)(gs+0x59d0) == 0)         /* socket input queue drained */
    && (*(int*)(gs+0x59d8) == 0)) {
    *(uint*)(gs+0x53f4) = (val & 0xfffffffc) | 1;   /* READY (bit0) */
}
/* low-HP force-sets ready too (gs+0x55d4) so flee/heal can't be starved */
```

```c
int network_receive_dispatch(GameState *gs) {
    while (drain one byte from the recv queue gs+0x69e9 into the line buffer gs+0x79ea) {
        if (byte == '\n') {
            gs[0x14fd] &= 0xfffffffc;                 /* clear READY on every newline */
            server_message_dispatch(gs, line, /*line_complete=*/1, 0);   /* PARSE -> state */
            reset line buffer;
        }
    }
    /* parse the still-in-progress partial line — this is how the no-newline
     * "[HP=...]:" prompt gets matched and sets READY */
    if (server_message_dispatch(gs, line, /*line_complete=*/0, 0)) reset line buffer;

    /* DECIDE — exactly once, only at the turn boundary */
    if (strlen(line) == /*empty*/ -2 && (gs[0x14fd] & 1)) {
        game_ai_do_something(gs);     /* the priority chain; at most ONE action */
    }
}
```

`server_message_dispatch @0x45dea0` is a pure fan-out to ~40 `*_parse` functions (hp,
room title/exits, roster also_here/scan/movement, combat events, spell/sneak/hide
outcomes, items…). **None of them send the AI's next action** — they mutate state and
return matched/not.

## Behaviour
1. Drain the entire received chunk, parsing each line into state. READY clears on every
   newline; it is set only when the bare `[HP=...]` prompt is parsed and the buffer is
   empty/drained.
2. Then, if READY, run `game_ai_do_something` once (one action), which consumes the turn.
   After sending, the server's reply (newline-terminated lines + a new prompt) clears and
   eventually re-arms READY → lock-step. No global send throttle exists; the lock-step IS
   the throttle.

**Port gap:** our bot decides+sends after EVERY line (coupled), causing double-move,
casting a just-killed monster, and sneak/hide spam between rounds. Align by splitting
reader/parser from a prompt-gated decider. See [`game_ai_do_something.md`](game_ai_do_something.md),
[`../timing.md`](../timing.md).
