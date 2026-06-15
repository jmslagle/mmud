# mmud — MegaMud Python Port

A Python reimplementation of MegaMud, the legendary MajorMud automation client. Connects to a MajorMud BBS server, parses the game output, and automates combat, navigation, and looping — with a Textual TUI.

Built by reverse engineering megamud.exe using Ghidra (400+ functions annotated).

---

## Installation

**Requires Python 3.11+**

```bash
git clone <repo>
cd mmud
pip install -e ".[dev]"
```

Verify:
```bash
python -m mmud.tui --help
pytest
```

---

## Quick Start

### 1. Create a character config

```bash
cp characters/example.toml characters/mychar.toml
$EDITOR characters/mychar.toml
```

Minimum config:
```toml
[server]
host = "your.mud.server.com"
port = 23

[login]
username  = "yourbbs"
password  = "yourpass"
character = "Your Character"
```

### 2. Launch the TUI

```bash
# With a config file:
python -m mmud.tui --char characters/mychar.toml

# Override server on the command line:
python -m mmud.tui --host mud.example.com --port 23 --char characters/mychar.toml

# No config (manual play, no automation):
python -m mmud.tui --host mud.example.com --port 23
```

### 3. Connect and play

Press `Ctrl+K` to connect, or type `:connect`.

The bot auto-logs in if `[login]` is configured, then starts the configured loop path if `auto_start = true`.

---

## TUI Layout

```
┌─ View  Action  Options  Help ─────────────────────────────────────┐
│                                          │ [Conversations][Players]│
│  MAIN GAME OUTPUT                        │  [Stats]                │
│  (scrolling MUD text)                    │                         │
│                                          │  Tab content            │
│                                          │                         │
├─────────────────────┬────────────────────┴─────────────────────────┤
│ HP ████░ 141/216    │ kills: 12  exp: 52497  loop: RHU2LOOP lap:5  │
│ MP █████  89/120    │ hit_pct: 72%  avg_dmg: 31                    │
├─────────────────────┴──────────────────────────────────────────────┤
│ > _                         F1:menu  Ctrl+1-3:tabs  Ctrl+R  Ctrl+B │
└────────────────────────────────────────────────────────────────────┘
```

### Keyboard shortcuts

| Key | Action |
|---|---|
| `Ctrl+K` | Connect / disconnect |
| `Ctrl+L` | Start / stop loop |
| `Ctrl+R` | Toggle right panel |
| `Ctrl+B` | Toggle stats bar |
| `Ctrl+1` | Conversations tab |
| `Ctrl+2` | Players tab |
| `Ctrl+3` | Stats tab |
| `Ctrl+O` | Open the settings editor (edit + save config without leaving the TUI) |
| `F1` | Menu |
| `Escape` | Clear input |

### In-app configuration

Press `Ctrl+O` to open a tabbed settings screen (General / Display / Combat /
Spells / Health / Events / Stealth / Items / Party) listing every scalar config
field. Edit a value and press Enter to apply it to the live config immediately;
press `Ctrl+S` (or the Save button) to write it back to your character `.toml`,
**preserving comments and any keys the schema doesn't know about**. No restart,
no hand-editing required. The same change is also reachable remotely via `@set`
/ `@save` (below) — all edit paths funnel through one validated service, so a
change made anywhere is type-checked and broadcast to every open panel.

---

## Web Control Panel (browser UI)

An optional browser UI that mirrors MegaMud's multi-window layout — a game
terminal, conversations, player/session statistics, an online-players list, and
quick-tools (a compass plus action buttons). It is driven live by the same
`GameEventBus` that powers the TUI, so both stay in sync. It is **off by
default**.

### Install

```
# Python extras (FastAPI + uvicorn):
python -m pip install -e '.[web]'
```

```
# Build the SPA (one time, or after frontend changes):
cd src/mmud/web/frontend
npm install
npm run build
```

### Enable

Add to the character `.toml`:

```
[web]
enabled = true
host    = "127.0.0.1"   # localhost only — see SECURITY below
port    = 8080
```

