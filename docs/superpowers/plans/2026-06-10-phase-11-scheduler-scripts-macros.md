# Phase 11: Scheduler, Scripts, Macros — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> This is the FINAL roadmap phase.

**Goal:** Timed events (logoff/relog/goto/command/loop on intervals), the original's command-template expansion (`{userid}`, `||` alternatives, `^M` escapes), and MACROS.MD numpad keybinds in the TUI.

**Architecture:** `expand_template()` (`src/mmud/commands.py`) implements the spec decompiled from `command_template_expand @ 0x00486690`. `Scheduler` (`src/mmud/automation/scheduler.py`) runs off the bot's existing 1Hz `_ticker` with injected callables (the CommerceEngine pattern) and per-event next-fire/remaining-count bookkeeping. MACROS.MD is **text** (probed) and is read directly per the project's text-source rule; the TUI maps its numpad key codes to send-command actions.

**Tech Stack:** Python 3.11+, stdlib only.

**Prerequisites:** Phases 6, 9 complete (`navigate_to_room`, `start_loop`, `request_relog`, `session.logout_cmd`); `pytest -q` green (376).

**RE'd facts (from megamud.exe this session — encode, do not re-derive):**
- **There is no binary EVENTS.MD.** The original stores the schedule in the
  config .ini `[Schedule]` section as `Event0..N = type:interval_seconds:count:command`
  (`event_schedule_load @ 0x00422b10`). Types: 1=Logon, 2=Logoff, 3=Relog,
  4=GoTo, 5=Command, 6=LoopPath. Our TOML equivalent is `[[schedule.events]]`.
- Runtime (`scheduler_event_execute @ 0x00404cd0`): an event fires when its
  next-fire time passes; Logoff/Relog send the template-expanded logout command
  then exit/reconnect; GoTo pushes a path destination; Command expands + sends;
  LoopPath switches the active loop by name; then the next event is scheduled.
- Template spec (`command_template_expand @ 0x00486690`): `||`-separated random
  alternatives (one chosen); tokens `{userid} {pswd} {source} {target} {dmg}
  {p1}..{p5}`; escapes `^X` → control char (`^M` = CR), `^^` → `^`, `^~` → `~`;
  bare `~` → `\x01` (ANSI lead-in).
- **MACROS.MD is text** (probed, 168 bytes): lines `key_code:shift:ctrl:alt:command`,
  command suffix `^M` = press enter. Real content: 11 macros, VK codes
  96–105 + 110 (numpad), commands `d u sw s se w rest e nw n ne`.

---

## File Map

```
src/mmud/
  commands.py                 NEW — expand_template()
  data/macros_md.py           NEW — text macro loader
  automation/scheduler.py     NEW — Scheduler (1Hz-driven)
  config/schema.py            MODIFY — ScheduleEvent/ScheduleConfig
  config/loader.py            MODIFY — parse [[schedule.events]]
  bot.py                      MODIFY — scheduler wiring + template vars
  automation/remote.py        MODIFY — @events
  tui/app.py                  MODIFY — numpad macro keybinds
tests/
  test_commands.py            NEW
  test_macros_md.py           NEW
  test_scheduler.py           NEW
  test_config.py              MODIFY
  test_remote.py              MODIFY
characters/example.toml       MODIFY
README.md                     MODIFY
```

---

### Task 1: `expand_template()`

**Files:**
- Create: `src/mmud/commands.py`
- Test: `tests/test_commands.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_commands.py
from mmud.commands import expand_template


def test_plain_passthrough():
    assert expand_template("kill orc") == "kill orc"


def test_tokens():
    out = expand_template("tell {target} hi from {userid}",
                          {"target": "orc", "userid": "Bee"})
    assert out == "tell orc hi from Bee"


def test_unknown_token_empty():
    assert expand_template("hi {nosuch} there") == "hi  there"


def test_alternatives_choose_injected():
    t = "say one||say two||say three"
    assert expand_template(t, choose=lambda n: 0) == "say one"
    assert expand_template(t, choose=lambda n: 2) == "say three"


def test_control_escapes():
    assert expand_template("hi^M") == "hi\r"
    assert expand_template("a^^b") == "a^b"
    assert expand_template("a^~b") == "a~b"


def test_tilde_is_ansi_leadin():
    assert expand_template("~[1m") == "\x01[1m"


def test_dmg_and_captures():
    out = expand_template("{dmg} {p1} {p5}", {"dmg": "42", "p1": "x"})
    assert out == "42 x "
```

- [ ] **Step 2: Run to confirm failure** — `pytest tests/test_commands.py -v` → ModuleNotFoundError

