# MegaMud reverse-engineering notes

This directory captures what we've reverse-engineered from `megamud.exe` (the
1998–2001 Windows MajorMUD/MajorBBS automation client) while rebuilding it as a
Python bot. **Ground truth is the binary** — when behavior must match MegaMud,
these notes record the exact algorithm + function addresses + offsets so we don't
re-derive them from Ghidra each time.

> Working rule (see project `CLAUDE.md`): RE the binary for parsing/hashing/combat/
> timing/data-format questions. The `*_md_save`/`*_parse`/`*_decide` functions are
> authoritative. Verify against real `.MD` bytes and live session logs before shipping.

## The binary

- `megamud.exe` — PE32, ~831 KB, MSVC ~6.0 C++. Image base `0x00400000`.
- Open in Ghidra (project `mmud.gpr`); the Ghidra MCP (`mcp__ghidra__*`) is connected.
- **100% of functions are named** (zero `FUN_` remain, as of 2026-06-10). Naming
  convention: snake_case with a domain prefix (`crt_`/`cdb_`/`net_`/`game_`/
  `pattern_`/`path_`/`room_`/`combat_`/`ansi_`). Ghidra's "not PascalCase" rename
  warnings are cosmetic — ignore.
- `0x004a0000–0x004b0000` is a ~288-function statically-linked blob = **MSVC 6 CRT**
  (`crt_*`) + the **"MDB2" keyed-record B-tree DB engine** (`cdb_*`) that reads/writes
  the `.MD` files. See [data-formats.md](data-formats.md) and
  [`../cdb-mdb2-format.md`](../cdb-mdb2-format.md).

## Index

| Doc | Covers |
|-----|--------|
| [data-formats.md](data-formats.md) | `.MD` binary record layouts (MONSTERS/ITEMS/SPELLS/PLAYERS/CLASSES/RACES/PATHS), GameState offsets, combat-stats block, condition table |
| [navigation.md](navigation.md) | Room-id hash, code-graph routing, MegaMud's path-follower, position tracking & resync rules |
| [combat.md](combat.md) | Kill-type targeting, cast-vs-melee decision, rest/meditate recovery |
| [terminal.md](terminal.md) | ANSI emulation, telnet NAWS, the `ESC[6n` screen-size probe |
| [parsing.md](parsing.md) | Combat-state / room / monster / exp / vitals / player-spy detection |

Two larger binary-grounded references live one level up:
- [`../megamud-commands-reference.md`](../megamud-commands-reference.md) — every
  outbound command + whether it's configurable (BBS.INI) or hardcoded.
- [`../megamud-responses-reference.md`](../megamud-responses-reference.md) — the RX
  pipeline and parsing internals.
- [`../cdb-mdb2-format.md`](../cdb-mdb2-format.md) — the MDB2 B-tree container format.

## Key function addresses

| Address | Name | Role |
|---------|------|------|
| `0x0041c4c0` | `net_buffer_receive` | 1024-byte circular network buffer (also used to send replies) |
| `0x00429720` | `game_state_process` | main room/state handler |
| `0x00427a10` | `pattern_match_dispatch` | MESSAGES.MD pattern dispatch |
| `0x00485ee0` / `0x00485e60` | `pattern_match_apply` / `_remove` | message-pattern apply/remove (also name matching) |
| `0x004176b0` | `combat_event_parse` | combat line parsing |
| `0x00408f36` | `combat_flee_or_hide_decide` | flee/hide + the `tier != 4` attack gate |
| `0x00407b7d` | `combat_spell_cast` | per-round attack-spell cast |
| `0x0040b380` | `combat_rest_decide` | HP/mana rest decision |
| `0x0040caa0` | `mana_meditate_decide` | mana `meditate` decision |
| `0x004544d0` | `monster_db_lookup_by_name` | monster name → record (adjective handling) |
| `0x00475e20` / `0x00425290` | `room_title_parse` / `room_exit_parse` | room-id hash inputs |
| `0x00459880` | `room_entity_classify_all` | classify "Also here" entities + AttackNeutral promotion |
| `0x00405b60` | `path_follow_step_decide` | path-following engine |
| `0x0042bf40` | `path_find_current_step` | relocate on a path after mismatch |
| `0x0045d830` | `ansi_escape_parse` | ANSI/VT100 state machine |
| `0x0040eb10` | `ansi_cursor_pos_report` | `ESC[6n` → `ESC[row;colR` reply |

Data extracted at `extractions/mm103s.exe.extracted/45DAD/Default/`. Python port in
`src/mmud/`. Parsers in `src/mmud/data/binary.py`.
