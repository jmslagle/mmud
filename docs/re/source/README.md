# RE'd function source — `docs/re/source/`

Ground-truth decompilations of `megamud.exe` functions, cleaned into readable
C/pseudocode so we never have to re-reverse-engineer the same function twice.

**Convention**
- **One file per function**, named after the function: `<function_name>.md` (the
  algorithm goes in a fenced ```` ```c ```` block — markdown so it renders and the C
  linter doesn't flag pseudocode).
- First line(s): a header comment with the **address**, a one-line purpose, and the
  game-state offsets it touches (named, not raw `+0x….`).
- Body: cleaned C / pseudocode — keep MegaMud's control flow and the *decisive*
  branches (caps, resets, gates). Annotate offsets with names; drop noise (stack
  temporaries, logging) unless it's load-bearing.
- End with a short **"Behaviour"** note in plain English and **"Ported to"** pointing at
  the Python that implements it.

These files are the authoritative algorithm. The prose in `docs/re/*.md` summarises the
*concepts* and cross-references here; the auto-memory indexes the highlights. When you
RE a new function (per CLAUDE.md, always RE the binary for MegaMud-matching behaviour),
**write it here** before moving on.

## Index

| Function | Addr | Purpose |
|---|---|---|
| [`combat_flee_or_hide_decide`](combat_flee_or_hide_decide.md) | `0x407f70` | Per-tick combat driver: flee/hide/backstab + the main attack cast-vs-melee decision (MaxCastCnt / AttMaxDmg / ManaAttack% gates; per-kill counter reset) |
| [`combat_event_parse`](combat_event_parse.md) | `0x4176b0` | Monster kill (by `You gain N exp` → remove pinned slot-0 target), player/party death, "is dead" re-scan. No per-monster death string exists |
| [`inventory_parse_response`](inventory_parse_response.md) | `0x43d650` | Parse the `i`/`inv` listing (split on `,`/`.` only; rejoin wraps; `(Slot)` worn tags; keys line) |
| [`item_name_match`](item_name_match.md) | `0x442080` | Item-name comparator: apostrophe-stripped exact match + trailing-`'s'` plural tolerance |
