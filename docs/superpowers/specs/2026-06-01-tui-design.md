# MegaMud TUI Design Spec

## Goal

Add a terminal user interface to the MegaMud Python bot client. The TUI wraps the existing bot infrastructure (MudBot, GameState, PatternMatcher, Navigator, CombatEngine) and adds a character config system. Architecture is designed to support a future web UI over the same event bus.

---

## Technology

- **Textual** — async-native Python TUI framework. Shares the bot's asyncio event loop. No threading required.
- **TOML** — character config files (one per character).
- **Entry point** — `python -m mmud.tui --host <host> --port <port> [--char <path.toml>]`

---

## Architecture

```
MudConnection ──► MudBot ──► GameEventBus ──► Textual widgets (TUI)
                                          └──► WebSocket clients (future web UI)
```

- `GameEventBus` is a protocol-agnostic pub/sub system with two methods: `bus.subscribe(EventType, callback)` and `bus.post(event)`. Callbacks are called synchronously in the asyncio event loop — no threading.
- `MudBot` emits events after each state change. It accepts an optional `event_bus` parameter; when `None` the existing behaviour is unchanged (all 35 tests continue to pass).
- Textual widgets subscribe to events via Textual's `Message` system, bridged from the bus in `app.py`.
- A future `mmud/web/` module would subscribe to the same events and forward them over WebSockets.

---

## Layout

Option C — main output left, tabbed right panel, compact stats bar above the command input.

```
┌─────────────────────────────────────────────────────────────────┐
│ View  Action  Options  Help        MegaMud TUI — [Spawn DaPrawn]│
├──────────────────────────────────┬──────────────────────────────┤
│                                  │ [Conversations][Players][Stats]│
│  MAIN GAME OUTPUT                │                              │
│  (scrolling RichLog,             │  Tab content:                │
│   ANSI colour preserved)         │  • Conversations: RichLog    │
│                                  │  • Players: DataTable        │
│                                  │  • Stats: exp progress,      │
│                                  │    hit/miss/BS/sneak/dodge % │
├──────────────────────┬───────────┴──────────────────────────────┤
│ HP ████░ 141/216     │ Path: RHU2LOOP Lap 58  Status: Moving   │
│ MP █████  89/120     │ Kills: 694  Exp/hr: 30k  Time: 07:36pm  │
│                      │ Hit:38% Miss:52% BS:38%  Exp: 52,497    │
├──────────────────────┴──────────────────────────────────────────┤
│ ▶ _                         F1:menu Ctrl+1-3:tabs Ctrl+R Ctrl+B │
└─────────────────────────────────────────────────────────────────┘
```

### Panel toggles

| Shortcut | Action |
|---|---|
| `Ctrl+R` | Toggle right panel (Conversations/Players/Stats) |
| `Ctrl+B` | Toggle stats bar |
| `Ctrl+1` | Switch to Conversations tab |
| `Ctrl+2` | Switch to Players tab |
| `Ctrl+3` | Switch to Stats tab |
| `F1` | Open menu |
| `Ctrl+K` | Connect/disconnect |
| `Ctrl+L` | Start/stop loop |

Panel visibility state is saved back to `[ui]` in the character config on exit.

### Menu structure

- **View** — Toggle Right Panel, Toggle Stats Bar, ─, Conversations, Online Players, Statistics
- **Action** — Connect, Disconnect, ─, Start Loop, Stop Loop, ─, Toggle Auto-combat, Toggle Auto-sneak
- **Options** — Edit Config (opens `$EDITOR` on the TOML file), Reload Config, ─, Edit Players
- **Help** — Keyboard Shortcuts, About

---

## File Structure

```
src/mmud/
├── events.py                  # Protocol-agnostic event dataclasses
├── config/
│   ├── __init__.py
│   ├── schema.py              # MudConfig + all sub-config dataclasses
│   └── loader.py             # load_config(path) → MudConfig
├── tui/
│   ├── __init__.py
│   ├── __main__.py            # CLI entry point (argparse → app.run())
│   ├── app.py                 # Textual App class, wires everything together
│   ├── app.tcss               # Layout CSS
│   └── widgets/
│       ├── __init__.py
│       ├── game_output.py     # RichLog subscribing to LineReceived
│       ├── conversations.py   # RichLog subscribing to ConversationReceived
│       ├── players.py         # DataTable subscribing to PlayerSeen
│       ├── stats_bar.py       # HP/MP bars + session + combat accuracy
│       └── right_panel.py     # TabbedContent containing the three right widgets
└── web/
    └── __init__.py            # Placeholder for future web UI

characters/                    # Character config files
    spawn_daprawn.toml         # gitignored (contains passwords) — user-created
    example.toml               # committed reference config with all options documented

tests/
    test_config.py
    test_events.py
    test_tui_widgets.py        # Textual headless widget tests
```