- [ ] **Step 3: Create `src/mmud/commands.py`**

```python
from __future__ import annotations
import random
import re
from typing import Callable

# Spec decompiled from megamud.exe command_template_expand @ 0x00486690:
# "||" random alternatives; {token} substitution; ^X control escapes; ~ -> \x01.
_TOKEN_RE = re.compile(r"\{(\w+)\}")
KNOWN_TOKENS = ("userid", "pswd", "source", "target", "dmg",
                "p1", "p2", "p3", "p4", "p5")


def expand_template(template: str, variables: dict[str, str] | None = None,
                    choose: Callable[[int], int] | None = None) -> str:
    """Expand a megamud command template.

    variables: token values (missing tokens expand to ""). choose: pick the
    index among "||" alternatives (defaults to random) — inject for tests.
    """
    variables = variables or {}
    alts = template.split("||")
    if len(alts) > 1:
        picker = choose or (lambda n: random.randrange(n))
        template = alts[picker(len(alts))]

    out: list[str] = []
    i = 0
    while i < len(template):
        ch = template[i]
        if ch == "{":
            m = _TOKEN_RE.match(template, i)
            if m:
                out.append(variables.get(m.group(1), ""))
                i = m.end()
                continue
            out.append(ch)
        elif ch == "^" and i + 1 < len(template):
            nxt = template[i + 1]
            if nxt == "^":
                out.append("^")
            elif nxt == "~":
                out.append("~")
            else:
                out.append(chr(ord(nxt.upper()) - 0x40))   # ^M -> \r
            i += 2
            continue
        elif ch == "~":
            out.append("\x01")
        else:
            out.append(ch)
        i += 1
    return "".join(out)
```

- [ ] **Step 4: Run** — `pytest tests/test_commands.py -v` → 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/mmud/commands.py tests/test_commands.py
git commit -m "feat: expand_template — megamud command templates (alternatives/tokens/escapes)"
```

---

### Task 2: MACROS.MD loader + TUI numpad binds

**Files:**
- Create: `src/mmud/data/macros_md.py`
- Modify: `src/mmud/tui/app.py`
- Test: `tests/test_macros_md.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_macros_md.py
from mmud.data.macros_md import Macro, load_macros, vk_to_key_name


def test_load_real_macros(data_dir):
    macros = load_macros(data_dir / "MACROS.MD")
    assert len(macros) == 11
    by_key = {m.key_code: m for m in macros}
    assert by_key[110].command == "d" and by_key[110].press_enter
    assert by_key[101].command == "rest"
    assert by_key[104].command == "n"
    assert all(not (m.shift or m.ctrl or m.alt) for m in macros)


def test_missing_file_returns_empty(tmp_path):
    assert load_macros(tmp_path / "MACROS.MD") == []


def test_malformed_lines_skipped(tmp_path):
    p = tmp_path / "MACROS.MD"
    p.write_text("not a macro\n96:0:0:0:u^M\n")
    macros = load_macros(p)
    assert len(macros) == 1 and macros[0].key_code == 96


def test_vk_to_key_name():
    assert vk_to_key_name(96) == "kp_0"
    assert vk_to_key_name(105) == "kp_9"
    assert vk_to_key_name(110) == "kp_decimal"
    assert vk_to_key_name(42) is None
```

- [ ] **Step 2: Run to confirm failure** — ModuleNotFoundError

- [ ] **Step 3: Create `src/mmud/data/macros_md.py`**

```python
from __future__ import annotations
import pathlib
from dataclasses import dataclass

# MACROS.MD is TEXT (probed): "key_code:shift:ctrl:alt:command" lines,
# command suffix "^M" = press enter. Read directly (never imported into the
# game-DB store, per the project's text-source rule).

# Windows virtual-key codes -> terminal key names (numpad block).
_VK_KEYS = {96: "kp_0", 97: "kp_1", 98: "kp_2", 99: "kp_3", 100: "kp_4",
            101: "kp_5", 102: "kp_6", 103: "kp_7", 104: "kp_8", 105: "kp_9",
            110: "kp_decimal"}


@dataclass
class Macro:
    key_code: int
    shift: bool
    ctrl: bool
    alt: bool
    command: str
    press_enter: bool


def vk_to_key_name(vk: int) -> str | None:
    return _VK_KEYS.get(vk)


