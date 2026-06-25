# Parsing — detecting combat, rooms, monsters, exp, vitals, players

Grounded in `megamud.exe`: `combat_event_parse @0x4176b0`, `room_exit_parse @0x425290`,
`room_also_here_parse` / `room_entity_classify_all`, `game_state_process @0x429720`.
For the full RX pipeline see [`../megamud-responses-reference.md`](../megamud-responses-reference.md).

## Combat state
Driven by the authoritative `*Combat Engaged*` / `*Combat Off*` markers
(`bot._parse_combat_state`). **`*Combat Off*` does NOT clear the roster** — it fires
between rounds. (The old "any MESSAGES.MD apply-match → in_combat" was a bug.)

## Monster roster
- `Also here:` **REPLACES** the roster; arrivals append-if-absent.
- A kill (`You gain N experience`) removes the current target (MegaMud's slot-0
  `room_entity_slot_remove`); named death/slay/`You do not see X` remove by exact name.
- An exits line with **no** `Also here:` clears a monster-free room.

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

## Debugging: the session log
`src/mmud/debug_log.py` (`SessionLogger`) writes a human-readable log when
`[session] debug_log = "logs/session.log"` is set (enabled in the gitignored
`characters/raist.toml`; `logs/` is gitignored). Format: `HH:MM:SS.mmm <TAG> <text>`:
- `RX` — ANSI-stripped line received
- `TX` — command sent
- `EVT` — state events (`combat=on`/`off`, `monsters=[…]`, `arrive room=… hex=… seen=[…]`,
  `objective: …`, `route goto … (N steps): …`)

Reading the RX/TX/EVT interleave is the primary way we debug live navigation/combat.
