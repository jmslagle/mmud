# Parsing — detecting combat, rooms, monsters, exp, vitals, players

Grounded in `megamud.exe`: `combat_event_parse @0x4176b0`, `room_exit_parse @0x425290`,
`room_also_here_parse` / `room_entity_classify_all`, `game_state_process @0x429720`.
For the full RX pipeline see [`../megamud-responses-reference.md`](../megamud-responses-reference.md).

## Combat state
Driven by the authoritative `*Combat Engaged*` / `*Combat Off*` markers
(`bot._parse_combat_state`). **`*Combat Off*` does NOT clear the roster** — it fires
between rounds. (The old "any MESSAGES.MD apply-match → in_combat" was a bug.)

## Monster roster (RE: `combat_event_parse @0x4176b0`, see [source](source/combat_event_parse.md))
- `Also here:` **REPLACES** the roster; arrivals append-if-absent.
- **A kill is `You gain N experience.` — AUTHORITATIVE.** It removes the current target
  (MegaMud's pinned slot-0 `room_entity_slot_remove @0x45a850`, by INDEX not name),
  clears the target, and requests a room re-scan. `You have progressed too far without
  training` is also a kill (maxed char, no XP).
- **MegaMud has NO per-monster death string** (none in MONSTERS.MD). The varied flavor
  death lines ("collapses without a sound", "falls to the ground, and is still") are
  **ignored** — don't build a generic death regex to remove on them.
- `<name> is dead.` → re-scan the room (re-read `Also here:`), don't name-remove.
- `<name> drops to the ground!` → **player/party** death, NOT a monster kill.
- `You do not see X` is a departure (`room_entity_movement_parse @0x4589c0`, by name).
- An exits line with **no** `Also here:` clears a monster-free room — BUT a wander-in
  (`X creeps into the room`) now marks the room occupied (`_also_here_seen`), so a stray
  exits line can't clear a just-arrived monster (it would otherwise rest/move through it).
- **Safety net (`_engage_attacker`):** when a line says `The <monster> <attack-verb> …
  you`, the attacker is added to the roster if absent — so we fight back even if its
  arrival was missed or cleared by a room-display race (the "rests through a monster
  beating on it" bug). MegaMud re-scans the room on combat events; this is our equivalent.

This killed phantom-target spam + cross-room accumulation. A stale
`monsters=['fat giant rat', …]` at index 0 in the session log reveals a phantom target.

## Exp
`You gain N experience.` is parsed as a per-kill **delta** → `session.exp_gained`
(rate) + kill count. The absolute `Exp:` line is display-only.

## Vitals
The bot sends `stat` once on entry so max HP/MA is learned — otherwise the flee / rest
/ mana thresholds never fire (they're fractions of the max).

## Rooms
- `detect_room` normalizes names ("Newhaven, Arena" → `ROOMS.MD` "Newhaven Arena") and
  resolves the **room-id hash** (see [navigation.md](navigation.md)).
- `parse_exits` keeps door-prefixed exits; `exit_signature()` implements MegaMud's exit
  bitfield (Arena → `0x10002` = low 20 bits of NARN `0xABC10002`, verified).

## Players — look / spy
MegaMud `LookPlayers` / `player_info_lookup_decide @0x4037cf`:
- `pvp.look_players` config (default True). `PlayerLookDecider`
  (`automation/players.py`, PRIO_LOOK=108) sends `l <name>` at unknown non-friend
  players, begins `TaskType.LOOKING`.
- `parser/player_parser.py` parses the `[ Name ]` examine block (race/class), arrivals/
  departures (sneak in/out, walks in/leaves), and `<Name> is looking at you`
  (→ `session.attacked`).
- Persisted to the spy DB via `store.learn_player(name, **fields)` (merges who-list +
  examine). The store initializes whenever `learning.enabled`.

## Stats (full parity)
`DamageStat` per type (hit/extra/crit/backstab/cast/round = damage-taken);
`combat_accuracy()` → pct + R:min–max + A:avg. `_parse_combat_stats` classifies
hit/crit/backstab, parses CAST damage ("You fire … for N" — was untracked for casters),
dodge, sneak, and monster-hit (Round). `bot._flush_stats()` (1 Hz) emits the full
panel field set. Combat-stat regexes are best-effort for melee wording (the dev log was
a caster) — refine verbs against a real melee session if hit/crit% look off.

## Config lives in BBS.INI, not the DB
MegaMud's per-character settings live in **`BBS.INI`** (`GetPrivateProfileString`), NOT
in `PLAYERS.MD` (which is the who/spy DB of *other* players).

- The `Cmd*` keys (`CmdRest`/`CmdSneak`/`CmdHide`/`CmdSearch`/`CmdInv`…) are **UI
  toolbar buttons only** — automation never reads them.
- Automation **hardcodes** rest/search/sneak/hide/backstab(`bs`)/flee/bash/open/get/
  equip/train/buy/sell/join/invite. The only real automation knobs are the attack
  prefix (`AttackCmd`), the spell commands, and `PreRestCmd`.

## Inventory parse + item-name matching (RE-confirmed 2026-06-26)
`inventory_parse_response @0x0043d650` parses the `i`/`inv` response. Decisive rules
(verified against the binary, then mirrored in `parser/inventory_parser.py` +
`navigation/code_route.py`):
- **Item list split on `,` and `.` ONLY — never on " and ".** So multi-word names that
  contain "and" (`rope and grapple`, `bow and arrow`) stay intact. The earlier bug
  split `rope and grapple` → `rope`/`grapple`, so the rope-and-grapple path gate never
  matched and the bot wandered "lost" (see ../re/navigation.md).
- **Wrapped lines are rejoined**, NOT detected by leading whitespace. The live "Realm
  of Legends" `i` output word-wraps the carrying list across lines with **no leading
  space**; MegaMud stashes the trailing partial item and prepends it to the next line.
  Our parser accumulates the whole section's text and splits only when it ends.
- **Worn gear is inlined in the carrying list with a `" (Slot)"` suffix** (`(Neck)`,
  `(Weapon Hand)`, …) — there is no separate "You are wearing" line on this server. The
  suffix is stripped; a slot ⇒ worn, else carried. Leading digit = quantity.
- **`You have the following keys: …`** is parsed as more carried items (so a `brass key`
  gate is satisfied). `You have no keys.` / `Wealth:` / `Encumbrance:` terminate the
  list; the binary hard-codes the misspelt `"Encumberance"` — accept both spellings.
- **Name comparison: `item_name_match @0x00442080`** — strip apostrophes from both, then
  exact compare with **trailing-`'s'` plural tolerance** (so `black star keys` matches a
  `black star key` gate). NOT substring, NOT case-folded (works because data is
  lowercase). `inventory_item_find_by_name @0x0043d210` additionally treats the boats
  `wooden skiff`/`log raft`/`silverbark canoe` as interchangeable. The path-gate check
  (`pathfind_next_step @0x0042b7b0`, required-item NAME at edge+0x1a; `""`/`"None"` ⇒ no
  requirement) and the inventory parser share this comparator — both operate purely on
  **name strings**, never numeric ITEMS.MD ids.

## Debugging: the session log
`src/mmud/debug_log.py` (`SessionLogger`) writes a human-readable log when
`[session] debug_log = "logs/session.log"` is set (enabled in the gitignored
`characters/raist.toml`; `logs/` is gitignored). Format: `HH:MM:SS.mmm <TAG> <text>`:
- `RX` — ANSI-stripped line received
- `TX` — command sent
- `EVT` — state events (`combat=on`/`off`, `monsters=[…]`, `arrive room=… hex=… seen=[…]`,
  `objective: …`, `route goto … (N steps): …`)

Reading the RX/TX/EVT interleave is the primary way we debug live navigation/combat.