---

## Events (`src/mmud/events.py`)

Typed dataclasses — protocol-agnostic, no Textual or WebSocket imports.

| Event | Fields | Emitted when |
|---|---|---|
| `LineReceived` | `line: str` | Every raw line from server |
| `HpChanged` | `hp: int, max_hp: int` | HP value parsed from prompt |
| `MpChanged` | `mp: int, max_mp: int` | Mana value parsed from prompt |
| `RoomChanged` | `code: str, name: str` | Room identified from output |
| `EffectApplied` | `name: str, flags: int` | Pattern apply match |
| `EffectRemoved` | `name: str` | Pattern remove match |
| `CombatChanged` | `in_combat: bool` | Combat state change |
| `ConversationReceived` | `channel: str, sender: str, text: str` | Tell/shout/party message |
| `PlayerSeen` | `name: str, level: str, rep: str, gang: str` | Player in online list |
| `PathStarted` | `name: str` | Loop/path begun |
| `PathStepped` | `command: str, lap: int` | Each step executed |
| `SessionStatUpdated` | `key: str, value: str` | Kill count, exp rate, etc. |

---

## Config Schema (`characters/*.toml`)

All sections optional. Missing keys fall back to safe defaults. `--host`/`--port` CLI args override `[server]`.

```toml
[server]
host = "mud.example.com"
port = 4000

[login]
username  = "spawn"
password  = "hunter2"
character = "Spawn DaPrawn"    # matched against character-select prompt

[combat]
attack_cmd      = "kill"
flee_threshold  = 0.15         # flee when HP < 15%
rest_threshold  = 0.40         # rest (out of combat) when HP < 40%
backstab        = true
polite_attacks  = false        # don't attack with non-party players in room
attack_order    = "first"      # first | last | reverse
mana_attack_pct = 0.20         # don't attack if mana < 20%

[spells]
attack        = "magic missile"
pre_attack    = "true strike"   # cast just before engaging
multi_attack  = "fireball"      # area-effect spell
heal          = "cure light wounds"
heal_hp_pct   = 0.50
mana_heal     = "meditate"
mana_heal_pct = 0.30

[[spells.bless]]                # up to 10 entries
cmd      = "bless"
mana_pct = 0.80

[stealth]
auto_sneak  = true
sneak_cmd   = "sneak"
must_sneak  = false             # halt movement if sneak fails
auto_hide   = false
hide_cmd    = "hide"

[navigation]
loop_path        = "RHU2LOOP"
start_room       = "HOME"
auto_start       = false
flee_rooms       = 3
can_pick_locks   = false
can_disarm_traps = false

[items]
auto_get         = false
auto_cash        = true
collect_copper   = true
collect_silver   = true
collect_gold     = true
collect_platinum = true
collect_runic    = false
runic_name       = "runic"
dont_go_heavy    = true
dont_go_medium   = false

[party]
heal_spell         = "party heal"
heal_hp_pct        = 0.50
wait_hp_pct        = 0.30
wait_max_seconds   = 30
wait_cmd           = "wait"
resume_cmd         = "go"
attack_with_leader = true
share_cash         = false

[[party.bless]]                 # up to 4 entries
cmd          = "party bless"
wait_seconds = 60

[afk]
enabled         = false
timeout_minutes = 5
reply           = "I am AFK"
hangup_on_low_hp = false
alert           = false
popup_missed    = true

[[players]]                     # one block per known player
name        = "BumbleBee"
friend      = true
remote_cmds = ["@do", "@loop"]
dont_heal   = false
dont_bless  = false

[ui]
show_right_panel = true
show_stats_bar   = true
default_tab      = "conversations"   # conversations | players | stats
```

---

## Testing

- **`test_config.py`** — valid TOML, missing optional sections, bad types, CLI override of host/port. Uses inline TOML strings.
- **`test_events.py`** — post events to bus, assert subscribers receive them. Assert `MudBot` emits correct events for known pattern matches.
- **`test_tui_widgets.py`** — Textual headless tests via `App.run_test()`. Feed events, assert widget render output. No live MUD connection.
- **Future `test_web.py`** — same event bus, assert WebSocket serialisation. Independent of TUI tests.

---

## Future Web UI Notes

- `src/mmud/web/` will contain a FastAPI app with a WebSocket endpoint.
- On connect, the WebSocket handler subscribes to `GameEventBus` and serialises each event to JSON.
- The same `MudConfig` drives bot behaviour regardless of which UI is attached.
- No changes to `events.py`, `config/`, or `bot.py` required when the web layer is added.