### Launch

Run the TUI as usual and connect:

```
python -m mmud.tui --char characters/yours.toml
```

When `[web].enabled = true` the bot starts the panel automatically — open
<http://127.0.0.1:8080>. The built SPA is served by FastAPI from
`src/mmud/web/frontend/dist`. For frontend development with hot reload, run
`npm run dev` in the frontend dir; it proxies `/api` and `/ws` to port 8080.

### SECURITY

The panel binds to `127.0.0.1` (localhost) by default and is
**UNAUTHENTICATED**. It can send game commands and edit your config. Do **not**
set `host` to `0.0.0.0` or expose the port publicly without an authenticating
reverse proxy or an SSH tunnel — anyone who can reach the port can drive your
character.

---

## Terminal emulation

MajorMUD/Worldgroup is a full-screen ANSI BBS app: the in-game editor, menus,
and scroll displays position the cursor to arbitrary row/col and redraw in
place. An append-only log cannot show these cross-line redraws, so both
frontends run a real screen-buffer terminal emulator over the connection's RAW
byte stream (post-telnet-IAC, pre-line-framing):

- **TUI:** `src/mmud/terminal.py` (`TerminalEmulator`, a pyte `HistoryScreen`)
  drives `TerminalView` — a live 80×24 screen with colour from pyte's per-cell
  buffer and PageUp/PageDown scrollback. Character mode (Tab to focus, raw
  keystrokes for the in-game editor) is preserved.
- **Web:** the raw stream is broadcast as `RawOutput` events and written
  straight into an `@xterm/xterm` terminal, which owns its own buffer.

### Display / semantics split

This is the key architecture. Raw bytes drive the terminal **DISPLAY** (pyte /
xterm.js). The existing line parser keeps driving **SEMANTICS** independently:
`MudBot._process_line` still runs the full parser pipeline and emits
`LineReceived`, `HpChanged`, `RoomChanged`, `ConversationReceived`, etc., which
feed the stats/conversations/players panels and all automation. The terminal
display and the event-driven semantics are two parallel consumers of the same
connection.

### Phase 2 (future, NOT implemented)

Today the parsers read framed lines (cursor moves replayed per-line by
`src/mmud/parser/ansi.py`). A future phase can migrate the line parsers to read
the emulator's `screen.display` rows instead — cursor-proof parsing of
full-screen redraws (room panes, the editor, scroll output) — and then retire
`parser/ansi.py`. This is intentionally deferred: it touches every parser and
the whole semantics test surface, and the current per-line parsing already
passes the suite.

---

## Bot Commands

Type `:command` in the command input to control the bot without sending to the server.

| Command | Description |
|---|---|
| `:loop [NAME]` | Start a loop path. Optional name overrides config. |
| `:stop` | Stop loop, clear command queue |
| `:goto CODE` | Navigate to a room by 4-letter code (e.g. `:goto CLKR`) |
| `:paths` | List all available loop paths |
| `:status` | Show room, HP/MP, loop state, combat flag |
| `:connect` | Connect to server |
| `:disconnect` | Disconnect |
| `:help` | Show command reference |

Anything **without** a `:` prefix is sent directly to the MUD server.

---

## @-Commands (remote control)

Trusted players can drive the bot from another character by sending it a **tell**
whose text begins with `@`. This is off by default — enable it and grant
permissions explicitly:

```toml
[remote]
enabled     = true
tell_format = "/{name} {text}"   # adjust to your server's telepath reply syntax

[[players]]
name        = "MyAltChar"
friend      = true
remote_cmds = ["*"]              # allow every verb, or list specific ones
```

Permission is per-player: a sender must match a `[[players]]` rule whose
`remote_cmds` contains the verb (without the `@`) or `"*"`. **Unknown players are
ignored silently** — no reply is sent, so the bot never reveals itself to
strangers. A known player who lacks a verb gets a `permission denied` reply.

> **`@set` is powerful.** It can change *any* scalar field, including
> `login.password`. Only grant `"set"`/`"save"` (or `"*"`) to characters you
> fully trust, and remember `@set` changes are live immediately but only written
> to disk on an explicit `@save`.

