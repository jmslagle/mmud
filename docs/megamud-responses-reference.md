# MegaMud Internals: Response Parsing Reference ("how the app works")

How `megamud.exe` turns incoming server text into game state — the RX pipeline,
the central line classifier, and the parsers, with **room detection** and
**monster detection** as the centerpiece. Built by decompiling `megamud.exe`
(fully analyzed in Ghidra). Use this instead of reopening Ghidra to re-derive
parsing behavior.

> Companion: [`megamud-commands-reference.md`](megamud-commands-reference.md) —
> what MegaMud *sends* and which commands are configurable.

> **Confidence note:** function names + addresses are high-confidence (Ghidra has
> 100% named coverage). Struct field offsets and some bit meanings are inferred
> from decompilation and should be treated as "best current understanding,"
> verifiable by re-decompiling the cited function.

---

## 1. RX pipeline (bytes → lines → dispatch)

```
WinSock/serial RX
  → network_receive_message_pump (0x0040f1a0)   poll WM_USER+0x99
  → network_receive_dispatch     (0x0045d520)   per-byte: ANSI strip, line assembly
       └ ansi_escape_parse       (0x0045d830)   VT100 state machine, 4 param slots
  → (on LF 0x0A) server_message_dispatch (0x0045dea0)   classify line → ~30 parsers
  → game_ai_do_something         (0x00402b20)   master AI tick (acts on new state)
```

- Bytes land in a circular receive buffer; `"-RX Queue overflow"` / `"DBG:
  Recursive receive!"` (`0xbea54`) guard the buffer and re-entrancy.
- Lines are assembled on LF; ANSI/VT100 escapes are parsed/stripped by
  `ansi_escape_parse`. Each completed line is logged `"Current line: \"%s\""`
  (`0xbf0e4`) and handed to the classifier.
- **`server_message_dispatch` (`0x0045dea0`)** is the central classifier: it
  pattern-tests the line and routes to the specialized parsers below (prompt,
  room title/exits/also-here, combat, conditions, inventory, who, exp, …).

---

## 2. ROOM DETECTION (centerpiece)

MegaMud does **not** trust a server room id. It computes a **client-side exit
hash** and matches that against ROOMS.MD, with the loaded `.MP` path as a
position oracle for disambiguation/recovery.

### 2.1 Identification key = exit-hash bitfield

`room_exit_parse` (`0x00425290`) parses the `"Obvious exits: "` line (`0xb82d4`)
and packs the 10 directions into a 32-bit value at `game_state+0x2e98`:

- 10 dirs × 2 bits: N,S,E,W,NE,NW,SE,SW,U,D. Per-dir state:
  `0` none/secret-closed · `1` open · `2` closed/locked door · `3` open door
  (`4` secret-open is normalized to `0` before hashing).
- Upper bits (`& 0xfff00000`) carry a base id.
- Then `room_lookup_by_id` (`0x004768a0`) **linear-scans** the room array
  (`game_state+0x2c48`, count `+0x2c40`), comparing each record's id field
  (`+0x44`) to the hash. Result stored at `game_state+0x2ec8`.
- Secondary `room_db_lookup_by_code` (`0x004768e0`) matches by **room name**
  (record `+0x06`) for navigation/door lookups.

Direction parsing handles `(closed)`/`(open door)` annotations and `[keyword]`
door tokens. If the exits line arrives split across packets, a continuation flag
(`game_state+0x53f4 |= 0x10000`) buffers the fragment (`+0x53fc`) for re-parse.

ROOMS.MD record (partial): `+0x06` name · `+0x44` id (exit-hash key) · `+0x48`
flags (`0x10` stop-before-enter, `0x20` avoid, `0x80` special).

### 2.2 Path correlation & uncertain-room recovery

`path_follow_step_decide` (`0x00405b60`) compares the current room vs. the
expected room from the loaded `.MP` path:

- **1st mismatch** → flag for confirmation.
- **2nd mismatch** → check the expected-direction exit; mark the step "uncertain"
  and log `"[Uncertain room (Path %s, step %d): Trying step anyway]"` (`0xb5914`),
  or force resync.
- **≥3 mismatches** → `path_find_current_step` (`0x0042bf40`) rescans the path's
  embedded room list (`path+0x80`, count `+0x6c`) for the current exit-hash; on
  success logs `"[Resynced from path step %d to %d]"`; on failure marks "lost"
  and updates the connection status. Adding a new room logs `"[Adding room \"%s\"
  from path \"%s\"]"` (`0xb94a4`); unknown start logs `"[Path \"%s\" begins at an
  unknown room]"` (`0xb94c8`).

### 2.3 Multi-line assembly & refresh

Room output (`In room:` id line, name, `Obvious exits:`, `Also here:`, ground
items) is assembled incrementally; `game_state+0x53f4` bits track completion
(`0x10000` exits-incomplete, `0x10` also-here-incomplete). If idle, the AI tick
re-requests the room: `game_ai_do_something` (`0x00402b20`) sets task `0x27`
(re-display), logs `"[Re-displaying room]"` (`0xb52dc`) / `"Re-showing room
exits"` (`0xb5a90`), and sends an empty line to force a re-print. Light changes
log `"[Room light updated]"` (`0xb58d4`); dark/pitch-black rooms are detected.

---

## 3. MONSTER DETECTION (centerpiece)

Pipeline: **parse names → match MONSTERS.MD → classify enemy/flee → prioritize →
flee-rule checks**.

### 3.1 Parse creature names

`room_also_here_parse` (`0x004580a0`) finds `"Also here: "` (`0xbfd48`) and splits
the list on `,` (`0xb82a0`) / terminal `.` (`0xb6b84`), trimming whitespace.
Handles `(Charmed)` suffixes, trailing `*` (plural/duplicate marker), and special
named spirits. Entities are stored in the room entity array (`game_state+0x1ee0`,
count `+0x1ed4`, ~50 slots). `room_entity_classify_all` (`0x00459880`) then
re-trims, drops stale entries, and re-sorts priority; new creatures log
`"[%s added to known monsters]"` (`0xb7668`).

### 3.2 Match to MONSTERS.MD (210-byte records)

`monster_db_lookup_by_name` (`0x004544d0`) — **two-pass, priority-first**:

- Pass 1 scans records with the priority flag (`record+0x24 & 0x08`); Pass 2 the
  rest. Match via `pattern_match_remove` (strips leading articles a/an/the/some,
  case-insensitive substring with a **word-boundary** check: a match mid-string
  only counts if preceded by a space). Exact match wins immediately.
- `monster_record_lookup_by_name` (`0x00454570`) is the stricter exact
  (`string_compare_nocase`) variant, used by PvP player matching.

MONSTERS.MD record (partial): `+0x01` name (≤32, NUL-term) · `+0x24` flags
(`0x08` priority-match) · `+0x25…` enemy-classification bytes · `+0x41…` exp /
combat-behavior fields.

### 3.3 Classify enemy / non-enemy / flee

- `combat_event_parse` (`0x004176b0`): a creature that "moves to attack YOU" is
  marked enemy — `"[%s marked as enemy!]"` (`0xb7e54`); attacking another player
  marks non-enemy — `"[%s marked as non-enemy]"` (`0xb764c`).
- `pvp_engaged_handle` (`0x00419c50`): identifies attacker; if not in MONSTERS.MD,
  treats as a player and logs `"[PVP detected! (%s)]"` (`0xb7ed4`); marks
  enemy/flee per config (`"[Player %s marked as enemy!/flee!]"` `0xb7e34`/`0xb7e18`).

### 3.4 Prioritize & flee rules

