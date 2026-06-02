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
Expected: 139 passed. If any fail, don't proceed — fix the environment first.

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
