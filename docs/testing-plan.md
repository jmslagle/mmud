# In-Person Testing Plan — mmud v0.1

**Goal:** Connect to a live MajorMud server, verify each layer of the bot works, and document what needs fixing.

**Time estimate:** 2–3 hours for a thorough first session.

---

## Prerequisites

- [ ] A MajorMud BBS account with an active character
- [ ] Server host, port, BBS login, character name
- [ ] Python 3.11+ and mmud installed (`pip install -e ".[dev]"`)
- [ ] A test character (ideally not your main — the bot will fight monsters)
- [ ] Notepad or a capture file open to record unexpected output

---

## Setup

### Step 1: Create your character config

```bash
cp characters/example.toml characters/mychar.toml
$EDITOR characters/mychar.toml
```

Fill in at minimum:
```toml
[server]
host = "YOUR_SERVER"
port = 23          # or whatever port your BBS uses

[login]
username  = "your_bbs_username"
password  = "your_bbs_password"
character = "Exact Character Name"
```

Leave everything else at defaults for now.

### Step 2: Verify tests pass before starting

```bash
pytest -q
```
Expected: 434 passed. If any fail, don't proceed — fix the environment first.

### Step 3: Open a capture log

Enable console logging so you have a record of everything the server sends:

```bash
python -m mmud.tui --char characters/mychar.toml 2>&1 | tee /tmp/mmud-session.log
```

---

## Phase 1: Connection (5 minutes)

**Goal:** Establish a raw TCP connection and see the server's welcome text.

- [ ] Launch the TUI: `python -m mmud.tui --char characters/mychar.toml`
- [ ] Verify the TUI renders without errors (3 panels visible, stats bar, command input)
- [ ] Press `Ctrl+K` to connect
- [ ] **Watch the main output window** — server text should start flowing
- [ ] Verify the sub-title updates to `[connected]`

**What can go wrong:**
- Connection refused → wrong host/port
- Blank screen → server sending binary telnet negotiations our client strips; that's OK
- Crash on connect → check `mmud.net.connection.py` readline error handling

**Record:** What does the first line the server sends look like? Copy it here.

---

## Phase 2: Login Sequence (10 minutes)

**Goal:** The bot detects BBS prompts and logs in automatically.

- [ ] Watch the output as the server sends login prompts
- [ ] Verify the bot auto-sends the username (watch for your username appearing in the output echoed back)
- [ ] Verify the bot auto-sends the password
- [ ] Verify the bot detects the character selection prompt and sends the character name
- [ ] Verify the bot detects the MajorMUD menu and presses enter to continue
- [ ] **Verify `LoginHandler.in_game` triggers** — check if `:status` shows a room code

**What can go wrong:**

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot doesn't send username | Prompt text doesn't match regex | Edit `_USERNAME_RE` in `automation/login.py` to match your BBS |
| Bot sends username at wrong time | Regex fires on wrong line | Make the regex more specific |
| Character selection fails | Character name doesn't match the prompt's format | Try partial name, or update `_CHARACTER_RE` |
| Bot stuck after login | MajorMUD menu prompt doesn't match `_MAJORMUD_RE` | Add your server's actual prompt text |

**Debug tip:** If the bot isn't responding to prompts, type the response manually (without `:` prefix to send directly to the server). Note what the actual prompt text is, then update `login.py`.

**Record:** Copy the exact text of:
- Username prompt: `___________________________`
- Password prompt: `___________________________`  
- Character selection prompt: `___________________________`
- MajorMUD menu line: `___________________________`

---

## Phase 3: Room Detection (15 minutes)

**Goal:** The bot correctly identifies rooms from the output stream.

- [ ] Once in-game, move around (`n`, `s`, `e`, `w` in the command input)
- [ ] After each move, type `:status` — check if `Room:` shows a code (e.g. `Room:HOME`)
- [ ] Move to several different rooms and verify the code updates

**What can go wrong:**

| Symptom | Likely cause | Fix |
|---|---|---|
| `Room:?` after moving | Room name not in ROOMS.MD | Expected — only 543 rooms loaded. Rooms not in the DB won't register. |
| Room detection fires on wrong lines | Server sends room names in unexpected format | Check if names are ANSI-colored (we strip ANSI) or have extra spaces |

