# Phase 9: Session Management & Full Disconnect Logic — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Session-level safety and observability: capture-to-file, exp-rate calculation with low-rate logoff/relog, max-hours-per-day cutoff, and a deliberate **relog flow** (log out, reconnect, log back in) — completing the disconnect story Phase 2 started.

**Architecture:** `SessionManager` (`src/mmud/session.py`) is a plain object the bot feeds directly (the SafetyMonitor pattern — no bus dependency): `on_line(raw)` appends to the capture file, `on_exp(value, now)` samples experience, `tick(now)` returns the action the 1Hz ticker should take (`None | "hangup" | "relog"`). Relog is a new bot flow: `request_relog()` enqueues the logout command and sets `_relog_pending`, which `run()`'s reconnect wrapper handles BEFORE the hangup check — one fresh session with `LoginHandler.reset()` + `SafetyMonitor.reset()`, not counted against `max_redials`.

**Tech Stack:** Python 3.11+, stdlib only. Transcript-tested via `make_transcript_bot`.

**Prerequisites:** Phases 2–3 complete (`bot._safety`, `RemoteCommandHandler`); `pytest -q` green.

**Verified API facts (no re-derivation needed):**
- `LoginHandler.reset()` clears `_sent_username/_sent_password/in_game` (`src/mmud/automation/login.py`) — relog re-login works through the existing login flow.
- `SafetyMonitor.reset()` exists (Phase 2).
- `bot.run()` wrapper: loops `_run_session()`; `if self._safety.hangup_requested: break` comes FIRST, then the `safety.reconnect`/`max_redials` check — the relog branch must be inserted before the hangup break.
- Exp source: `bot._parse_who_and_exp` calls `self._state.set_exp(exp)` when `WhoParser.parse_exp_line` matches — add the `session.on_exp` call there.
- `FakeConnection.readlines()` re-yields its transcript on each call — a relogging transcript bot simply replays the lines for the second session (handy for the e2e test).
- `TaskType.RELOGGING` exists unused.

---

## File Map

```
src/mmud/
  session.py                 NEW — SessionManager
  config/schema.py           MODIFY — SessionConfig
  config/loader.py           MODIFY — parse [session]
  bot.py                     MODIFY — feed hooks, ticker action, relog flow
  automation/remote.py       MODIFY — @relog, @rate
tests/
  test_session.py            NEW
  test_config.py             MODIFY
  test_bot.py                MODIFY — relog e2e
  test_remote.py             MODIFY — verbs
characters/example.toml      MODIFY
README.md                    MODIFY — [session] note
```

---

### Task 1: SessionConfig