| Verb | Action |
|---|---|
| `@status` | Reply with room, HP/MP, loop state, combat flag |
| `@health` | Reply with `HP cur/max MP cur/max` |
| `@loop NAME` | Start loop path `NAME` |
| `@stop` | Stop the loop and clear the command queue |
| `@goto CODE` | Navigate to a room by 4-letter code |
| `@kill TARGET` | Enqueue an attack on `TARGET` |
| `@hangup` | Disconnect immediately |
| `@panic!` | Send the configured `[safety] panic_cmd`, then disconnect |
| `@auto-sneak [on\|off]` | Toggle `[stealth] auto_sneak` (no arg = flip) |
| `@auto-hide [on\|off]` | Toggle `[stealth] auto_hide` |
| `@auto-get [on\|off]` | Toggle `[items] auto_get` |
| `@auto-cash [on\|off]` | Toggle `[items] auto_cash` |
| `@set SECTION.FIELD VALUE` | Edit any scalar config field live (e.g. `@set combat.flee_threshold 0.25`); type-checked |
| `@save` | Persist the current config back to the character `.toml` |
| `@wealth` | Report carried wealth (copper-equivalent + per-denomination) |
| `@db` | Report game-DB store stats (records / learned exits / collisions) |
| `@rate` | Report exp/hour and session length |
| `@relog` | Log out cleanly and log back in (fresh session) |
| `@invite` | Invite the sender to your party |
| `@wait` / `@rego` | Pause / resume (party wait protocol) |
| `@share [args]` | Share cash with the party |
| `@forget` | Drop tracked party state |
| `@events` | List scheduled timed events with next-fire countdowns |

The original MegaMud exposed ~47 verbs; the rest (e.g. `@relog`, party verbs)
arrive as later phases wire up the subsystems they drive.

---

## Game DB store (`[learning]`)

With `[learning] enabled = true` the bot keeps its **own JSON game database**
(default `gamedb.json`) instead of reading the binary `.MD` files directly each
run:

- On startup the binary databases (`MONSTERS.MD`, `ITEMS.MD`, `SPELLS.MD`,
  `PLAYERS.MD`) are **converted and merged in** — the `.MD` files are **never
  written**. Each source is fingerprinted (sha256+size); an unchanged source is
  skipped for an instant start.
- When a source changes, records are merged per id: plain MD records follow the
  source, while records you've **learned or overridden** locally survive. If the
  MD side of an overridden record also changed, that's a **collision** — the
  local value wins and the new MD version is logged in the store's `collisions`
  list for review.
- Live learning persists here too: unknown monsters seen in rooms, plus
  `ungettable` / `no_auto_equip` marks. Phase 6 will also persist learned room
  exits in the same store.
- Text sources (`.MP` paths, `ROOMS.MD`, `MESSAGES.MD`) are **not** imported —
  they stay directly-read at runtime.

Check the store live with the `@db` remote verb. Deleting `gamedb.json` rebuilds
it from the `.MD` files on the next start (losing learned data and overrides).

---

## Commerce detours (`[commerce]`)

When configured, the bot interrupts its loop to run errands, then resumes:

- **Bank** (`bank_room`) — deposits when wealth exceeds `[items] max_wealth`
  (down to `min_wealth`), or withdraws when below `min_wealth`.
- **Shop** (`shop_room`) — sells anything in `sell_items` it's carrying, buys
  anything in `buy_items` it lacks.
- **Train** (`train_room` + `auto_train`) — walks to the trainer when the server
  says you're ready to advance.

Each errand is a Phase-6 multi-hop travel detour: leave the loop → walk to the
room → do the work (one command per tick) → `inv` re-sync → resume the loop.
Commerce only triggers on fresh inventory data (never mid-travel or in combat),
and an unroutable room disables that errand instead of retrying. Rooms are
4-letter codes; `""` disables an errand.

```toml
[commerce]
bank_room  = "BANK"
shop_room  = "SHOP"
train_room = "TRNR"
sell_items = ["rusty sword"]
buy_items  = ["torch"]
auto_train = true
```