**Important test:** Find a room that IS in the DB. Type the room name from the output into a Python REPL:
```python
from mmud.data.rooms import load_rooms
import pathlib
rooms = load_rooms(pathlib.Path("extractions/mm103s.exe.extracted/45DAD/Default/ROOMS.MD"))
# Search for a known room
matches = [(c, r.name) for c, r in rooms.items() if "Silvermere" in r.name]
print(matches[:5])
```

- [ ] Move to one of those rooms, verify `:status` shows the code

**Record:** How many rooms in your starting area are recognized? What's the starting room code?

---

## Phase 4: Monster Detection (10 minutes)

**Goal:** The bot correctly reads monster names from room descriptions.

- [ ] Find a room with monsters
- [ ] After entering the room, type `:status` — check if `IN COMBAT` appears after a moment
- [ ] Observe what "Also here:" or "You notice" lines look like in the output

**What can go wrong:**

| Symptom | Likely cause | Fix |
|---|---|---|
| Monsters not detected | Room uses a format not covered by our parser | Note the exact line format, update `room_parser.py` |
| `monsters_present` wrong | Parser extracts currency/items as monsters | Update `_NON_MONSTER` regex in `room_parser.py` |

**Record:** Copy the exact room content lines showing monsters:
```
_________________________________________
_________________________________________
```

---

## Phase 5: Combat (20 minutes)

**Goal:** The bot fights a monster correctly.

- [ ] Set a low-level monster area and enter it manually
- [ ] Start combat manually: type `kill <monster>` in command input
- [ ] Observe: does the bot send subsequent attack commands each round?
- [ ] Verify flee triggers at low HP (set `flee_threshold = 0.50` temporarily for easier testing)
- [ ] Verify rest triggers after combat when HP is low

**With spell config:** Set `attack = "magic missile"` in config, reconnect, and verify the attack spell fires instead of bare melee.

**What can go wrong:**

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot sends `kill` but combat effect patterns don't fire | Server's combat messages don't match MESSAGES.MD | Need to compare real output to patterns |
| Bot doesn't know it's in combat | `CombatChanged` event not firing | Check `_parse_combat_exit` and `_process_line` with debug print |
| Bot never stops attacking | Combat exit phrases don't match | Note exact "breaks off combat" / "You have slain" text, update `_COMBAT_EXIT_RE` |
| Bot attacks but sends `kill` without monster name | Monsters not detected | See Phase 4 |

**Record:** Exact text of:
- Combat engaged message: `___________________________`
- Combat exit / monster death: `___________________________`

---

## Phase 6: Loop Navigation (30 minutes)

**Goal:** The bot runs a loop path automatically.

### 6a: Find a loop path in your area

```python
from mmud.data.paths import load_mp_file
import pathlib
DATA = pathlib.Path("extractions/mm103s.exe.extracted/45DAD/Default")
# Find loop paths (from == to)
loops = []
for mp in DATA.glob("*.MP"):
    try:
        p = load_mp_file(mp)
        if p.from_code == p.to_code and p.steps:
            loops.append((p.from_code, len(p.steps), mp.stem))
    except: pass
loops.sort(key=lambda x: x[1])
print(loops[:20])  # shortest loops first
```

- [ ] Run the above — note which loops exist and their step counts
- [ ] Pick a short loop (5-15 steps) in a safe area

### 6b: Start the loop

- [ ] Navigate manually to the loop's starting room
- [ ] Type `:loop XXXX` (the 4-letter code from above)
- [ ] Verify `:status` shows `Loop:XXXX lap:0`
- [ ] Watch the bot begin sending movement commands

**What to watch:**
- Does each movement command go out?
- Does the bot recognize when it returns to the starting room (lap count increases)?
- Does it handle "You can't go that way" by retrying?

**What can go wrong:**

| Symptom | Likely cause | Fix |
|---|---|---|
| `:loop XXXX` says "not found" | Path not loaded, or code wrong | Verify the 4-letter code exactly from the list above |
| Loop starts but never increments lap count | Room not in ROOMS.MD — `RoomChanged` never fires | Move manually to discover rooms; loop detection depends on room recognition |
| Bot gets stuck mid-path | "Can't go that way" not detected OR room requires special action | Note the blocker command, the path may need a different step |
| Commands sent too fast | Server can't keep up | (Future: add rate limiting) |