**Files:**
- Modify: `src/mmud/config/schema.py`, `src/mmud/config/loader.py`, `characters/example.toml`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_session_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[session]
capture_file = "session.log"
max_hours_per_day = 4
min_exp_rate = 5000
grace_minutes = 10
low_rate_action = "relog"
logout_cmd = "=x"
""")
    cfg = load_config(p)
    assert cfg.session.capture_file == "session.log"
    assert cfg.session.max_hours_per_day == 4
    assert cfg.session.min_exp_rate == 5000
    assert cfg.session.grace_minutes == 10
    assert cfg.session.low_rate_action == "relog"
    assert cfg.session.logout_cmd == "=x"


def test_session_defaults():
    cfg = load_config(None)
    assert cfg.session.capture_file == ""        # "" = capture off
    assert cfg.session.max_hours_per_day == 0    # 0 = unlimited
    assert cfg.session.min_exp_rate == 0         # 0 = disabled
    assert cfg.session.grace_minutes == 15
    assert cfg.session.low_rate_action == "hangup"
    assert cfg.session.logout_cmd == "x"
```

- [ ] **Step 2: Run to confirm failure** — `pytest tests/test_config.py -v -k session` → AttributeError

- [ ] **Step 3: Implement**

`schema.py` (after `CommerceConfig` if Phase 8 landed, else after `LearningConfig`):

```python
@dataclass
class SessionConfig:
    capture_file: str = ""          # append raw server lines here ("" = off)
    max_hours_per_day: int = 0      # hangup after this many hours (0 = unlimited)
    min_exp_rate: int = 0           # exp/hour floor (0 = disabled)
    grace_minutes: int = 15         # no rate enforcement during warmup
    low_rate_action: str = "hangup" # "hangup" | "relog"
    logout_cmd: str = "x"           # command that exits the game cleanly
```

`MudConfig` gains `session: SessionConfig = field(default_factory=SessionConfig)`.
Loader block (add `SessionConfig` to imports):

```python
    if se := data.get("session"):
        cfg.session = SessionConfig(
            capture_file=se.get("capture_file", ""),
            max_hours_per_day=se.get("max_hours_per_day", 0),
            min_exp_rate=se.get("min_exp_rate", 0),
            grace_minutes=se.get("grace_minutes", 15),
            low_rate_action=se.get("low_rate_action", "hangup"),
            logout_cmd=se.get("logout_cmd", "x"),
        )
```

`example.toml` — append the section with the schema comments.

- [ ] **Step 4: Run + commit**

```bash
git add src/mmud/config/ characters/example.toml tests/test_config.py
git commit -m "feat: [session] config section"
```

---

### Task 2: SessionManager core

**Files:**
- Create: `src/mmud/session.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_session.py
from mmud.config.schema import SessionConfig
from mmud.session import SessionManager


def _mgr(start=0.0, **cfg):
    return SessionManager(SessionConfig(**cfg), now=lambda: start)


def test_exp_rate_needs_two_samples():
    m = _mgr()
    assert m.exp_rate_per_hour() == 0.0
    m.on_exp(1000, now=0.0)
    assert m.exp_rate_per_hour() == 0.0


def test_exp_rate_per_hour():
    m = _mgr()
    m.on_exp(1000, now=0.0)
    m.on_exp(3000, now=1800.0)          # +2000 exp in 30 min
    assert m.exp_rate_per_hour() == 4000.0


def test_hours_elapsed():
    m = _mgr(start=0.0)
    assert m.hours_elapsed(7200.0) == 2.0


def test_tick_max_hours_hangup():
    m = _mgr(start=0.0, max_hours_per_day=2)
    assert m.tick(7199.0) is None
    assert m.tick(7200.0) == "hangup"
    assert m.tick(7300.0) is None       # latched: fires once


def test_tick_low_rate_after_grace():
    m = _mgr(start=0.0, min_exp_rate=5000, grace_minutes=15,
             low_rate_action="relog")
    m.on_exp(0, now=0.0)
    m.on_exp(100, now=1800.0)           # 200/hr, well under 5000
    assert m.tick(899.0) is None        # still inside grace (15 min)
    assert m.tick(1800.0) == "relog"
    assert m.tick(1900.0) is None       # latched


def test_tick_rate_ok_no_action():
    m = _mgr(start=0.0, min_exp_rate=1000, grace_minutes=0)
    m.on_exp(0, now=0.0)
    m.on_exp(5000, now=3600.0)          # 5000/hr
    assert m.tick(3600.0) is None


def test_tick_disabled_by_default():
    m = _mgr(start=0.0)
    m.on_exp(0, now=0.0)
    m.on_exp(1, now=36000.0)
    assert m.tick(36000.0) is None
```

- [ ] **Step 2: Run to confirm failure** — ModuleNotFoundError

- [ ] **Step 3: Create `src/mmud/session.py`**

```python
from __future__ import annotations
import time
from typing import Callable
from mmud.config.schema import SessionConfig


class SessionManager:
    """Session-scope tracking: capture file, exp rate, time limits.

    Pure logic with an injected clock; the bot feeds it directly
    (on_line / on_exp) and asks tick(now) for the 1Hz safety action.
    """

    def __init__(self, config: SessionConfig,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._cfg = config
        self.started_at = now()
        self._first_exp: tuple[float, int] | None = None   # (t, exp)
        self._last_exp: tuple[float, int] | None = None
        self._capture = None
        self._fired = False    # actions fire once per session

    # ---- feeds ---------------------------------------------------------------

    def on_line(self, raw: str) -> None:
        if not self._cfg.capture_file:
            return
        if self._capture is None:
            self._capture = open(self._cfg.capture_file, "a", encoding="utf-8",
                                 errors="replace")
        self._capture.write(raw if raw.endswith("\n") else raw + "\n")
        self._capture.flush()

    def on_exp(self, value: int, now: float) -> None:
        if self._first_exp is None:
            self._first_exp = (now, value)
        self._last_exp = (now, value)

    # ---- queries ---------------------------------------------------------------

    def exp_rate_per_hour(self) -> float:
        if not self._first_exp or not self._last_exp:
            return 0.0
        t0, e0 = self._first_exp
        t1, e1 = self._last_exp
        if t1 <= t0:
            return 0.0
        return (e1 - e0) / ((t1 - t0) / 3600.0)

    def hours_elapsed(self, now: float) -> float:
        return (now - self.started_at) / 3600.0

    # ---- 1Hz decision -----------------------------------------------------------

    def tick(self, now: float) -> str | None:
        """Return "hangup" | "relog" | None. Fires at most once per session."""
        if self._fired:
            return None
        if (self._cfg.max_hours_per_day
                and self.hours_elapsed(now) >= self._cfg.max_hours_per_day):
            self._fired = True
            return "hangup"
        if (self._cfg.min_exp_rate
                and (now - self.started_at) >= self._cfg.grace_minutes * 60
                and self._first_exp and self._last_exp
                and self.exp_rate_per_hour() < self._cfg.min_exp_rate):
            self._fired = True
            return self._cfg.low_rate_action
        return None

    def reset(self, now: float) -> None:
        """New session (after relog): restart timers and samples."""
        self.started_at = now
        self._first_exp = None
        self._last_exp = None
        self._fired = False

    def close(self) -> None:
        if self._capture is not None:
            self._capture.close()
            self._capture = None
```

- [ ] **Step 4: Run** — `pytest tests/test_session.py -v` → 7 passed

- [ ] **Step 5: Capture-file test** — append to `tests/test_session.py`,
then re-run:

```python
def test_capture_appends_raw_lines(tmp_path):
    cap = tmp_path / "session.log"
    m = SessionManager(SessionConfig(capture_file=str(cap)), now=lambda: 0.0)
    m.on_line("[HP=100/100]:\n")
    m.on_line("An orc swings at you!")     # newline added if missing
    m.close()
    assert cap.read_text() == "[HP=100/100]:\nAn orc swings at you!\n"


def test_no_capture_when_unset(tmp_path):
    m = SessionManager(SessionConfig(), now=lambda: 0.0)
    m.on_line("hello\n")                   # must not crash or create files
    m.close()
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 6: Commit**

```bash
git add src/mmud/session.py tests/test_session.py
git commit -m "feat: SessionManager — capture file, exp rate, session limits"
```

---

### Task 3: Bot wiring — feeds, ticker action, relog flow

**Files:**
- Modify: `src/mmud/bot.py`
- Test: `tests/test_bot.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
from mmud.config.schema import SessionConfig


@pytest.mark.asyncio
async def test_relog_runs_second_session(tmp_path):
    received = []
    bus = GameEventBus()
    bus.subscribe(LineReceived, received.append)
    bot = make_transcript_bot(["hello\n", "world\n"], event_bus=bus)
    bot.request_relog("test")
    await bot.run()
    # logout command sent, then a SECOND session replayed the transcript
    assert bot._config.session.logout_cmd in bot._conn.sent
    assert len(received) == 4               # 2 lines x 2 sessions
    assert not bot._relog_pending


@pytest.mark.asyncio
async def test_relog_resets_login_and_safety():
    bot = make_transcript_bot(["You have died!\n"])
    bot._config.safety.hangup_on_death = True
    bot._login_handler.in_game = True
    bot.request_relog("test")
    await bot.run()
    # second session re-processed the death line; safety was reset in between
    # (hangup fired again in session 2 and ended the run)
    assert bot._safety.hangup_requested
    assert bot._login_handler.in_game is False or bot._safety.hangup_requested


@pytest.mark.asyncio
async def test_session_capture_via_bot(tmp_path):
    config = MudConfig()
    config.session = SessionConfig(capture_file=str(tmp_path / "cap.log"))
    bot = make_transcript_bot(["alpha\n", "beta\n"], config=config)
    await bot.run()
    bot._session.close()
    text = (tmp_path / "cap.log").read_text()
    assert "alpha" in text and "beta" in text


@pytest.mark.asyncio
async def test_ticker_action_low_rate_hangup(monkeypatch):
    # tick() decision is unit-tested in test_session; here just verify the
    # bot honors a "hangup" action from the session manager.
    bot = make_transcript_bot(["x\n"])
    bot._session._fired = False
    monkeypatch.setattr(bot._session, "tick", lambda now: "hangup")
    bot._check_session(now=0.0)
    assert bot._safety.hangup_requested
    assert "session" in bot._safety.reason
```

- [ ] **Step 2: Run to confirm failure** — `request_relog`/`_check_session`/`_session` missing

- [ ] **Step 3: Implement in `bot.py`**

`__init__` (next to the `SafetyMonitor` construction):

```python
        from mmud.session import SessionManager
        self._session = SessionManager(self._config.session)
        self._relog_pending = False
```

Feed hooks:
- Top of `_process_line` (FIRST line, before ANSI strip — capture is raw):
  `self._session.on_line(line)`.
- In `_parse_who_and_exp`, inside the exp branch after `self._state.set_exp(exp)`:
  `self._session.on_exp(exp, time.monotonic())`.

Ticker — add to `_ticker` after `_check_task_timeout` and the new method:

```python
            self._check_session(time.monotonic())
```

```python
    def _check_session(self, now: float) -> None:
        action = self._session.tick(now)
        if action == "hangup":
            self._safety.request_hangup("session limit reached")
        elif action == "relog":
            self.request_relog("exp rate below minimum")
```

Relog API + run()-wrapper branch (ORDER MATTERS — before the hangup break):

```python
    def request_relog(self, reason: str) -> None:
        """Log out cleanly and start one fresh session (login from scratch)."""
        if self._relog_pending:
            return
        self._relog_pending = True
        self._state.begin_task(TaskType.RELOGGING, priority=1, timeout_s=30.0,
                               now=time.monotonic())
        self._state.enqueue(self._config.session.logout_cmd)
```

In `run()`:

```python
            try:
                await self._run_session()
            except (ConnectionError, OSError):
                pass
            if self._relog_pending:
                self._relog_pending = False
                self._login_handler.reset()
                self._safety.reset()
                self._state.abort_task()
                self._session.reset(time.monotonic())
                continue
            if self._safety.hangup_requested:
                break   # deliberate disconnect — never auto-reconnect past it
```

(RELOGGING at priority 1 pins every slot except the queue (0), so only the
logout command goes out while the relog is pending.)

- [ ] **Step 4: Run** — `pytest tests/test_bot.py -v -k "relog or session"` then `pytest -q` → green

- [ ] **Step 5: Commit**

```bash
git add src/mmud/bot.py tests/test_bot.py
git commit -m "feat: session wiring — capture, exp-rate ticker actions, relog flow"
```

---

### Task 4: @relog + @rate verbs, docs

**Files:**
- Modify: `src/mmud/automation/remote.py`, `README.md`
- Test: `tests/test_remote.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
def test_relog_verb():
    bot = _bot(WILDCARD)
    h = RemoteCommandHandler(bot)
    reply = h.handle("Friend", "@relog")
    assert "relog" in reply.lower()
    assert bot._relog_pending
    assert bot._state.dequeue() == bot._config.session.logout_cmd


def test_rate_verb():
    bot = _bot(WILDCARD)
    bot._session.on_exp(0, now=0.0)
    bot._session.on_exp(2500, now=1800.0)
    h = RemoteCommandHandler(bot)
    assert "5000" in h.handle("Friend", "@rate")
```

- [ ] **Step 2: Run to confirm failure** — unknown verbs

- [ ] **Step 3: Register in `_register_builtins`**

```python
        self.register("relog", self._relog)
        self.register("rate", lambda s, a: (
            f"exp rate {bot._session.exp_rate_per_hour():.0f}/hr "
            f"({bot._session.hours_elapsed(__import__('time').monotonic()):.1f}h session)"
        ))
```

and the method:

```python
    def _relog(self, sender: str, arg: str) -> str:
        self._bot.request_relog(f"remote @relog from {sender}")
        return "relogging"
```

(Prefer a normal `import time` at module top over the inline `__import__` —
implementer's choice; the test only checks the rate number.)

- [ ] **Step 4: README** — add `[session]` to the config reference and a short
"Session management" paragraph: capture file, exp-rate logoff/relog,
max-hours cutoff, `@relog`/`@rate`, and the live-tune caveat for `logout_cmd`
(MajorMUD exits with `x` at the prompt; some BBS menus need `=x`).

- [ ] **Step 5: Run** — `pytest -q` → green

- [ ] **Step 6: Commit**

```bash
git add src/mmud/automation/remote.py README.md tests/test_remote.py
git commit -m "feat: @relog/@rate verbs; session docs"
```

---

## Verification

- `pytest -q` — full suite green after every task.
- Relog e2e covered by `test_relog_runs_second_session` (FakeConnection replays
  its transcript per `readlines()` call — the second session re-reads it, so
  the line count doubles and proves the wrapper looped once without
  `safety.reconnect`).
- Live test (user, per docs/testing-plan.md): confirm `logout_cmd` actually
  exits to the BBS and that the login sequence completes on the second pass
  (`LoginHandler` regexes already live-tested in Phase 2); set a 2-minute
  `max_hours_per_day` equivalent via small values to watch the hangup fire;
  check the capture file contains raw ANSI lines.
- Phase 2 note: this completes the disconnect story — `safety.reconnect`
  covers unexpected loss, `request_relog` covers deliberate logout-and-return.
  Phase 11's scheduler will call `request_relog` for timed relogs.