`room_entity_priority_sort` ranks: in-combat first, then enemy-marked, then
non-flee, then MONSTERS.MD priority flag, then exp value.
`combat_flee_or_hide_decide` (`0x00407f70`) reads the room monster count
(`+0x1ed4`) and summed exp and flees on: too-many-monsters
(`"[Running: Too many monsters! (%s)]"` `0xb5eb8`), too-much-exp
(`"[Running: Too much monster experience! (%s)]"` `0xb5e10`), or HP/mana below
threshold; also handles the PvP hangup timer.

---

## 4. Prompt parser (status line)

`hp_parse_and_update` (`0x0045e980`) parses the MajorMUD prompt — anchors `"[HP="`
(`0xbe178`), `"%d[HP=%h"` (`0xc2b0c`). Extracts current/previous HP, mana,
resting/meditating state, the low-HP threshold, and detects death. Fully
hardcoded (no INI). HP/mana drive the rest/heal/flee deciders.

## 5. MESSAGES.MD (effect/spell pattern table)

- `messages_md_load` (`0x00451040`) loads `"Messages.md"` (`0xb8864`); blank
  records warn (`"MESSAGES.MD contains a blank message."`). `SortMessages`
  (`0xbd0c0`) orders the table (`game_state+0x1f1c`, count `+0x1f14`, entry
  `0x48` dwords).
- Each record is a 3-line template: header (`TypeName:MessageId`), an **apply**
  line, and a **remove** line, with wildcard captures (e.g. target/dmg).
- `message_db_lookup_by_name` (`0x00451820`) matches an incoming line against the
  table (linear scan, wildcard-aware). Drives condition onset/recovery and combat
  effect recognition.

## 6. Other parsers

- **Inventory:** `inventory_parse_response` (`0x0043d650`) → `inventory_item_add`
  (`0x0043fb60`), new items log `"[%s added to known items]"` (`0xbd824`); matches
  against ITEMS.MD.
- **Who/party:** `who_list_parse` (`0x00497d10`) — `"Player \"%s\" added in
  ParseWho"` (`0xc635c`).
- **Conditions:** `condition_onset_parse` (`0x00450410`) with a trigger table
  (poison/disease/blind/hold onset & recovery, via MESSAGES.MD patterns).
- **Experience/level/training:** `exp_response_parse` (`0x0046fab0`) — `"Level:"`
  (`0xc19d4`), `"Exp needed for next level:"` (`0xc19b4`), training-ready.

## 7. Response category catalog

| Category | Recognizer (addr) | Anchors |
|---|---|---|
| Status prompt | `hp_parse_and_update` (`0x0045e980`) | `[HP=`, `%d[HP=%h` |
| Room title/exits | `room_title_parse` (`0x00475e20`), `room_exit_parse` (`0x00425290`) | `In room: %08lX`, `Obvious exits:` |
| Also-here / monsters | `room_also_here_parse` (`0x004580a0`), `room_monster_spy_parse` (`0x00457050`) | `Also here:` |
| Combat hit/miss/death | `combat_event_parse` (`0x004176b0`) | MESSAGES.MD apply/remove |
| Conditions | `condition_onset_parse` (`0x00450410`) | poison/disease/blind/hold |
| Experience/level/train | `exp_response_parse` (`0x0046fab0`) | `Level:`, `Exp needed…` |
| Inventory | `inventory_parse_response` (`0x0043d650`) | inventory listing |
| Who/party | `who_list_parse` (`0x00497d10`) | `Player "%s" added…` |
| Login/menu prompts | dispatch in `server_message_dispatch` | menu/logon prompts |

---

## 8. Open items to verify

- `server_message_dispatch` branch order (how line-type precedence is decided).
- Exact `room`/entity struct field maps beyond the offsets cited.
- MESSAGES.MD record field layout (the `0x48`-dword entry) in detail.
- Whether condition cures and inventory-refresh on the automation path use INI
  keys or literals (affects the commands-reference §5 "to verify" list).