- [ ] With `auto_sneak = true`: verify `sneak` is sent before each step
- [ ] With `auto_start = true` in config: reconnect and verify loop starts automatically after login

---

## Phase 7: TUI Features (15 minutes)

**Goal:** Verify all TUI panels and commands work.

- [ ] **Conversations tab** (`Ctrl+1`): Send a tell to yourself from another client — verify it appears
- [ ] **Players tab** (`Ctrl+2`): Type `who` in command input — verify the online player list populates
- [ ] **Stats tab** (`Ctrl+3`): Verify HP/MP bars update after taking damage
- [ ] **Toggle panels**: `Ctrl+R` hides/shows right panel, `Ctrl+B` hides/shows stats bar
- [ ] **`:paths`**: Should list available loop paths
- [ ] **`:status`**: Should show current room, HP/MP, combat state
- [ ] **`:stop`**: Should stop any running loop

---

## Phase 8: Stress Test (30 minutes)

**Goal:** Run the bot for 30 minutes on a loop and observe stability.

- [ ] Set up a loop in a safe, low-level area with easy monsters
- [ ] Configure a heal spell and bless spell
- [ ] Start the loop with `:loop CODE`
- [ ] Leave it running for 30 minutes
- [ ] Monitor for: crashes, stuck states, memory growth, combat hangs

**Success criteria:**
- Lap count advances continuously
- HP stays above flee threshold (bot flees if needed)
- Bless spells fire (check if bless message appears in output)
- No Python exceptions in the terminal

---

## What to Record After the Session

Fill this in after your first test session:

### Login prompt patterns (for `login.py` tuning)
```
Username prompt:  
Password prompt:  
Character select:  
MajorMUD menu:    
```

### Room format (for `room_parser.py` tuning)
```
Room name format:           [bold? ANSI color? line by itself?]
"Also here:" format:        [exact example]
"Obvious exits:" format:    [exact example]
```

### Combat message patterns (for `_COMBAT_EXIT_RE` tuning)
```
Combat start:       
Monster death:      
"Breaks off combat":
```

### Issues found (one per line)
```
-
-
-
```

---

## Debugging Tips

**See what the bot is receiving:**
The TUI shows all raw output in the main window. If something isn't being parsed, look at the exact text.

**Test a pattern interactively:**
```python
from mmud.parser.room_parser import RoomParser
p = RoomParser({})
p.extract_monsters("Also here: A dark elf warrior, Krang Moan.")
```

**Test login regexes:**
```python
from mmud.automation.login import _USERNAME_RE, _PASSWORD_RE, _MAJORMUD_RE
_USERNAME_RE.search("Please enter your username:")
```

**Force a room lookup:**
```python
from mmud.data.rooms import load_rooms
import pathlib
rooms = load_rooms(pathlib.Path("extractions/mm103s.exe.extracted/45DAD/Default/ROOMS.MD"))
# Search by partial name
results = [(c, r.name) for c, r in rooms.items() if "hearth" in r.name.lower()]
print(results)
```

**Check loaded paths:**
```python
python -m mmud.tui --char characters/mychar.toml
# then in TUI: :paths
```

---

## After Testing: Tuning Checklist

Based on your session, update these files:

| File | What to tune |
|---|---|
| `src/mmud/automation/login.py` | `_USERNAME_RE`, `_PASSWORD_RE`, `_CHARACTER_RE`, `_MAJORMUD_RE` |
| `src/mmud/parser/room_parser.py` | `_ALSO_HERE_RE`, `_IS_HERE_RE`, `_NON_MONSTER` |
| `src/mmud/bot.py` | `_COMBAT_EXIT_RE`, `_NAV_FAIL_RE` |
| `src/mmud/parser/conversation_parser.py` | Channel formats if your server uses different bracket styles |
| `characters/mychar.toml` | Thresholds, spells, loop path |


---

# Part 2 — Live-Tuning Plan: Reconstructed Regexes

Most of the bot's line-matching regexes were reconstructed from the MegaMud
binary and from educated guesses about server wording, not from observed live
output. They are *load-bearing*: a missed onset line leaves a condition
untracked, a missed exits line stalls travel, a missed train line skips
training. This document lists every such pattern with its source `file:line`,
the **current** pattern quoted verbatim, and a blank **Real capture** slot to
fill in once you have seen the real server line.