> Live-tune caveat: the `deposit`/`withdraw`/`sell`/`buy`/`train` command syntax
> and the "ready to advance" line are reconstructed — verify against your server
> and adjust `src/mmud/automation/commerce.py` if needed.

---

## Session management (`[session]`)

Session-scope safety and observability:

- **`capture_file`** — append every raw server line (ANSI preserved) to a log.
- **`min_exp_rate`** — exp/hour floor. After a `grace_minutes` warmup, if the
  rate drops below this, the bot performs `low_rate_action` (`"hangup"` or
  `"relog"`). Check the current rate any time with the `@rate` verb.
- **`max_hours_per_day`** — hang up after this many hours connected (0 = no
  limit).
- **Relog** (`@relog`, or the low-rate action) is a deliberate logout-and-return:
  it sends `logout_cmd`, then reconnects and logs in from scratch — a separate
  path from `[safety] reconnect`, which only covers *unexpected* connection loss.

```toml
[session]
capture_file      = "session.log"
max_hours_per_day = 4
min_exp_rate      = 5000
grace_minutes     = 15
low_rate_action   = "relog"
logout_cmd        = "x"
```

> Live-tune caveat: `logout_cmd` must cleanly exit the game — MajorMUD uses `x`
> at the prompt, but some BBS menus need `=x` or similar.

---

## Party support (`[party]`)

The bot tracks your party from the party-list output (`"The following people are
in your party:"` / `"You are following <Name>."` / `"You are not in a party"`)
and, when configured, looks after the group:

- **Heal** the lowest member below `heal_hp_pct` with `heal_spell` (skips
  players marked `dont_heal` in `[[players]]`).
- **Wait/resume** — if a member drops below `wait_hp_pct`, send `wait_cmd` and
  hold (pinning combat/travel) until everyone recovers, then `resume_cmd`.
- **Bless** — cast each `[[party.bless]]` command on its `wait_seconds` cooldown.
- **Share cash** — when `share_cash`, hand coins to the party after combat.
- **Status refresh** — re-issue `status_cmd` every `status_interval_s` to keep
  member HP current.
- **Auto-join** — accept party invites from players marked `friend = true`.

Party automation engages only when `heal_spell` or `status_cmd` is set; control
it live with `@invite`/`@wait`/`@rego`/`@share`/`@forget`.

> Live-tune caveat: the party member-ROW format (name / `[class]` / `[HP%]`
> `[MP%]` columns) is reconstructed — capture your server's real party output
> and tune `_ROW_RE` in `src/mmud/parser/party_parser.py`. The `join`/`share`/
> `wait`/`go` command syntax is likewise reconstructed.

---

## Timed events (`[schedule]`) & macros

`[[schedule.events]]` runs commands on a timer — the TOML form of the original's
`.ini [Schedule] EventN = type:interval:count:command` entries. Six event types:

| `type` | Action |
|--------|--------|
| `command` | Expand `arg` as a template and send it |
| `goto` | Navigate to room `arg` (multi-hop) |
| `loop` | Switch the active loop to path `arg` |
| `relog` | Log out and back in (Phase 9 relog flow) |
| `logoff` | Log out and disconnect |
| `logon` | (no-op while connected — reconnect/relog own the lifecycle) |

`every_seconds` sets the interval; `count` limits firings (`0` = forever).
List the live schedule with `@events`.

```toml
[[schedule.events]]
type          = "relog"
every_seconds = 14400      # every 4 hours
count         = 0
[[schedule.events]]
type          = "command"
every_seconds = 300
arg           = "gossip still here||gossip anyone about?"   # random alternative
```

**Command templates** (used by `command` events) support the original's syntax:
`||`-separated random alternatives, `{userid}`/`{pswd}`/`{target}`/`{dmg}`/`{p1}`–`{p5}`
substitution tokens, and `^X` control escapes (`^M` = press enter).