def load_macros(path: pathlib.Path) -> list[Macro]:
    if not path.exists():
        return []
    macros: list[Macro] = []
    for line in path.read_text(encoding="latin-1").splitlines():
        parts = line.strip().split(":", 4)
        if len(parts) != 5 or not parts[0].isdigit():
            continue
        command = parts[4]
        press_enter = command.endswith("^M")
        if press_enter:
            command = command[:-2]
        macros.append(Macro(
            key_code=int(parts[0]),
            shift=parts[1] == "1", ctrl=parts[2] == "1", alt=parts[3] == "1",
            command=command, press_enter=press_enter,
        ))
    return macros
```

- [ ] **Step 4: TUI wiring** (`src/mmud/tui/app.py`) — load macros next to the
other data files (`data_dir / "MACROS.MD"` when a data dir is configured),
build `self._macro_keys: dict[str, str]` mapping `vk_to_key_name(m.key_code)`
→ `m.command`, and in the app's key handler (`on_key`) send the mapped command
through the same path the command input uses when the input box is NOT focused:

```python
    def on_key(self, event) -> None:
        cmd = self._macro_keys.get(event.key)
        if cmd is not None and not self._input_focused():
            self.send_command(cmd)
            event.stop()
```

(Adapt names to the app's existing structure — `send_command`/focus check are
whatever app.py already uses for the command box. NOTE: terminal numpad key
names vary by emulator; `kp_0`-style names are Textual's, but verify on the
user's terminal during live testing.)

- [ ] **Step 5: Run** — `pytest tests/test_macros_md.py -v` then `pytest -q` → green

- [ ] **Step 6: Commit**

```bash
git add src/mmud/data/macros_md.py src/mmud/tui/app.py tests/test_macros_md.py
git commit -m "feat: MACROS.MD text loader + TUI numpad macro keybinds"
```

---

### Task 3: `[schedule]` config

**Files:**
- Modify: `src/mmud/config/schema.py`, `src/mmud/config/loader.py`, `characters/example.toml`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_schedule_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[[schedule.events]]
type = "relog"
every_seconds = 3600
count = 0

[[schedule.events]]
type = "command"
every_seconds = 600
count = 3
arg = "say hello||say hi"
""")
    cfg = load_config(p)
    assert len(cfg.schedule.events) == 2
    assert cfg.schedule.events[0].type == "relog"
    assert cfg.schedule.events[0].every_seconds == 3600
    assert cfg.schedule.events[0].count == 0          # 0 = forever
    assert cfg.schedule.events[1].arg == "say hello||say hi"


def test_schedule_empty_by_default():
    cfg = load_config(None)
    assert cfg.schedule.events == []
```

- [ ] **Step 2: Run to confirm failure** — AttributeError

- [ ] **Step 3: Implement** — schema.py (after `SessionConfig`):

```python
@dataclass
class ScheduleEvent:
    type: str = "command"      # logon|logoff|relog|goto|command|loop
    every_seconds: int = 0     # fire interval (<=0 = disabled)
    count: int = 0             # times to fire (0 = forever)
    arg: str = ""              # room code / command template / loop name


@dataclass
class ScheduleConfig:
    events: list[ScheduleEvent] = field(default_factory=list)
```

`MudConfig` gains `schedule: ScheduleConfig = field(default_factory=ScheduleConfig)`.
Loader (add both classes to imports):

```python
    if sc := data.get("schedule"):
        cfg.schedule = ScheduleConfig(events=[
            ScheduleEvent(
                type=ev.get("type", "command"),
                every_seconds=ev.get("every_seconds", 0),
                count=ev.get("count", 0),
                arg=ev.get("arg", ""),
            )
            for ev in sc.get("events", [])
        ])
```

`example.toml` — append a commented sample:

```toml
# ── Timed events (the original's .ini [Schedule] EventN entries) ─────────────
# [[schedule.events]]
# type          = "relog"     # logon|logoff|relog|goto|command|loop
# every_seconds = 3600
# count         = 0           # 0 = forever
# arg           = ""          # goto: room code; command: template; loop: name
```

- [ ] **Step 4: Run + commit**

```bash
git add src/mmud/config/ characters/example.toml tests/test_config.py
git commit -m "feat: [schedule] timed-event config (TOML form of the original's [Schedule] EventN)"
```

---

### Task 4: Scheduler

