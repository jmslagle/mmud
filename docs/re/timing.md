# Command-send timing — MegaMud's turn model (RE'd 2026-06-26)

Our recurring "timing" bugs (double-move, casting a just-killed monster, sneak/hide spam
between rounds) all have ONE root cause: **we decide+send after every received line.**
MegaMud doesn't. This is the authoritative model. Source:
[`source/network_receive_dispatch.md`](source/network_receive_dispatch.md),
[`source/game_ai_do_something.md`](source/game_ai_do_something.md).

## The model

1. **Parsing is decoupled from deciding.** `network_receive_dispatch @0x45d520` drains the
   whole received chunk one byte at a time, and on each newline parses the completed line
   via `server_message_dispatch @0x45dea0` → ~40 `*_parse` functions. **Those parsers only
   mutate state (roster, target, hp, room, combat); they never send the AI's next action.**

2. **A "READY" bit gates the decision.** Bit 0 of `gs+0x53F4`:
   - **SET** only by the prompt parser `hp_parse_and_update @0x45e980` when the line is
     exactly the `[HP=...]` prompt with NOTHING trailing AND the input buffer is drained
     (`gs+0x53f8`==0, `gs+0x59d0`==0, `gs+0x59d8`==0). Low-HP force-sets it so flee/heal
     isn't starved.
   - **CLEARED** on every newline (and on a non-empty/echo prompt).

3. **Decide once per turn.** After draining the chunk, `network_receive_dispatch` calls
   `game_ai_do_something @0x402b20` **exactly once, and only if READY**. DoSomething walks
   the priority chain and **returns on the first action — at most one action per turn.**

4. **Lock-step on the prompt.** After a command is sent, the server's reply is
   newline-terminated lines (each clearing READY) ending in a fresh `[HP=...]` prompt;
   only that re-arms READY. There is **no global time throttle** — the prompt lock-step IS
   the throttle (it's why the server never says "Why don't you slow down?"). A separate
   ~1 Hz idle re-post (`network_read_thread @0x41bad0` via `GetTickCount`) re-enters the
   decider when the bot sits idle at a prompt with something it wants to do (e.g. start a
   loop). The 1 Hz `SetTimer` does housekeeping only — it does NOT drive the AI.

5. **Queues.** Two outgoing paths: an **immediate ring** (one action may emit a small
   fixed multi-line burst), and a **deferred command queue** drained **one entry per turn**
   (`queued_command_dequeue_send @0x46c020`) — so a multi-command sequence trickles out one
   line per prompt.

## Why our port hits timing bugs
We run the decision chain after EVERY parsed line, so:
- a stale "no exit" (result of a superseded move) fires a second move on top of the
  in-flight one → **double-move**;
- the cast decision fires on the cast-result damage line microseconds before the
  `You gain N experience` line (same packet) clears the target → **cast a dead monster**;
- the backstab/sneak re-evaluates on the between-round `*Combat Off*` flicker →
  **sneak/hide spam**.

## The alignment (target architecture)
Split the loop exactly like the binary:
- **Reader/parser:** consume the whole received chunk, updating state. Maintain a `ready`
  flag — set when you parse a **bare `[HP=...]:` prompt** (nothing after the `:`, buffer
  drained); clear it on every other line.
- **Decider:** run the priority chain once **only when `ready`**, take at most one action,
  then clear `ready` (re-arms on the next prompt). Keep a ~1 s idle tick to re-enter when
  idle at a prompt.

Partial steps already shipped toward this (each a symptom-level patch until the full
turn-gate lands): the stale-failure prompt-echo guard, the in-combat `_can_act` mid-round
gate (`bot._process_line`), and the backstab opener-latch. The full fix is to make the
decider prompt-turn-gated for ALL actions (with login/queue draining preserved).