## Tuning procedure (apply to every pattern below)

1. **Capture.** Trigger the event in-game (get poisoned, walk a room, open a
   door, train, backstab, etc.) and copy the *exact* server line — including
   punctuation and any leading whitespace — into the matching `Real capture:`
   slot below.
2. **Add a failing test.** Write a test that feeds that real line through the
   relevant parser/monitor and asserts the expected result. Prefer the
   transcript harness (`FakeConnection`) for bot-level flows, or a direct unit
   test for a standalone parser/regex.
3. **Run + adjust.** Run the test (`python -m pytest tests/<file>.py -q`),
   watch it fail, then adjust the regex *minimally* so the real line matches
   while existing tests stay green. Re-run the whole suite (`python -m pytest -q`).
4. **Commit.** Commit the pair together:
   `test+fix: tune <pattern> against live capture`.

Keep edits minimal — widen alternations or relax anchors only as far as the
real line demands; do not rewrite a working pattern.

---

## 1. Conditions onset / recovery

**File:** `src/mmud/state/conditions.py`

`ONSET_PATTERNS` (lines 17–24):

- L18 POISONED — `r"you (?:are|have been|feel) .*poison"`
- L19 DISEASED — `r"you (?:are|have been) diseased|you feel very ill"`
- L20 HELD — `r"you (?:are|have been) (?:held|paralyzed)|you cannot move"`
- L21 STUNNED — `r"you (?:are|have been) stunned|you see stars"`
- L22 BLIND — `r"you (?:are|have been|go) blind|you cannot see"`
- L23 CONFUSED — `r"you (?:are|feel) confused|your head spins"`

`RECOVERY_PATTERNS` (lines 26–33):

- L27 POISONED — `r"poison has worn off|poison leaves? your"`
- L28 DISEASED — `r"you feel healthy again|disease has been cured"`
- L29 HELD — `r"you can move again|no longer (?:held|paralyzed)"`
- L30 STUNNED — `r"no longer stunned|your head clears"`
- L31 BLIND — `r"you can see again|your (?:sight|vision) returns"`
- L32 CONFUSED — `r"no longer confused|your mind clears"`

All compiled `re.IGNORECASE`, matched with `.search()`.

Real capture (onset, per condition):
- POISONED: ___
- DISEASED: ___
- HELD/paralyzed: ___
- STUNNED: ___
- BLIND: ___
- CONFUSED: ___

Real capture (recovery, per condition):
- POISONED: ___
- DISEASED: ___
- HELD/paralyzed: ___
- STUNNED: ___
- BLIND: ___
- CONFUSED: ___

---

## 2. Inventory — carrying / wearing / wealth / encumbrance

**File:** `src/mmud/parser/inventory_parser.py`

Current (all anchored at `^`, `re.IGNORECASE`, matched with `.match()`):

- L5  `_CARRYING_RE` — `r"^You are carrying\s+(.*)$"`
- L6  `_WEARING_RE` — `r"^You are wearing\s+(.*)$"`
- L7–8 `_WEALTH_RE` — `r"^Wealth:\s+(\d+)\s+(copper|silver|gold|platinum|runic)"`
- L9–10 `_ENCUMBRANCE_RE` — `r"^Encumbrance:\s+(\d+)/(\d+)\s*-\s*(\w+)\s*\[(\d+)%\]"`
- L11 `_COUNT_ITEM_RE` — `r"^(\d+)\s+(.*)$"` (leading "N <item>" count)
- L12 `_ARTICLE_RE` — `r"^(?:a|an|the|some)\s+"` (article stripper)
- L13–14 `_COIN_RE` — `r"^(\d+)\s+(copper|silver|gold|platinum|runic)\b"`
- L18 item splitter (inline) — `re.split(r",\s*|\s+and\s+", ...)`

Note: wrapped carrying/wearing continuation lines are matched by a
`line.startswith(" ")` check (L61), not a regex.

Real capture:
- `You are carrying` line: ___
- `You are wearing` line: ___
- `Wealth:` line: ___
- `Encumbrance:` line: ___
- A wrapped continuation line (leading spaces): ___

---

## 3. Loot — "You notice ... here."

**File:** `src/mmud/automation/items.py`

Current:

- L14 `_NOTICE_RE` — `r"^You notice (.+?) here\.?$"` (`re.IGNORECASE`, `.match()`)
- L15–16 `_COIN_RE` — `r"^(\d+)\s+(copper|silver|gold|platinum|runic)\b"`
- L17 `_ARTICLE_RE` — `r"^(?:a|an|the|some)\s+"`
- L18 `_CANT_GET_RE` — `r"you can'?t (?:get|take|pick up)"` (used from `bot.py` L502)
- L35 list splitter (inline) — `re.split(r",\s*|\s+and\s+", m.group(1))`

Real capture:
- Single-item notice: ___
- Multi-item notice (comma/and list): ___
- Coins-on-ground notice: ___
- A "can't get" refusal line: ___

---

## 4. Exits — "Obvious exits:" (also the arrival signal)

**File:** `src/mmud/parser/exits_parser.py`

Current:

- L4 `_EXITS_RE` — `r"^Obvious exits:\s*(.+?)\.?$"` (`re.IGNORECASE`, `.match()` on the stripped line)
- L30 direction splitter (inline) — `re.split(r",\s*|\s+and\s+", body)`

This line doubles as the **arrival signal** for unnamed rooms (~88% of the
graph); `TravelDecider` advances on it, so tuning this also tunes travel. A
body of `none` yields `[]` (no exits).

Real capture:
- Multi-exit line: ___
- `none` line: ___
- Single-exit line: ___

---

## 5. Doors — closed / locked

**File:** `src/mmud/automation/doors.py`

Current (both `re.IGNORECASE`, matched with `.search()`):

- L6 `_CLOSED_RE` — `r"(?:the )?door is closed|it'?s closed"`
- L7 `_LOCKED_RE` — `r"(?:the )?door is locked|it'?s locked"`

Locked is checked before closed; a match drives `open`/`pick`/`bash <dir>`.

Real capture:
- Door-closed line: ___
- Door-locked line: ___

---

## 6. Party — member row / leader / invite / leader-hit

**File:** `src/mmud/parser/party_parser.py`

- L7  `_NOT_IN_PARTY_RE` — `r"You are not in a party"`
- L8  `_LIST_HEADER_RE` — `r"The following people are in your"`
- L9  `_FOLLOWING_RE` — `r"^You are following\s+(\w+)"`
- L13–20 `_ROW_RE` (RECONSTRUCTED member-row layout):

```
^\s*([A-Z][\w']*)            # first name
(?:\s+[A-Z][\w']*)?          # optional surname
\s+\[([^\]]+)\]              # [Class]
\s+\[\s*(\d+)\]              # [HP%]
(?:\s+\[\s*(\d+)\])?         # [MP%] (optional)
(?:\s+(P))?\s*$              # leader/rank flag
```

The header/not-in/following anchors are noted in source as EXACT anchors from
`party_list_parse @ 0x004618e0`; the **row layout is reconstructed** and is the
highest-risk pattern here — verify field order/brackets against a live
`party`/`who` listing.

**File:** `src/mmud/automation/party.py`

- L14 `_INVITE_RE` — `r"(\w+) has invited you to join"` (`.search()`)
- L15–16 `_LEADER_HIT_RE` (newly added) —
  `r"\b(?:swings?|attacks?|hits?|strikes?|slashes?|casts?)\b"`
  Used in `on_line` (L52–57): the line must *start* with the escaped leader
  name (`re.match(rf"{leader}\b", ...)`) **and** `_LEADER_HIT_RE.search(line)`
  must hit, to set `leader_engaged`.

Real capture:
- A party member row (verbatim, preserve spacing/brackets): ___
- The list header line: ___
- `You are following <name>` line: ___
- `not in a party` line: ___
- An invite line: ___
- A leader-acting-in-combat line (leader name + verb): ___

---

## 7. Commerce — train ready/done + bank/shop/share command syntax

**File:** `src/mmud/automation/commerce.py`

Line monitors (`re.IGNORECASE`, `.search()`):

- L15–17 `_TRAIN_READY_RE` —
  `r"enough experience to advance|you may now advance|ready to train"`
- L18–19 `_TRAIN_DONE_RE` —
  `r"you advance to level|you are now level|welcome to level"`

Outbound **command syntax** generated by `_build_work` (verify the server
accepts these exact verbs/forms):