**Files:**
- Create: `src/mmud/automation/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scheduler.py
from mmud.automation.scheduler import Scheduler
from mmud.config.schema import ScheduleConfig, ScheduleEvent


class _Harness:
    def __init__(self):
        self.sent, self.gotos, self.loops = [], [], []
        self.relogs = 0
        self.logoffs = 0

    def make(self, *events, t=0.0):
        self.t = t
        return Scheduler(
            ScheduleConfig(events=list(events)),
            send=self.sent.append,
            goto=self.gotos.append,
            start_loop=self.loops.append,
            relog=lambda: setattr(self, "relogs", self.relogs + 1),
            logoff=lambda: setattr(self, "logoffs", self.logoffs + 1),
            now=lambda: self.t,
        )


def test_command_fires_on_interval_with_expansion():
    h = _Harness()
    s = h.make(ScheduleEvent(type="command", every_seconds=60,
                             arg="say hi^M"), t=0.0)
    s.tick(59.0)
    assert h.sent == []
    s.tick(60.0)
    assert h.sent == ["say hi"]              # expanded, trailing CR stripped
    s.tick(61.0)
    assert h.sent == ["say hi"]              # not again until next interval
    s.tick(120.0)
    assert h.sent == ["say hi", "say hi"]


def test_count_limits_fires():
    h = _Harness()
    s = h.make(ScheduleEvent(type="relog", every_seconds=10, count=2), t=0.0)
    s.tick(10.0); s.tick(20.0); s.tick(30.0); s.tick(40.0)
    assert h.relogs == 2                     # count exhausted


def test_goto_loop_logoff_dispatch():
    h = _Harness()
    s = h.make(ScheduleEvent(type="goto", every_seconds=5, arg="BANK"),
               ScheduleEvent(type="loop", every_seconds=7, arg="ORCS"),
               ScheduleEvent(type="logoff", every_seconds=11), t=0.0)
    s.tick(11.0)
    assert h.gotos == ["BANK"]
    assert h.loops == ["ORCS"]
    assert h.logoffs == 1


def test_disabled_event_never_fires():
    h = _Harness()
    s = h.make(ScheduleEvent(type="command", every_seconds=0, arg="x"), t=0.0)
    s.tick(99999.0)
    assert h.sent == []


def test_logon_is_noop_while_connected():
    h = _Harness()
    s = h.make(ScheduleEvent(type="logon", every_seconds=5), t=0.0)
    s.tick(10.0)                             # must not raise or dispatch
    assert h.sent == [] and h.relogs == 0
```

- [ ] **Step 2: Run to confirm failure** — ModuleNotFoundError

- [ ] **Step 3: Create `src/mmud/automation/scheduler.py`**

```python
from __future__ import annotations
import time
from typing import Callable
from mmud.commands import expand_template
from mmud.config.schema import ScheduleConfig

# Type dispatch mirrors megamud.exe scheduler_event_execute @ 0x00404cd0
# (1=Logon, 2=Logoff, 3=Relog, 4=GoTo, 5=Command, 6=LoopPath).


class Scheduler:
    """Timed events driven from the bot's 1Hz ticker.

    Injected callables keep this bot-free and unit-testable:
    send(cmd), goto(room_code), start_loop(name), relog(), logoff().
    """

    def __init__(self, config: ScheduleConfig, *,
                 send: Callable[[str], object],
                 goto: Callable[[str], object],
                 start_loop: Callable[[str], object],
                 relog: Callable[[], object],
                 logoff: Callable[[], object],
                 variables: Callable[[], dict] | None = None,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._events = [e for e in config.events if e.every_seconds > 0]
        self._send = send
        self._goto = goto
        self._start_loop = start_loop
        self._relog = relog
        self._logoff = logoff
        self._variables = variables or (lambda: {})
        start = now()
        self._next_fire = [start + e.every_seconds for e in self._events]
        self._remaining = [e.count if e.count > 0 else -1 for e in self._events]

    def tick(self, now: float) -> None:
        for i, event in enumerate(self._events):
            if self._remaining[i] == 0 or now < self._next_fire[i]:
                continue
            self._next_fire[i] = now + event.every_seconds
            if self._remaining[i] > 0:
                self._remaining[i] -= 1
            self._fire(event)

    def pending(self, now: float) -> list[tuple[str, float]]:
        """(description, seconds_until) per live event — for @events."""
        return [(f"{e.type} {e.arg}".strip(), max(0.0, self._next_fire[i] - now))
                for i, e in enumerate(self._events) if self._remaining[i] != 0]

    def _fire(self, event) -> None:
        kind = event.type.lower()
        if kind == "command":
            cmd = expand_template(event.arg, self._variables()).rstrip("\r")
            self._send(cmd)
        elif kind == "goto":
            self._goto(event.arg)
        elif kind == "loop":
            self._start_loop(event.arg)
        elif kind == "relog":
            self._relog()
        elif kind == "logoff":
            self._logoff()
        # "logon" is a no-op while connected: the port's reconnect (Phase 2)
        # and relog (Phase 9) flows own the connection lifecycle.
```