**Macros:** `MACROS.MD` (text) maps numpad keys to commands — in the TUI, the
numpad block (with NumLock off) fires movement/`rest` hotkeys.

> Live-tune caveat: terminal numpad key names vary by emulator (`kp_0`-style are
> Textual's); adjust `_VK_KEYS` in `src/mmud/data/macros_md.py` if they don't match.

---

## Character Config Reference

All sections are optional. Missing keys use safe defaults. `--host` / `--port` CLI args override `[server]`.

```toml
[server]
host = "mud.example.com"
port = 4000

[login]
username  = "bbs_login"
password  = "password"
character = "Character Name"   # matched against character-select prompt

[combat]
attack_cmd      = "kill"       # command sent to attack (e.g. "kill", "attack")
flee_threshold  = 0.15         # flee when HP drops below 15%
rest_threshold  = 0.40         # rest out-of-combat when HP below 40%
backstab        = false
polite_attacks  = false        # don't attack with non-party players in room
attack_order    = "first"      # "first" | "last" | "reverse"
mana_attack_pct = 0.20         # don't attack if mana below 20%

[spells]
attack        = ""             # e.g. "magic missile" — cast in combat each tick
pre_attack    = ""             # cast just before engaging a monster
multi_attack  = ""             # area-effect spell (unused in current version)
heal          = ""             # e.g. "cure light wounds"
heal_hp_pct   = 0.50           # heal when HP below this %
mana_heal     = ""             # e.g. "meditate"
mana_heal_pct = 0.30           # meditate when mana below this %

# Up to 10 bless spells, each with its own mana threshold and 600-second cooldown:
[[spells.bless]]
cmd      = "bless"
mana_pct = 0.80                # only cast when mana >= 80%

[[spells.bless]]
cmd      = "protection"
mana_pct = 0.75

[stealth]
auto_sneak  = false            # sneak before each loop step and before attacking
sneak_cmd   = "sneak"
must_sneak  = false            # halt movement if sneak fails (not yet implemented)
auto_hide   = false
hide_cmd    = "hide"

[navigation]
loop_path        = ""          # 4-letter room code (loop paths: from==to) or 8-char stem
start_room       = ""          # room code to start from (informational)
auto_start       = false       # start loop immediately on game entry
flee_rooms       = 3           # rooms to run on panic flee (not yet implemented)
can_pick_locks   = false
can_disarm_traps = false

[items]
auto_get         = false       # auto-get items (not yet implemented)
auto_cash        = true        # auto-get coins (not yet implemented)
collect_copper   = true
collect_silver   = true
collect_gold     = true
collect_platinum = true
collect_runic    = false
dont_go_heavy    = true

[party]
heal_spell         = ""
heal_hp_pct        = 0.50
wait_hp_pct        = 0.30
wait_max_seconds   = 30
attack_with_leader = true
share_cash         = false

[[party.bless]]
cmd          = "party bless"
wait_seconds = 60

[afk]
enabled          = false
timeout_minutes  = 5
reply            = "I am AFK"
hangup_on_low_hp = false        # disconnect if HP drops below flee_threshold while AFK
popup_missed     = true

[health]
# Cure commands sent automatically when a condition is detected (blank = don't cure):
blind_cmd   = ""               # e.g. "cast purify vision"
poison_cmd  = ""               # e.g. "cast neutralize poison"
disease_cmd = ""
freedom_cmd = ""               # break hold/paralysis

[safety]
hangup_on_death = true
hangup_players  = []           # disconnect if any of these appear in the room
panic_cmd       = ""           # sent before a panic hangup (e.g. "recall")
reconnect       = false        # auto-reconnect on connection loss
max_redials     = 3

[remote]
enabled     = false            # allow trusted players to drive the bot via @-tells
tell_format = "/{name} {text}" # reply template; adjust to your server's telepath syntax

# Per-player rules (one block per player):
[[players]]
name        = "FriendName"
friend      = true
remote_cmds = ["*"]            # allowed @-verbs (without the @), or ["*"] for all
dont_heal   = false
dont_bless  = false

[ui]
show_right_panel = true
show_stats_bar   = true
default_tab      = "conversations"   # "conversations" | "players" | "stats"
```

---

## Architecture

```
MudConnection (asyncio TCP)
    │
    ▼
MudBot._process_line()
    ├── LoginHandler          — BBS prompt matching, auto-login
    ├── RoomParser            — room name → code, monster detection
    ├── PatternMatcher        — MESSAGES.MD effect patterns
    ├── ConversationParser    — tell/shout/party parsing
    ├── WhoParser             — WHO list → PlayerSeen events
    └── combat/nav exit detection
    │
    ▼
GameState (HP, mana, room, effects, monsters, combat stats, queue)
    │
    ▼
MudBot._next_command()  →  DecisionEngine.next_command()
    │  Priority decider chain (src/mmud/automation/decision.py) with a task
    │  state machine (src/mmud/state/tasks.py), mirroring the original MegaMud
    │  "DoSomething" loop. First non-None command wins; an active task pins
    │  lower-priority slots and is preempted (aborted) by any higher-priority one.
    │  Current slots: queue (0) → SpellEngine (30) → CombatEngine (40).
    │  Reserved for later phases: cures, flee, rest, refresh, equip, items,
    │  party, travel, search.
    │
    ▼
GameEventBus → Textual TUI widgets (GameOutput, StatsBar, RightPanel)
```

**Loop runner** (background): subscribes to `RoomChanged` events. On arrival at the loop destination, re-enqueues the path steps for the next lap.

**1Hz ticker** (background asyncio task): advances spell cooldowns, checks AFK timeout.

---

## Game Data Files

The bot loads game data from `extractions/mm103s.exe.extracted/45DAD/Default/`:

| File | What it contains | Format |
|---|---|---|
| `MESSAGES.MD` | 404 spell/effect patterns | Text: `name:flags:\napply_msg\nremove_msg` |
| `ROOMS.MD` | 543 room definitions | Text: `HexID:HexID:flags:Code:Region:Name` |
| `*.MP` (1,198 files) | Navigation paths | Text: bracketed from/to + step commands |
| `MONSTERS.MD` | 788 monster records | MDB2 B-tree (210-byte payload) — see [docs/cdb-mdb2-format.md](docs/cdb-mdb2-format.md) |
| `ITEMS.MD` | 667 active item records (1,336 entries) | MDB2 B-tree (200-byte payload) |
| `SPELLS.MD` | 936 spell records | MDB2 B-tree (158-byte payload) |

---

## Known Limitations (v0.1)

- **Room database is incomplete** — only 543 rooms from the Default/ extraction. Unknown rooms won't trigger `RoomChanged` events, so loop detection may miss arrivals in unknown areas. Mitigation: move through the area manually first to "discover" rooms.
- **Login prompts are server-specific** — the auto-login regex patterns work for standard MajorMud but may need tuning for your BBS configuration.
- **No auto-cash/loot collection yet** — `auto_cash` and `auto_get` config exists but the bot doesn't issue `get coin` commands.
- **No multi-hop pathfinding** — `:goto CODE` only works if there's a direct `.MP` file between your current room and the destination.
- **Pattern matching is regex-based** — the original used literal substring matching. Complex patterns with `{target}` may behave slightly differently.
- **Never tested against a live server** — this is v0.1. Expect to tune prompt patterns and combat messages after your first session.

---

## Development

```bash
pytest                  # run all 139 tests
pytest -v --tb=short    # verbose
python -m mmud.tui --help
```

Source layout:
```
src/mmud/
  data/         — file parsers (messages, rooms, paths, binary)
  parser/       — pattern matcher, room parser, conversation parser, WHO parser
  state/        — GameState
  net/          — TCP connection
  combat/       — CombatEngine
  navigation/   — Navigator, paths
  automation/   — LoginHandler, LoopRunner, SpellEngine
  config/       — TOML schema + loader
  events.py     — GameEventBus + event dataclasses
  bot.py        — MudBot (orchestrates everything)
  tui/          — Textual app + widgets
  web/          — placeholder for future web UI
```