- deposit — `f"deposit {k} {denom}"` (L138)
- withdraw — `f"withdraw {need} copper"` (L143)
- sell — `f"sell {i.lower()}"` (L146)
- buy — `f"buy {i.lower()}"` (L150)
- train — `"train"` (L153)

**File:** `src/mmud/automation/party.py` — share command syntax:

- share — `f"share {n} {denom}"` (L105)

Real capture / verification:
- Train-ready line: ___
- Train-complete line: ___
- Bank deposit accepted? (command echo / confirmation): ___
- Bank withdraw accepted?: ___
- Shop sell accepted?: ___
- Shop buy accepted?: ___
- `train` accepted?: ___
- `share` accepted?: ___

---

## 8. Backstab — hide / sneak / backstab stage lines

**File:** `src/mmud/combat/backstab.py`

All `re.IGNORECASE`, matched with `.search()`:

- L10 `_HIDE_OK_RE` — `r"slip into the shadows|you are hidden"`
- L11 `_HIDE_FAIL_RE` — `r"fail to hide|can'?t hide"`
- L12 `_SNEAK_OK_RE` — `r"move silently|begin to sneak"`
- L13 `_SNEAK_FAIL_RE` — `r"fail to sneak|make a noise"`
- L14 `_BS_OK_RE` — `r"plant your weapon|backstab.*for \d+"`
- L15 `_BS_FAIL_RE` — `r"backstab attempt fails|fails? to find an opening"`

Note: the hide/sneak success/fail wording overlaps with the combat-engine sneak
patterns in area 10 — capture once and tune both call sites consistently.

Real capture:
- Hide success: ___
- Hide fail: ___
- Sneak success: ___
- Sneak fail: ___
- Backstab success (with damage): ___
- Backstab fail: ___

---

## 9. Combat — player-hit / miss / monster-hit / backstab

**File:** `src/mmud/bot.py` (combat-stat regexes near the top)

- L36 `_HP_RE` — `r"\[HP=(\d+)/(\d+)\]"` (prompt HP, `.search()`)
- L37 `_MP_RE` — `r"\[MP=(\d+)/(\d+)\]"` (prompt MP)
- L38 `_ANSI_RE` — `r"\x1b\[[0-9;]*m"` (ANSI strip)
- L39–44 `_COMBAT_EXIT_RE` —
  `r"breaks off combat|Combat Engaged:\s*Off|You have (?:slain|killed)|falls? to the ground|(?:is|are) dead\b"`
- L45–49 `_NAV_FAIL_RE` —
  `r"(?:you can'?t go that way|alas|there is no exit|you cannot go that direction|no exit|blocked|closed)"`
- L50 `_PLAYER_HIT_RE` —
  `r"You (?:hit|strike|slash|pierce|bash|backstab)\w* \w.+? for (\d+) damage"`
- L51 `_PLAYER_MISS_RE` — `r"You miss\b"`
- L52 `_MONSTER_HIT_RE` —
  `r"(?:hits?|strikes?|slashes?|bashes?|pierces?) you for (\d+) damage"`
- L53 `_BACKSTAB_RE` — `r"You backstab"`

All combat lines `re.IGNORECASE`, `.search()`. `_PLAYER_HIT_RE` captures damage
in group 1; `_BACKSTAB_RE` tags the hit as a backstab.

Real capture:
- Prompt line showing `[HP=.../...]` (and `[MP=.../...]`): ___
- A player-hit line (with damage): ___
- A player-miss line: ___
- A monster-hit line (with damage): ___
- A player-backstab line: ___
- A kill / combat-exit line: ___
- A movement-blocked / nav-fail line: ___

---

## 10. Sneak ok / fail (combat engine)

**File:** `src/mmud/combat/combat.py`

Newly added, `re.IGNORECASE`, `.search()`:

- L6 `_SNEAK_OK_RE` — `r"move silently|begin to sneak"`
- L7 `_SNEAK_FAIL_RE` — `r"fail to sneak|make a noise"`

Identical wording to the backstab-engine sneak patterns (area 8); when
`must_sneak` is set, success sets `_sneak_confirmed` and a fail clears
`_sneaked_this_encounter`. Tune in lockstep with area 8.

Real capture:
- Sneak success: ___
- Sneak fail: ___