- [ ] **Step 4: Run** — `pytest tests/test_scheduler.py -v` → 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/mmud/automation/scheduler.py tests/test_scheduler.py
git commit -m "feat: Scheduler — timed logoff/relog/goto/command/loop events"
```

---

### Task 5: Bot wiring + @events + docs

**Files:**
- Modify: `src/mmud/bot.py`, `src/mmud/automation/remote.py`, `README.md`
- Test: `tests/test_remote.py` (append), `tests/test_bot.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_remote.py`:

```python
def test_events_verb():
    from mmud.config.schema import ScheduleEvent
    config = MudConfig()
    config.schedule.events = [ScheduleEvent(type="relog", every_seconds=3600)]
    bot = _bot(WILDCARD)
    bot._config.schedule = config.schedule
    from mmud.automation.scheduler import Scheduler
    bot._scheduler = Scheduler(config.schedule, send=lambda c: None,
                               goto=lambda c: None, start_loop=lambda n: None,
                               relog=lambda: None, logoff=lambda: None,
                               now=lambda: 0.0)
    h = RemoteCommandHandler(bot)
    reply = h.handle("Friend", "@events")
    assert "relog" in reply


def test_events_verb_empty():
    bot = _bot(WILDCARD)
    h = RemoteCommandHandler(bot)
    assert "no events" in h.handle("Friend", "@events").lower()
```

Append to `tests/test_bot.py`:

```python
@pytest.mark.asyncio
async def test_scheduled_command_fires_via_ticker():
    from mmud.config.schema import ScheduleEvent
    config = MudConfig()
    config.schedule.events = [ScheduleEvent(type="command", every_seconds=1,
                                            arg="look")]
    bot = make_transcript_bot(["x\n"], config=config)
    # drive the scheduler directly (the 1Hz ticker calls this in production)
    bot._scheduler.tick(bot._scheduler._next_fire[0] + 0.1)
    assert bot._state.dequeue() == "look"
```

- [ ] **Step 2: Run to confirm failure** — `bot._scheduler` missing / unknown verb

- [ ] **Step 3: Bot wiring** — `__init__` (after the session manager):

```python
        from mmud.automation.scheduler import Scheduler
        self._scheduler = Scheduler(
            self._config.schedule,
            send=self._state.enqueue,
            goto=self.navigate_to_room,
            start_loop=self.start_loop,
            relog=lambda: self.request_relog("scheduled relog"),
            logoff=self._scheduled_logoff,
            variables=self._template_vars,
        )
```

New methods:

```python
    def _scheduled_logoff(self) -> None:
        self._state.enqueue(self._config.session.logout_cmd)
        self._safety.request_hangup("scheduled logoff")

    def _template_vars(self) -> dict:
        names = self._state.monster_names()
        return {
            "userid": self._config.login.username,
            "pswd": self._config.login.password,
            "target": names[0] if names else "",
            "source": "",   # populated when live testing identifies the source line
            "dmg": str(self._state.combat_dmg_sum),
        }
```

`_ticker` gains (after `_check_session`):

```python
            self._scheduler.tick(time.monotonic())
```

- [ ] **Step 4: @events verb** — in `_register_builtins`:

```python
        self.register("events", lambda s, a: (
            ", ".join(f"{desc} in {int(secs)}s"
                      for desc, secs in bot._scheduler.pending(time.monotonic()))
            or "no events scheduled"
        ))
```

- [ ] **Step 5: README** — add `@events` to the verb table and a "Timed events
(`[schedule]`) & macros" section: the six event types with their original
`.ini [Schedule]` lineage, template syntax (`||`, tokens, `^M`), and MACROS.MD
numpad binds (with the terminal-key-name caveat).

- [ ] **Step 6: Run** — `pytest -q` → green

- [ ] **Step 7: Commit**

```bash
git add src/mmud/bot.py src/mmud/automation/remote.py README.md tests/
git commit -m "feat: scheduler wiring, @events verb, template vars; macro/schedule docs"
```

---

## Verification

- `pytest -q` — full suite green after every task.
- Format claims re-checkable: `xxd MACROS.MD` (text macro lines); Ghidra plate
  comments at `0x00422b10` (schedule .ini format), `0x00404cd0` (execute
  semantics), `0x00486690` (template spec).
- Live test (user): a `command` event with `||` alternatives firing on a short
  interval; a scheduled `relog`; numpad macros in the user's actual terminal
  (key names vary by emulator — adjust `_VK_KEYS` mapping if `kp_0`-style names
  don't match).
- This completes the roadmap: after Phase 11, every numbered gap in the
  original feature catalog maps to shipped code.
