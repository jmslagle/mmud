# Web Control Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a browser-based control panel that replicates MegaMud's classic multi-window layout (game terminal, conversations, player/session statistics, online players, quick-tools compass + action buttons) driven LIVE by the existing `GameEventBus`. The panel can both observe (every event streams to the browser over a WebSocket) and act (send game commands, fire quick-tool buttons, edit config).

**Architecture:** FastAPI backend registers ONE subscriber per `GameEventBus` event type, serializes each event to JSON, and broadcasts it to all connected `/ws` clients. A React/Vite SPA renders the panels and dispatches incoming events into a reducer by a stable `"type"` discriminator. The backend exposes REST endpoints (`/api/state`, `/api/command`, `/api/quicktool`, `/api/config`) that reach into the live `MudBot`. The server is **optional**: the bot constructs and starts it only when a `[web]` config section is present, so existing headless/TUI runs are completely unaffected.

**Tech Stack:** FastAPI, uvicorn, websockets, React, Vite, TypeScript, pytest, vitest

**Depends on:**
- **Doc 1 — `2026-06-11-hardening-and-gap-closure.md` Task 2 (new stat tracking).** The Session Statistics panel surfaces counters that Doc 1 adds (dialed/failed/connected/lost-carrier, people-seen/attacked, had-to-run/health-low, sneak%/dodge%, deposited/income-rate). Where a stat does not yet exist this plan reads `0`/`""` and the field lights up once Doc 1 lands. **Do not invent the stat plumbing here** — only consume it.
- **Doc 2 — `2026-06-11-in-app-configuration.md` (`ConfigService`).** The Settings view and `GET/PATCH /api/config` proxy Doc 2's `ConfigService`. If `ConfigService` is not yet importable, Task 2's config endpoints return HTTP 503 (`{"detail": "config service unavailable"}`) and the Settings view shows a "config service not available" banner. Everything else works without Doc 2.

---

## Conventions (read once, applies to every task)

- **Repo root:** `/Users/jslagle/proj/mmud`. All paths below are relative to it.
- **Python source** lives under `src/mmud/` (note `pyproject.toml` sets `pythonpath = ["src"]`).
- **Run the full Python suite:** `python -m pytest -q` from the repo root.
- **Run one Python test file:** `python -m pytest tests/web/test_server.py -q`.
- **Frontend lives at** `src/mmud/web/frontend/`. Run frontend commands **from that directory**.
- **Run the frontend unit tests:** `cd src/mmud/web/frontend && npm run test`.
- **Build the frontend:** `cd src/mmud/web/frontend && npm run build` (emits to `src/mmud/web/frontend/dist/`).
- **TDD discipline:** for every code task write the failing test FIRST, watch it fail, then write the implementation, then watch it pass. Never write implementation before its test.
- **Type consistency:** the bot owns `self._conn` (has `async def send(self, command: str)`), `self._state` (`GameState`), `self._session` (`SessionManager`), `self._bus` (`GameEventBus | None`), and methods `navigate_to_room(code) -> str`, `start_loop(name="") -> str`, `stop_all() -> str`, `toggle_loop() -> None`. The web server must use exactly these signatures.

---

## Background: what already exists (verified against source)

### Events (`src/mmud/events.py`)

The bus is dead simple:

```python
class GameEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[type, list[Callable]] = {}

    def subscribe(self, event_type: type, callback: Callable) -> None:
        self._subscribers.setdefault(event_type, []).append(callback)

    def post(self, event: object) -> None:
        for cb in self._subscribers.get(type(event), []):
            cb(event)
```

The full set of event dataclasses (all `@dataclass`, all plain fields — `dataclasses.asdict` works on every one):

| Event | Fields |
|---|---|
| `LineReceived` | `line: str` |
| `HpChanged` | `hp: int`, `max_hp: int` |
| `MpChanged` | `mp: int`, `max_mp: int` |
| `RoomChanged` | `code: str`, `name: str` |
| `EffectApplied` | `name: str`, `flags: int` |
| `EffectRemoved` | `name: str` |
| `CombatChanged` | `in_combat: bool` |
| `ConversationReceived` | `channel: str` (`tell`/`shout`/`party`/`gossip`), `sender: str`, `text: str` |
| `PlayerSeen` | `name: str`, `level: str`, `rep: str`, `gang: str` |
| `PathStarted` | `name: str` |
| `PathStepped` | `command: str`, `lap: int` |
| `SessionStatUpdated` | `key: str`, `value: str` |
| `MonstersSeen` | `monsters: list[str]` |
| `TaskChanged` | `task_type: str`, `status: str` |
| `ConditionChanged` | `name: str`, `active: bool` |
| `HangupTriggered` | `reason: str` |
| `DbImported` | `added: int`, `updated: int`, `collisions: int` |
| `DbCollision` | `db: str`, `record_id: int` |
| `TravelResynced` | `from_step: int`, `to_step: int` |
| `TravelEnded` | `reason: str` |

`MudBot._emit(event)` calls `self._bus.post(event)` when `self._bus is not None`. The web server NEVER emits; it only subscribes.

### Bot ownership (`src/mmud/bot.py`)

- Constructor: `MudBot(host, port, patterns=None, data_dir=None, event_bus=None, rooms=None, config=None)`.
- `self._bus = event_bus` — the bus the web server subscribes to.
- `self._conn` — `MudConnection`; the send path is `await self._conn.send(cmd)`.
- `self._state` — `GameState` (see fields below).
- `self._session` — `SessionManager` (`exp_rate_per_hour()`, `hours_elapsed(now)`, `started_at`).
- `self._config` — `MudConfig`.
- `navigate_to_room(to_code: str) -> str`, `start_loop(name="") -> str`, `stop_all() -> str`, `toggle_loop() -> None`.
- The bot runs inside an asyncio loop (`await bot.run()`), launched by the TUI via `asyncio.create_task(self._bot.run())` (`src/mmud/tui/app.py`).

### GameState fields the panels render (`src/mmud/state/game_state.py`)

`current_room: str`, `current_hex: str`, `hp/max_hp`, `mana/max_mana`, `monsters_present: list[MonsterSighting]` (`.name`, `.count`, `.exp_each`), `players_present: list[str]`, `party: list`, `kills: int`, `exp: int`, `level: int`, `in_combat: bool`, combat counters (`combat_hits`, `combat_misses`, `combat_special`, `combat_dmg_sum`, `monster_hits`, `monster_misses`, `backstab_attempts`, `backstab_successes`), and the properties `hit_pct: float`, `avg_damage: float`.

### Session fields (`src/mmud/session.py`)

`exp_rate_per_hour() -> float`, `hours_elapsed(now) -> float`, `started_at: float` (monotonic seconds at session start).

### Test style (`tests/conftest.py`)

`asyncio_mode = "auto"` — async tests need no decorator. `FakeConnection(lines)` records every `.send(cmd)` in `.sent`. `make_transcript_bot(lines, **kwargs)` builds a `MudBot` wired to a `FakeConnection`. Web tests will use a lightweight fake bot instead (no network), defined in `tests/web/conftest.py`.

### Dependencies (`pyproject.toml`)

`fastapi`, `uvicorn`, `httpx` (TestClient needs it) are **NOT** present yet — Task 1 adds them as an optional extra `[web]`.

---

## Task 1 — `[web]` config section + optional server wiring

**Why:** The server must be inert unless explicitly enabled. We add a `WebConfig` dataclass, parse it in the loader, document it in the example, add the Python deps, and make `MudBot` construct/start the server only when the section is present.

### Step 1.1 — add deps to `pyproject.toml`

- [ ] Edit `pyproject.toml`. Add an optional-dependencies extra named `web`:

```toml
[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-asyncio", "pytest-unused-port", "textual-dev"]
web = ["fastapi>=0.110", "uvicorn>=0.29", "httpx>=0.27", "websockets>=12.0"]
```

- [ ] Install it into the working environment: `python -m pip install -e '.[web,dev]'` (run from repo root). Verify: `python -c "import fastapi, uvicorn, httpx; print('ok')"` prints `ok`.

### Step 1.2 — `WebConfig` dataclass (test first)

- [ ] Create `tests/config/test_web_config.py`:

```python
from __future__ import annotations
import pathlib
from mmud.config.loader import load_config
from mmud.config.schema import MudConfig, WebConfig


def test_web_config_defaults():
    cfg = WebConfig()
    assert cfg.enabled is False
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8080


def test_mudconfig_has_web_default():
    cfg = MudConfig()
    assert isinstance(cfg.web, WebConfig)
    assert cfg.web.enabled is False


def test_loader_absent_web_section(tmp_path: pathlib.Path):
    p = tmp_path / "char.toml"
    p.write_text('[server]\nhost = "x"\nport = 1\n', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.web.enabled is False  # absent => disabled


def test_loader_parses_web_section(tmp_path: pathlib.Path):
    p = tmp_path / "char.toml"
    p.write_text(
        '[web]\nenabled = true\nhost = "0.0.0.0"\nport = 9000\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.web.enabled is True
    assert cfg.web.host == "0.0.0.0"
    assert cfg.web.port == 9000
```

- [ ] Run `python -m pytest tests/config/test_web_config.py -q` and confirm it FAILS (ImportError on `WebConfig`).

- [ ] Edit `src/mmud/config/schema.py`. Add the dataclass next to the other config dataclasses (e.g. after `UiConfig`):

```python
@dataclass
class WebConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8080
```

- [ ] In the same file, add the field to `MudConfig` (after `ui`):

```python
    ui: UiConfig = field(default_factory=UiConfig)
    web: WebConfig = field(default_factory=WebConfig)
```

- [ ] Edit `src/mmud/config/loader.py`. Add `WebConfig` to the import list from `mmud.config.schema`, then add parsing just before `return cfg`:

```python
    if w := data.get("web"):
        cfg.web = WebConfig(
            enabled=w.get("enabled", False),
            host=w.get("host", "127.0.0.1"),
            port=w.get("port", 8080),
        )
    return cfg
```

- [ ] Run `python -m pytest tests/config/test_web_config.py -q` and confirm it PASSES.

### Step 1.3 — document in `characters/example.toml`

- [ ] Append to `characters/example.toml`:

```toml
# Web control panel (browser UI). Optional; off by default.
# When enabled, the bot starts a FastAPI server bound to host:port.
# SECURITY: binds 127.0.0.1 by default. The panel can SEND game commands.
# Do NOT change host to 0.0.0.0 / expose publicly without adding auth.
[web]
enabled = false
host    = "127.0.0.1"
port    = 8080
```

### Step 1.4 — bot constructs + starts the server only when `[web]` present (test first)

The bot must remain importable and runnable without the `web` extra installed, so the server import is lazy (inside the method, guarded by `enabled`).

- [ ] Create `tests/web/__init__.py` (empty file) and `tests/config/__init__.py` if it does not exist (empty file). (Skip any `__init__.py` that already exists.)

- [ ] Create `tests/web/test_bot_wiring.py`:

```python
from __future__ import annotations
from mmud.config.schema import MudConfig, WebConfig
from mmud.events import GameEventBus
from tests.conftest import make_transcript_bot


def test_no_web_section_means_no_server():
    cfg = MudConfig()  # web.enabled defaults False
    bot = make_transcript_bot([], event_bus=GameEventBus(), config=cfg)
    assert bot.maybe_build_web_server() is None
    assert bot._web_server is None


def test_web_enabled_builds_server():
    cfg = MudConfig()
    cfg.web = WebConfig(enabled=True, host="127.0.0.1", port=8099)
    bot = make_transcript_bot([], event_bus=GameEventBus(), config=cfg)
    server = bot.maybe_build_web_server()
    assert server is not None
    assert bot._web_server is server
    # It registered itself as a bus subscriber for at least HpChanged.
    from mmud.events import HpChanged
    assert HpChanged in bot._bus._subscribers
```

- [ ] Run `python -m pytest tests/web/test_bot_wiring.py -q` and confirm it FAILS.

- [ ] Edit `src/mmud/bot.py`. In `MudBot.__init__`, after `self._redial_delay_s = 5.0`, add:

```python
        self._web_server = None   # WebPanelServer | None, built on demand
```

- [ ] Add this method to `MudBot` (place it near `start_loop`):

```python
    def maybe_build_web_server(self):
        """Construct the web control-panel server iff [web] config is enabled.

        Lazy import so the `web` extra (fastapi/uvicorn) is only required when
        the panel is actually turned on. Idempotent: returns the existing
        server on repeat calls. Returns None when disabled.
        """
        if not self._config.web.enabled:
            return None
        if self._web_server is not None:
            return self._web_server
        from mmud.web.server import WebPanelServer
        self._web_server = WebPanelServer(self)
        return self._web_server
```

- [ ] Run `python -m pytest tests/web/test_bot_wiring.py -q` and confirm it PASSES.

> Note: `WebPanelServer` does not exist yet — `test_web_enabled_builds_server` will fail to import it until Task 2. Mark Step 1.4's second test as expected-to-pass only AFTER Task 2. If working strictly task-by-task, write a temporary minimal `src/mmud/web/server.py` stub with `class WebPanelServer:` that subscribes to the bus, OR run only `test_no_web_section_means_no_server` now and the full file at the end of Task 2. Prefer the latter.

### Step 1.5 — launch the server from the TUI when enabled (wiring only)

- [ ] Edit `src/mmud/tui/app.py` inside `action_toggle_connect`, right after `self._bot_task = asyncio.create_task(self._bot.run())`:

```python
            server = self._bot.maybe_build_web_server()
            if server is not None:
                self._web_task = asyncio.create_task(server.serve())
```

- [ ] Add `self._web_task = None` wherever the app initializes its other task attributes (search for `self._bot_task = None` and add the line beside it).

- [ ] On disconnect (the `else` branch that cancels `self._bot_task`), add:

```python
            if getattr(self, "_web_task", None) is not None:
                self._web_task.cancel()
                self._web_task = None
```

- [ ] Run the full suite: `python -m pytest -q`. Confirm no regressions (the TUI changes are inert when `web.enabled` is False).

---

## Task 2 — Backend `src/mmud/web/server.py`

**Why:** The heart of the panel. One bus subscriber per event type → JSON broadcast over `/ws`; REST endpoints to read state and drive the bot.

### Step 2.1 — replace the stub `src/mmud/web/__init__.py`

- [ ] Edit `src/mmud/web/__init__.py` to:

```python
"""Web control panel: FastAPI + WebSocket UI driven by GameEventBus.

`WebPanelServer` (server.py) registers one subscriber per event dataclass,
serialises each event to JSON, and broadcasts it to all /ws clients. REST
endpoints read GameState/SessionManager and drive the live MudBot. The whole
package is optional — only imported when [web] config is enabled (see
MudBot.maybe_build_web_server).
"""
```

- [ ] Ensure `tests/web/__init__.py` exists (empty) from Task 1.

### Step 2.2 — the event→JSON serializer (test first; full impl in Task 3)

The serializer lives in its own module `src/mmud/web/serialize.py` so it can be unit-tested in isolation. **Its full implementation and per-event tests are Task 3.** For Task 2 we only need its signature: `serialize_event(event) -> dict`, returning a dict with a stable `"type"` key. Create the minimal version now and flesh it out in Task 3.

- [ ] Create `src/mmud/web/serialize.py`:

```python
from __future__ import annotations
import dataclasses


def serialize_event(event: object) -> dict:
    """Convert any GameEventBus event dataclass to a JSON-ready dict.

    The dict always carries a stable "type" discriminator equal to the
    event class name (e.g. "HpChanged"), plus every dataclass field.
    """
    if not dataclasses.is_dataclass(event):
        raise TypeError(f"not a dataclass event: {type(event)!r}")
    payload = dataclasses.asdict(event)
    return {"type": type(event).__name__, **payload}
```

### Step 2.3 — the connection manager (test first)

- [ ] Create `tests/web/test_connection_manager.py`:

```python
from __future__ import annotations
from mmud.web.server import ConnectionManager


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


async def test_broadcast_reaches_all_clients():
    mgr = ConnectionManager()
    a, b = FakeWS(), FakeWS()
    mgr.add(a)
    mgr.add(b)
    await mgr.broadcast({"type": "HpChanged", "hp": 10, "max_hp": 20})
    assert a.sent == [{"type": "HpChanged", "hp": 10, "max_hp": 20}]
    assert b.sent == [{"type": "HpChanged", "hp": 10, "max_hp": 20}]


async def test_remove_stops_delivery():
    mgr = ConnectionManager()
    a = FakeWS()
    mgr.add(a)
    mgr.remove(a)
    await mgr.broadcast({"type": "x"})
    assert a.sent == []


async def test_dead_client_is_dropped_not_raised():
    class Dead(FakeWS):
        async def send_json(self, data):
            raise RuntimeError("socket closed")

    mgr = ConnectionManager()
    dead, ok = Dead(), FakeWS()
    mgr.add(dead)
    mgr.add(ok)
    await mgr.broadcast({"type": "x"})   # must not raise
    assert ok.sent == [{"type": "x"}]
    assert dead not in mgr._clients
```

- [ ] Run `python -m pytest tests/web/test_connection_manager.py -q` and confirm it FAILS.

### Step 2.4 — quick-tool action map (test first)

The Quick Tools panel buttons map to game commands. The compass directions map to single-letter move commands; the action buttons map to MajorMud verbs (per the Ghidra button-set recon). Movement directions are sent via the bot's send path; non-movement actions are also plain commands. `navigate`/`stop` are special-cased to bot methods.

- [ ] Create `tests/web/test_quicktool_map.py`:

```python
from __future__ import annotations
from mmud.web.server import quicktool_command


def test_compass_directions():
    assert quicktool_command("n") == "n"
    assert quicktool_command("ne") == "ne"
    assert quicktool_command("e") == "e"
    assert quicktool_command("se") == "se"
    assert quicktool_command("s") == "s"
    assert quicktool_command("sw") == "sw"
    assert quicktool_command("w") == "w"
    assert quicktool_command("nw") == "nw"
    assert quicktool_command("u") == "u"
    assert quicktool_command("d") == "d"


def test_action_buttons():
    assert quicktool_command("get-all") == "get all"
    assert quicktool_command("drop-all") == "drop all"
    assert quicktool_command("equip-all") == "wear all"
    assert quicktool_command("deposit") == "deposit all"
    assert quicktool_command("search") == "search"
    assert quicktool_command("afk") == "afk"


def test_unknown_action_returns_none():
    assert quicktool_command("frobnicate") is None
```

- [ ] Run `python -m pytest tests/web/test_quicktool_map.py -q` and confirm it FAILS.

### Step 2.5 — write `src/mmud/web/server.py` (full implementation)

- [ ] Create `src/mmud/web/server.py`:

```python
from __future__ import annotations
import pathlib
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import mmud.events as ev
from mmud.web.serialize import serialize_event

# Every event dataclass the panel cares about. The server subscribes one
# broadcast callback per type. Adding a new event => add it here.
_EVENT_TYPES: tuple[type, ...] = (
    ev.LineReceived, ev.HpChanged, ev.MpChanged, ev.RoomChanged,
    ev.EffectApplied, ev.EffectRemoved, ev.CombatChanged,
    ev.ConversationReceived, ev.PlayerSeen, ev.PathStarted, ev.PathStepped,
    ev.SessionStatUpdated, ev.MonstersSeen, ev.TaskChanged,
    ev.ConditionChanged, ev.HangupTriggered, ev.DbImported, ev.DbCollision,
    ev.TravelResynced, ev.TravelEnded,
)

# Quick-tool action id -> game command. Compass dirs are raw move commands;
# action buttons map to MajorMud verbs (Ghidra button-set recon).
_QUICKTOOL: dict[str, str] = {
    "n": "n", "ne": "ne", "e": "e", "se": "se",
    "s": "s", "sw": "sw", "w": "w", "nw": "nw",
    "u": "u", "d": "d",
    "get-all": "get all",
    "drop-all": "drop all",
    "equip-all": "wear all",
    "deposit": "deposit all",
    "search": "search",
    "afk": "afk",
}

_FRONTEND_DIST = pathlib.Path(__file__).parent / "frontend" / "dist"


def quicktool_command(action: str) -> str | None:
    """Map a Quick Tools action id to a game command, or None if unknown."""
    return _QUICKTOOL.get(action)


class ConnectionManager:
    """Tracks live WebSocket clients and broadcasts JSON to all of them."""

    def __init__(self) -> None:
        self._clients: list[Any] = []

    def add(self, ws: Any) -> None:
        self._clients.append(ws)

    def remove(self, ws: Any) -> None:
        if ws in self._clients:
            self._clients.remove(ws)

    async def broadcast(self, message: dict) -> None:
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove(ws)


class CommandBody(BaseModel):
    cmd: str


class QuickToolBody(BaseModel):
    action: str


class WebPanelServer:
    """FastAPI app + WS hub bound to a live MudBot.

    Registers one bus subscriber per event type; each subscriber schedules a
    broadcast of the serialized event to all /ws clients. REST endpoints read
    GameState/SessionManager and drive the bot.
    """

    def __init__(self, bot: Any) -> None:
        self._bot = bot
        self._manager = ConnectionManager()
        self._loop = None  # set in serve(); used to schedule broadcasts
        self.app = self._build_app()
        self._subscribe_all()

    # ---- bus wiring -----------------------------------------------------

    def _subscribe_all(self) -> None:
        bus = self._bot._bus
        if bus is None:
            return
        for event_type in _EVENT_TYPES:
            bus.subscribe(event_type, self._on_event)

    def _on_event(self, event: object) -> None:
        """Bus callback (sync). Schedule the async broadcast on the loop."""
        message = serialize_event(event)
        import asyncio
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
        loop.create_task(self._manager.broadcast(message))

    # ---- snapshot -------------------------------------------------------

    def snapshot(self) -> dict:
        """Full current state for GET /api/state (panel hydration)."""
        s = self._bot._state
        sess = self._bot._session
        import time
        now = time.monotonic()
        return {
            "room": {"code": s.current_room, "hex": s.current_hex},
            "vitals": {
                "hp": s.hp, "max_hp": s.max_hp,
                "mana": s.mana, "max_mana": s.max_mana,
                "in_combat": s.in_combat,
            },
            "progress": {"level": s.level, "exp": s.exp, "kills": s.kills},
            "combat": {
                "hits": s.combat_hits, "misses": s.combat_misses,
                "special": s.combat_special, "dmg_sum": s.combat_dmg_sum,
                "monster_hits": s.monster_hits, "monster_misses": s.monster_misses,
                "backstab_attempts": s.backstab_attempts,
                "backstab_successes": s.backstab_successes,
                "hit_pct": s.hit_pct, "avg_damage": s.avg_damage,
            },
            "session": {
                "hours_elapsed": sess.hours_elapsed(now),
                "exp_rate_per_hour": sess.exp_rate_per_hour(),
            },
            "monsters": [
                {"name": m.name, "count": m.count, "exp_each": m.exp_each}
                for m in s.monsters_present
            ],
            "players": list(s.players_present),
        }

    # ---- app ------------------------------------------------------------

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="mmud control panel")
        bot = self._bot
        manager = self._manager

        @app.get("/api/state")
        async def get_state():
            return self.snapshot()

        @app.post("/api/command")
        async def post_command(body: CommandBody):
            cmd = body.cmd.strip()
            if not cmd:
                return JSONResponse({"detail": "empty command"}, status_code=400)
            await bot._conn.send(cmd)
            return {"ok": True, "sent": cmd}

        @app.post("/api/quicktool")
        async def post_quicktool(body: QuickToolBody):
            action = body.action.strip().lower()
            if action == "navigate":
                return JSONResponse(
                    {"detail": "navigate requires /api/command via the goto UI"},
                    status_code=400,
                )
            cmd = quicktool_command(action)
            if cmd is None:
                return JSONResponse(
                    {"detail": f"unknown action: {action}"}, status_code=400
                )
            await bot._conn.send(cmd)
            return {"ok": True, "action": action, "sent": cmd}

        @app.get("/api/config")
        async def get_config():
            svc = self._config_service()
            if svc is None:
                return JSONResponse(
                    {"detail": "config service unavailable"}, status_code=503
                )
            return svc.as_dict()

        @app.patch("/api/config")
        async def patch_config(patch: dict):
            svc = self._config_service()
            if svc is None:
                return JSONResponse(
                    {"detail": "config service unavailable"}, status_code=503
                )
            svc.apply(patch)
            return svc.as_dict()

        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket):
            await ws.accept()
            manager.add(ws)
            try:
                await ws.send_json({"type": "Snapshot", **self.snapshot()})
                while True:
                    await ws.receive_text()  # keepalive; client may send pings
            except WebSocketDisconnect:
                pass
            finally:
                manager.remove(ws)

        if _FRONTEND_DIST.is_dir():
            app.mount(
                "/", StaticFiles(directory=str(_FRONTEND_DIST), html=True),
                name="static",
            )
        return app

    def _config_service(self):
        """Doc 2 ConfigService bound to the bot's config, or None if absent."""
        try:
            from mmud.config.service import ConfigService  # Doc 2
        except Exception:
            return None
        return ConfigService(self._bot._config)

    # ---- run ------------------------------------------------------------

    async def serve(self) -> None:
        import asyncio
        import uvicorn
        self._loop = asyncio.get_running_loop()
        cfg = self._bot._config.web
        config = uvicorn.Config(
            self.app, host=cfg.host, port=cfg.port, log_level="warning"
        )
        server = uvicorn.Server(config)
        await server.serve()
```

- [ ] Run `python -m pytest tests/web/test_connection_manager.py tests/web/test_quicktool_map.py -q` and confirm they PASS.

### Step 2.6 — endpoint tests with FastAPI TestClient + fake bot (test)

- [ ] Create `tests/web/conftest.py`:

```python
from __future__ import annotations
import pytest
from mmud.events import GameEventBus
from mmud.state.game_state import GameState
from mmud.session import SessionManager
from mmud.config.schema import MudConfig


class FakeConn:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, command: str) -> None:
        self.sent.append(command)


class FakeBot:
    """Minimal stand-in exposing exactly what WebPanelServer reads."""

    def __init__(self) -> None:
        self._bus = GameEventBus()
        self._state = GameState()
        self._config = MudConfig()
        self._session = SessionManager(self._config.session, now=lambda: 0.0)
        self._conn = FakeConn()


@pytest.fixture
def fake_bot():
    return FakeBot()


@pytest.fixture
def server(fake_bot):
    from mmud.web.server import WebPanelServer
    return WebPanelServer(fake_bot)


@pytest.fixture
def client(server):
    from fastapi.testclient import TestClient
    return TestClient(server.app)
```

- [ ] Create `tests/web/test_endpoints.py`:

```python
from __future__ import annotations
from mmud.events import HpChanged


def test_state_returns_snapshot(client, fake_bot):
    fake_bot._state.set_hp(30, 90)
    fake_bot._state.set_level(12)
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    assert body["vitals"]["hp"] == 30
    assert body["vitals"]["max_hp"] == 90
    assert body["progress"]["level"] == 12


def test_command_reaches_send_stub(client, fake_bot):
    r = client.post("/api/command", json={"cmd": "look"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "sent": "look"}
    assert fake_bot._conn.sent == ["look"]


def test_empty_command_rejected(client):
    r = client.post("/api/command", json={"cmd": "   "})
    assert r.status_code == 400


def test_quicktool_compass(client, fake_bot):
    r = client.post("/api/quicktool", json={"action": "ne"})
    assert r.status_code == 200
    assert fake_bot._conn.sent == ["ne"]


def test_quicktool_action_button(client, fake_bot):
    r = client.post("/api/quicktool", json={"action": "deposit"})
    assert r.status_code == 200
    assert fake_bot._conn.sent == ["deposit all"]


def test_quicktool_unknown_400(client):
    r = client.post("/api/quicktool", json={"action": "frobnicate"})
    assert r.status_code == 400


def test_config_503_without_doc2(client):
    # Doc 2 ConfigService not present => 503
    r = client.get("/api/config")
    assert r.status_code == 503


def test_ws_broadcasts_posted_event(client, fake_bot):
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()        # hydration snapshot
        assert first["type"] == "Snapshot"
        fake_bot._bus.post(HpChanged(hp=5, max_hp=40))
        msg = ws.receive_json()
        assert msg == {"type": "HpChanged", "hp": 5, "max_hp": 40}
```

- [ ] Run `python -m pytest tests/web/test_endpoints.py -q` and confirm it PASSES.

> If `test_ws_broadcasts_posted_event` is flaky because the broadcast task hasn't run, the TestClient's WebSocket runs in the same event loop; `_on_event` uses `asyncio.get_running_loop()` when `self._loop` is unset, schedules a task, and `ws.receive_json()` pumps the loop until the message arrives. This is the intended path — keep it.

- [ ] Now revisit Task 1 Step 1.4's `test_web_enabled_builds_server` — run `python -m pytest tests/web/test_bot_wiring.py -q` and confirm BOTH tests PASS (the real `WebPanelServer` now exists and subscribes to the bus).

---

## Task 3 — Event-to-panel mapping + full serializer tests

**Why:** Lock down the JSON contract the frontend depends on, and prove every event serializes with a stable `"type"`.

### Event → Panel → JSON shape

| Event (`"type"`) | Panel | JSON shape |
|---|---|---|
| `LineReceived` | Terminal | `{type, line}` |
| `HpChanged` | Terminal prompt, PlayerStats | `{type, hp, max_hp}` |
| `MpChanged` | Terminal prompt | `{type, mp, max_mp}` |
| `RoomChanged` | Terminal (room header), QuickTools | `{type, code, name}` |
| `EffectApplied` | Terminal status | `{type, name, flags}` |
| `EffectRemoved` | Terminal status | `{type, name}` |
| `CombatChanged` | Terminal, PlayerStats | `{type, in_combat}` |
| `ConversationReceived` | Conversations | `{type, channel, sender, text}` |
| `PlayerSeen` | OnlinePlayers | `{type, name, level, rep, gang}` |
| `PathStarted` | SessionStats (activity) | `{type, name}` |
| `PathStepped` | SessionStats (lap counter) | `{type, command, lap}` |
| `SessionStatUpdated` | SessionStats / PlayerStats | `{type, key, value}` |
| `MonstersSeen` | Terminal (room monsters) | `{type, monsters}` |
| `TaskChanged` | SessionStats (activity) | `{type, task_type, status}` |
| `ConditionChanged` | Terminal status, SessionStats | `{type, name, active}` |
| `HangupTriggered` | Terminal banner | `{type, reason}` |
| `DbImported` | Terminal banner | `{type, added, updated, collisions}` |
| `DbCollision` | Terminal banner | `{type, db, record_id}` |
| `TravelResynced` | SessionStats (activity) | `{type, from_step, to_step}` |
| `TravelEnded` | SessionStats (activity) | `{type, reason}` |
| `Snapshot` (server-synthesized) | all panels | `{type:"Snapshot", room, vitals, progress, combat, session, monsters, players}` |

### Step 3.1 — per-event serializer tests (test first)

- [ ] Create `tests/web/test_serialize.py`:

```python
from __future__ import annotations
import pytest
import mmud.events as ev
from mmud.web.serialize import serialize_event

CASES = [
    (ev.LineReceived("hi"), {"type": "LineReceived", "line": "hi"}),
    (ev.HpChanged(10, 20), {"type": "HpChanged", "hp": 10, "max_hp": 20}),
    (ev.MpChanged(3, 7), {"type": "MpChanged", "mp": 3, "max_mp": 7}),
    (ev.RoomChanged("ABCD", "A Room"),
     {"type": "RoomChanged", "code": "ABCD", "name": "A Room"}),
    (ev.EffectApplied("bless", 4),
     {"type": "EffectApplied", "name": "bless", "flags": 4}),
    (ev.EffectRemoved("bless"), {"type": "EffectRemoved", "name": "bless"}),
    (ev.CombatChanged(True), {"type": "CombatChanged", "in_combat": True}),
    (ev.ConversationReceived("tell", "Bob", "hi"),
     {"type": "ConversationReceived", "channel": "tell", "sender": "Bob", "text": "hi"}),
    (ev.PlayerSeen("Bob", "L5", "Neutral", "Gang"),
     {"type": "PlayerSeen", "name": "Bob", "level": "L5", "rep": "Neutral", "gang": "Gang"}),
    (ev.PathStarted("loop1"), {"type": "PathStarted", "name": "loop1"}),
    (ev.PathStepped("n", 2), {"type": "PathStepped", "command": "n", "lap": 2}),
    (ev.SessionStatUpdated("kills", "3"),
     {"type": "SessionStatUpdated", "key": "kills", "value": "3"}),
    (ev.MonstersSeen(["rat", "bat"]),
     {"type": "MonstersSeen", "monsters": ["rat", "bat"]}),
    (ev.TaskChanged("RESTING", "started"),
     {"type": "TaskChanged", "task_type": "RESTING", "status": "started"}),
    (ev.ConditionChanged("POISONED", True),
     {"type": "ConditionChanged", "name": "POISONED", "active": True}),
    (ev.HangupTriggered("death"), {"type": "HangupTriggered", "reason": "death"}),
    (ev.DbImported(1, 2, 3),
     {"type": "DbImported", "added": 1, "updated": 2, "collisions": 3}),
    (ev.DbCollision("monsters", 42),
     {"type": "DbCollision", "db": "monsters", "record_id": 42}),
    (ev.TravelResynced(1, 4),
     {"type": "TravelResynced", "from_step": 1, "to_step": 4}),
    (ev.TravelEnded("arrived"), {"type": "TravelEnded", "reason": "arrived"}),
]


@pytest.mark.parametrize("event,expected", CASES)
def test_serialize_event(event, expected):
    assert serialize_event(event) == expected


def test_every_event_type_is_covered():
    covered = {type(e).__name__ for e, _ in CASES}
    declared = {
        name for name in dir(ev)
        if name[0].isupper() and name not in {"GameEventBus", "Callable"}
    }
    assert declared <= covered, f"uncovered events: {declared - covered}"


def test_non_dataclass_raises():
    with pytest.raises(TypeError):
        serialize_event(object())
```

- [ ] Run `python -m pytest tests/web/test_serialize.py -q`. The serializer from Step 2.2 already satisfies these. Confirm PASS. If `test_every_event_type_is_covered` fails, add the missing event(s) to BOTH `CASES` here and `_EVENT_TYPES` in `server.py`.

---

## Task 4 — React/Vite frontend (`src/mmud/web/frontend/`)

**Why:** The actual panels. A `useWebSocket` hook keeps a live state object updated from `/ws`, dispatching by `"type"`. Components render the MegaMud panel layout.

### Step 4.1 — scaffold

- [ ] Create `src/mmud/web/frontend/package.json`:

```json
{
  "name": "mmud-control-panel",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "ansi-to-html": "^0.7.2"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^24.1.0",
    "typescript": "^5.5.3",
    "vite": "^5.3.4",
    "vitest": "^2.0.4"
  }
}
```

- [ ] Create `src/mmud/web/frontend/vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8080",
      "/ws": { target: "ws://127.0.0.1:8080", ws: true },
    },
  },
  test: { environment: "jsdom", globals: true },
});
```

- [ ] Create `src/mmud/web/frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "types": ["vitest/globals"]
  },
  "include": ["src"]
}
```

- [ ] Create `src/mmud/web/frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>mmud control panel</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] Create `src/mmud/web/frontend/src/main.tsx`:

```tsx
import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] Install: `cd src/mmud/web/frontend && npm install`. Verify it completes without error.

### Step 4.2 — the panel state model + reducer (test first)

The reducer is pure and unit-testable without React. It owns the single source of truth the panels read.

- [ ] Create `src/mmud/web/frontend/src/panelState.ts`:

```ts
export interface PanelState {
  terminal: string[];            // recent game lines (ANSI preserved)
  room: { code: string; name: string };
  vitals: { hp: number; maxHp: number; mana: number; maxMana: number; inCombat: boolean };
  progress: { level: number; exp: number; kills: number };
  combat: {
    hits: number; misses: number; special: number; dmgSum: number;
    monsterHits: number; monsterMisses: number;
    backstabAttempts: number; backstabSuccesses: number;
    hitPct: number; avgDamage: number;
  };
  session: { hoursElapsed: number; expRatePerHour: number; stats: Record<string, string> };
  conversations: { channel: string; sender: string; text: string }[];
  players: Record<string, { name: string; level: string; rep: string; gang: string }>;
  monsters: { name: string; count: number; expEach: number }[];
  conditions: Record<string, boolean>;
  activity: string;              // latest task/travel status line
}

export type PanelEvent = { type: string; [k: string]: any };

export const initialPanelState: PanelState = {
  terminal: [],
  room: { code: "", name: "" },
  vitals: { hp: 0, maxHp: 0, mana: 0, maxMana: 0, inCombat: false },
  progress: { level: 0, exp: 0, kills: 0 },
  combat: {
    hits: 0, misses: 0, special: 0, dmgSum: 0,
    monsterHits: 0, monsterMisses: 0,
    backstabAttempts: 0, backstabSuccesses: 0, hitPct: 0, avgDamage: 0,
  },
  session: { hoursElapsed: 0, expRatePerHour: 0, stats: {} },
  conversations: [],
  players: {},
  monsters: [],
  conditions: {},
  activity: "",
};

const TERMINAL_MAX = 500;
const CONVO_MAX = 200;

export function panelReducer(state: PanelState, ev: PanelEvent): PanelState {
  switch (ev.type) {
    case "Snapshot":
      return {
        ...state,
        room: { code: ev.room.code, name: state.room.name },
        vitals: {
          hp: ev.vitals.hp, maxHp: ev.vitals.max_hp,
          mana: ev.vitals.mana, maxMana: ev.vitals.max_mana,
          inCombat: ev.vitals.in_combat,
        },
        progress: { level: ev.progress.level, exp: ev.progress.exp, kills: ev.progress.kills },
        combat: {
          hits: ev.combat.hits, misses: ev.combat.misses,
          special: ev.combat.special, dmgSum: ev.combat.dmg_sum,
          monsterHits: ev.combat.monster_hits, monsterMisses: ev.combat.monster_misses,
          backstabAttempts: ev.combat.backstab_attempts,
          backstabSuccesses: ev.combat.backstab_successes,
          hitPct: ev.combat.hit_pct, avgDamage: ev.combat.avg_damage,
        },
        session: {
          ...state.session,
          hoursElapsed: ev.session.hours_elapsed,
          expRatePerHour: ev.session.exp_rate_per_hour,
        },
        monsters: ev.monsters.map((m: any) => ({
          name: m.name, count: m.count, expEach: m.exp_each,
        })),
        players: ev.players.reduce(
          (acc: PanelState["players"], name: string) => {
            acc[name] = acc[name] ?? { name, level: "", rep: "", gang: "" };
            return acc;
          },
          { ...state.players },
        ),
      };
    case "LineReceived":
      return { ...state, terminal: [...state.terminal, ev.line].slice(-TERMINAL_MAX) };
    case "HpChanged":
      return { ...state, vitals: { ...state.vitals, hp: ev.hp, maxHp: ev.max_hp } };
    case "MpChanged":
      return { ...state, vitals: { ...state.vitals, mana: ev.mp, maxMana: ev.max_mp } };
    case "RoomChanged":
      return { ...state, room: { code: ev.code, name: ev.name } };
    case "CombatChanged":
      return { ...state, vitals: { ...state.vitals, inCombat: ev.in_combat } };
    case "ConversationReceived":
      return {
        ...state,
        conversations: [
          ...state.conversations,
          { channel: ev.channel, sender: ev.sender, text: ev.text },
        ].slice(-CONVO_MAX),
      };
    case "PlayerSeen":
      return {
        ...state,
        players: {
          ...state.players,
          [ev.name]: { name: ev.name, level: ev.level, rep: ev.rep, gang: ev.gang },
        },
      };
    case "MonstersSeen":
      return {
        ...state,
        monsters: ev.monsters.map((n: string) => ({ name: n, count: 1, expEach: 0 })),
      };
    case "ConditionChanged":
      return { ...state, conditions: { ...state.conditions, [ev.name]: ev.active } };
    case "SessionStatUpdated":
      return {
        ...state,
        session: { ...state.session, stats: { ...state.session.stats, [ev.key]: ev.value } },
      };
    case "TaskChanged":
      return { ...state, activity: `${ev.task_type}: ${ev.status}` };
    case "PathStarted":
      return { ...state, activity: `path ${ev.name}` };
    case "PathStepped":
      return { ...state, activity: `${ev.command} (lap ${ev.lap})` };
    case "TravelResynced":
      return { ...state, activity: `resync ${ev.from_step}->${ev.to_step}` };
    case "TravelEnded":
      return { ...state, activity: `travel ${ev.reason}` };
    case "HangupTriggered":
      return { ...state, activity: `HANGUP: ${ev.reason}` };
    default:
      return state;
  }
}
```

- [ ] Create `src/mmud/web/frontend/src/panelState.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { initialPanelState, panelReducer } from "./panelState";

describe("panelReducer", () => {
  it("appends terminal lines", () => {
    const s = panelReducer(initialPanelState, { type: "LineReceived", line: "hello" });
    expect(s.terminal).toEqual(["hello"]);
  });

  it("updates hp", () => {
    const s = panelReducer(initialPanelState, { type: "HpChanged", hp: 12, max_hp: 40 });
    expect(s.vitals.hp).toBe(12);
    expect(s.vitals.maxHp).toBe(40);
  });

  it("collects conversations", () => {
    const s = panelReducer(initialPanelState, {
      type: "ConversationReceived", channel: "tell", sender: "Bob", text: "hi",
    });
    expect(s.conversations).toEqual([{ channel: "tell", sender: "Bob", text: "hi" }]);
  });

  it("indexes players by name", () => {
    const s = panelReducer(initialPanelState, {
      type: "PlayerSeen", name: "Bob", level: "L5", rep: "Neutral", gang: "G",
    });
    expect(s.players["Bob"]).toEqual({ name: "Bob", level: "L5", rep: "Neutral", gang: "G" });
  });

  it("tracks session stats by key", () => {
    const s = panelReducer(initialPanelState, {
      type: "SessionStatUpdated", key: "kills", value: "7",
    });
    expect(s.session.stats["kills"]).toBe("7");
  });

  it("hydrates from a Snapshot", () => {
    const snap = {
      type: "Snapshot",
      room: { code: "ABCD", hex: "1A" },
      vitals: { hp: 5, max_hp: 50, mana: 1, max_mana: 9, in_combat: true },
      progress: { level: 3, exp: 1000, kills: 2 },
      combat: {
        hits: 10, misses: 2, special: 1, dmg_sum: 80,
        monster_hits: 4, monster_misses: 3,
        backstab_attempts: 2, backstab_successes: 1, hit_pct: 80, avg_damage: 8,
      },
      session: { hours_elapsed: 1.5, exp_rate_per_hour: 666 },
      monsters: [{ name: "rat", count: 2, exp_each: 5 }],
      players: ["Bob"],
    };
    const s = panelReducer(initialPanelState, snap);
    expect(s.vitals.hp).toBe(5);
    expect(s.progress.level).toBe(3);
    expect(s.combat.hitPct).toBe(80);
    expect(s.session.expRatePerHour).toBe(666);
    expect(s.monsters[0]).toEqual({ name: "rat", count: 2, expEach: 5 });
    expect(s.players["Bob"].name).toBe("Bob");
  });

  it("ignores unknown event types", () => {
    const s = panelReducer(initialPanelState, { type: "Nope" });
    expect(s).toBe(initialPanelState);
  });
});
```

- [ ] Run `cd src/mmud/web/frontend && npm run test` and confirm the reducer tests PASS.

### Step 4.3 — the `useWebSocket` hook

- [ ] Create `src/mmud/web/frontend/src/useWebSocket.ts`:

```ts
import { useEffect, useReducer, useRef } from "react";
import { initialPanelState, panelReducer, PanelEvent } from "./panelState";

export function useWebSocket(url = "/ws") {
  const [state, dispatch] = useReducer(panelReducer, initialPanelState);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}${url}`);
    wsRef.current = ws;
    ws.onmessage = (e) => {
      const ev = JSON.parse(e.data) as PanelEvent;
      dispatch(ev);
    };
    return () => ws.close();
  }, [url]);

  return state;
}

export async function sendCommand(cmd: string): Promise<void> {
  await fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cmd }),
  });
}

export async function quickTool(action: string): Promise<void> {
  await fetch("/api/quicktool", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
}
```

### Step 4.4 — QuickTools component (FULL)

- [ ] Create `src/mmud/web/frontend/src/components/QuickTools.tsx`:

```tsx
import React from "react";
import { quickTool } from "../useWebSocket";
import { PanelState } from "../panelState";

const COMPASS: (string | null)[][] = [
  ["nw", "n", "ne"],
  ["w", null, "e"],
  ["sw", "s", "se"],
];

const ACTIONS: { id: string; label: string }[] = [
  { id: "get-all", label: "Get-All" },
  { id: "drop-all", label: "Drop-All" },
  { id: "equip-all", label: "Equip-All" },
  { id: "deposit", label: "Deposit" },
  { id: "search", label: "Search" },
  { id: "afk", label: "AFK" },
];

export function QuickTools({ state }: { state: PanelState }) {
  const fire = (action: string) => () => { void quickTool(action); };
  const income = state.session.stats["income_rate"] ?? "0/hr";

  return (
    <div className="quick-tools">
      <h3>Quick Tools</h3>
      <div className="compass">
        {COMPASS.map((row, r) => (
          <div className="compass-row" key={r}>
            {row.map((dir, c) =>
              dir ? (
                <button key={c} className="compass-btn" onClick={fire(dir)}>
                  {dir.toUpperCase()}
                </button>
              ) : (
                <div key={c} className="compass-center">
                  <button className="ud-btn" onClick={fire("u")}>U</button>
                  <button className="ud-btn" onClick={fire("d")}>D</button>
                </div>
              ),
            )}
          </div>
        ))}
      </div>
      <div className="action-buttons">
        {ACTIONS.map((a) => (
          <button key={a.id} className="action-btn" onClick={fire(a.id)}>
            {a.label}
          </button>
        ))}
      </div>
      <div className="income">Income: {income}</div>
    </div>
  );
}
```

### Step 4.5 — PlayerStats component (FULL — Experience + Combat Accuracy with R:/A: columns)

The classic panel shows Combat Accuracy as percentages with two sub-columns: **R:** (this Round) and **A:** (All session). With a single live `GameState` we have session totals only, so **A:** is computed from the running counters and **R:** mirrors the latest delta the server reports (placeholder identical to A: until Doc 1 supplies per-round counters). Both columns are wired so Doc 1 can fill **R:** later.

- [ ] Create `src/mmud/web/frontend/src/components/PlayerStats.tsx`:

```tsx
import React from "react";
import { PanelState } from "../panelState";

function pct(n: number, d: number): string {
  return d > 0 ? `${Math.round((n / d) * 100)}%` : "0%";
}

export function PlayerStats({ state }: { state: PanelState }) {
  const c = state.combat;
  const attacks = c.hits + c.misses + c.special;
  const monsterAttacks = c.monsterHits + c.monsterMisses;
  const s = state.session;

  // Combat Accuracy rows. R: = latest round (Doc 1 fills; mirrors A: for now).
  const rows: { label: string; a: string; r: string }[] = [
    { label: "Miss", a: pct(c.misses, attacks), r: pct(c.misses, attacks) },
    { label: "Hit", a: pct(c.hits, attacks), r: pct(c.hits, attacks) },
    { label: "Extra", a: pct(c.special, attacks), r: pct(c.special, attacks) },
    { label: "Crit", a: s.stats["crit_pct"] ?? "0%", r: s.stats["crit_pct"] ?? "0%" },
    {
      label: "BS",
      a: pct(c.backstabSuccesses, c.backstabAttempts),
      r: pct(c.backstabSuccesses, c.backstabAttempts),
    },
    { label: "Cast", a: s.stats["cast_pct"] ?? "0%", r: s.stats["cast_pct"] ?? "0%" },
    {
      label: "Round",
      a: pct(c.monsterMisses, monsterAttacks),
      r: pct(c.monsterMisses, monsterAttacks),
    },
  ];

  const expNeeded = s.stats["exp_needed"] ?? "?";
  const willLevelIn = s.stats["will_level_in"] ?? "?";

  return (
    <div className="player-stats">
      <h3>Player Statistics</h3>

      <section className="experience">
        <h4>Experience</h4>
        <div className="stat-row"><span>Duration</span><span>{s.hoursElapsed.toFixed(2)} h</span></div>
        <div className="stat-row"><span>Exp made</span><span>{state.progress.exp}</span></div>
        <div className="stat-row"><span>Exp needed</span><span>{expNeeded}</span></div>
        <div className="stat-row"><span>Exp rate</span><span>{Math.round(s.expRatePerHour)}/hr</span></div>
        <div className="stat-row"><span>Will level in</span><span>{willLevelIn}</span></div>
      </section>

      <section className="combat-accuracy">
        <h4>Combat Accuracy</h4>
        <div className="accuracy-header">
          <span className="col-label"></span>
          <span className="col-r">R:</span>
          <span className="col-a">A:</span>
        </div>
        {rows.map((row) => (
          <div className="accuracy-row" key={row.label}>
            <span className="col-label">{row.label}</span>
            <span className="col-r">{row.r}</span>
            <span className="col-a">{row.a}</span>
          </div>
        ))}
      </section>
    </div>
  );
}
```

### Step 4.6 — remaining component skeletons + event field bindings

Each skeleton reads `state` (from `useWebSocket`) and binds the documented fields. Implement each as shown; styling is left to a single `App.css` (Task 4.8).

- [ ] Create `src/mmud/web/frontend/src/components/Terminal.tsx`:

```tsx
import React, { useMemo, useRef, useEffect } from "react";
import Convert from "ansi-to-html";
import { PanelState } from "../panelState";

// Bindings: state.terminal (LineReceived), state.room (RoomChanged),
// state.vitals.hp/maxHp/mana/maxMana (HpChanged/MpChanged), inCombat (CombatChanged).
export function Terminal({ state }: { state: PanelState }) {
  const convert = useMemo(() => new Convert({ newline: true }), []);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollTo(0, ref.current.scrollHeight); }, [state.terminal]);
  const html = useMemo(
    () => state.terminal.map((l) => convert.toHtml(l)).join("<br/>"),
    [state.terminal, convert],
  );
  const v = state.vitals;
  return (
    <div className="terminal">
      <div className="room-header">
        {state.room.name || state.room.code} {state.vitals.inCombat ? "[COMBAT]" : ""}
      </div>
      <div className="terminal-body" ref={ref} dangerouslySetInnerHTML={{ __html: html }} />
      <div className="prompt">
        [HP={v.hp}/{v.maxHp}] [MP={v.mana}/{v.maxMana}]
      </div>
    </div>
  );
}
```

- [ ] Create `src/mmud/web/frontend/src/components/Conversations.tsx`:

```tsx
import React from "react";
import { PanelState } from "../panelState";

// Binding: state.conversations[] (ConversationReceived: channel/sender/text).
export function Conversations({ state }: { state: PanelState }) {
  return (
    <div className="conversations">
      <h3>Conversations</h3>
      <div className="convo-body">
        {state.conversations.map((m, i) => (
          <div className={`convo-line channel-${m.channel}`} key={i}>
            <span className="convo-channel">[{m.channel}]</span>{" "}
            <span className="convo-sender">{m.sender}:</span>{" "}
            <span className="convo-text">{m.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] Create `src/mmud/web/frontend/src/components/OnlinePlayers.tsx`:

```tsx
import React from "react";
import { PanelState } from "../panelState";

// Binding: state.players (PlayerSeen: name/level/rep/gang).
export function OnlinePlayers({ state }: { state: PanelState }) {
  const players = Object.values(state.players);
  return (
    <div className="online-players">
      <h3>Online Players</h3>
      <table>
        <thead>
          <tr><th>Name</th><th>Level</th><th>Rep</th><th>Gang</th></tr>
        </thead>
        <tbody>
          {players.map((p) => (
            <tr key={p.name}>
              <td>{p.name}</td><td>{p.level}</td><td>{p.rep}</td><td>{p.gang}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] Create `src/mmud/web/frontend/src/components/SessionStats.tsx`:

```tsx
import React from "react";
import { PanelState } from "../panelState";

// Bindings: state.session.hoursElapsed (Time/Online), state.session.stats[...]
// from SessionStatUpdated (Doc 1 supplies: dialed/failed/connected/lost_carrier,
// people_seen/attacked, killed/had_to_run/health_low, sneak_pct/dodge_pct,
// deposited/income_rate). Missing keys render "0"/"-".
export function SessionStats({ state }: { state: PanelState }) {
  const st = state.session.stats;
  const g = (k: string, dflt = "0") => st[k] ?? dflt;
  return (
    <div className="session-stats">
      <h3>Session Statistics</h3>
      <section>
        <h4>Time</h4>
        <div className="stat-row"><span>MegaMud</span><span>{g("megamud_time", "-")}</span></div>
        <div className="stat-row"><span>Online</span><span>{state.session.hoursElapsed.toFixed(2)} h</span></div>
      </section>
      <section>
        <h4>Comms</h4>
        <div className="stat-row"><span>Dialed</span><span>{g("dialed")}</span></div>
        <div className="stat-row"><span>Failed</span><span>{g("failed")}</span></div>
        <div className="stat-row"><span>Connected</span><span>{g("connected")}</span></div>
        <div className="stat-row"><span>Lost carrier</span><span>{g("lost_carrier")}</span></div>
      </section>
      <section>
        <h4>Visitors</h4>
        <div className="stat-row"><span>People seen</span><span>{g("people_seen")}</span></div>
        <div className="stat-row"><span>Attacked</span><span>{g("attacked")}</span></div>
      </section>
      <section>
        <h4>Monsters</h4>
        <div className="stat-row"><span>Killed</span><span>{g("kills")}</span></div>
        <div className="stat-row"><span>Had to run</span><span>{g("had_to_run")}</span></div>
        <div className="stat-row"><span>Health low</span><span>{g("health_low")}</span></div>
      </section>
      <section>
        <h4>Other</h4>
        <div className="stat-row"><span>Sneak%</span><span>{g("sneak_pct", "0%")}</span></div>
        <div className="stat-row"><span>Dodge%</span><span>{g("dodge_pct", "0%")}</span></div>
        <div className="stat-row"><span>Deposited</span><span>{g("deposited")}</span></div>
        <div className="stat-row"><span>Income rate</span><span>{g("income_rate", "0/hr")}</span></div>
      </section>
    </div>
  );
}
```

- [ ] Create `src/mmud/web/frontend/src/components/Settings.tsx`:

```tsx
import React, { useEffect, useState } from "react";

// Uses Doc 2 ConfigService via GET/PATCH /api/config. When the service is
// absent the API returns 503 and we show a banner instead of the editor.
export function Settings() {
  const [config, setConfig] = useState<Record<string, any> | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    fetch("/api/config").then(async (r) => {
      if (r.status === 503) { setUnavailable(true); return; }
      setConfig(await r.json());
    });
  }, []);

  if (unavailable) {
    return <div className="settings"><h3>Settings</h3><p>Config service not available.</p></div>;
  }
  if (!config) return <div className="settings"><h3>Settings</h3><p>Loading…</p></div>;

  const save = async (patch: Record<string, any>) => {
    const r = await fetch("/api/config", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (r.ok) setConfig(await r.json());
  };

  return (
    <div className="settings">
      <h3>Settings</h3>
      <pre>{JSON.stringify(config, null, 2)}</pre>
      <button onClick={() => save({})}>Reload</button>
    </div>
  );
}
```

### Step 4.7 — App shell + command input

- [ ] Create `src/mmud/web/frontend/src/App.tsx`:

```tsx
import React, { useState } from "react";
import "./App.css";
import { useWebSocket, sendCommand } from "./useWebSocket";
import { Terminal } from "./components/Terminal";
import { Conversations } from "./components/Conversations";
import { OnlinePlayers } from "./components/OnlinePlayers";
import { SessionStats } from "./components/SessionStats";
import { PlayerStats } from "./components/PlayerStats";
import { QuickTools } from "./components/QuickTools";
import { Settings } from "./components/Settings";

export function App() {
  const state = useWebSocket();
  const [cmd, setCmd] = useState("");
  const [showSettings, setShowSettings] = useState(false);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (cmd.trim()) { void sendCommand(cmd); setCmd(""); }
  };

  return (
    <div className="app">
      <header>
        <span>mmud control panel</span>
        <button onClick={() => setShowSettings((v) => !v)}>
          {showSettings ? "Panels" : "Settings"}
        </button>
      </header>
      {showSettings ? (
        <Settings />
      ) : (
        <div className="grid">
          <div className="main-col">
            <Terminal state={state} />
            <form className="command-bar" onSubmit={submit}>
              <input
                value={cmd}
                onChange={(e) => setCmd(e.target.value)}
                placeholder="Type a command…"
                autoFocus
              />
              <button type="submit">Send</button>
            </form>
            <Conversations state={state} />
          </div>
          <div className="side-col">
            <PlayerStats state={state} />
            <SessionStats state={state} />
            <OnlinePlayers state={state} />
            <QuickTools state={state} />
          </div>
        </div>
      )}
    </div>
  );
}
```

### Step 4.8 — minimal stylesheet

- [ ] Create `src/mmud/web/frontend/src/App.css`:

```css
:root { color-scheme: dark; }
body { margin: 0; font-family: "Courier New", monospace; background: #0b0b0b; color: #cfcfcf; }
.app header { display: flex; justify-content: space-between; align-items: center;
  padding: 4px 8px; background: #1a1a2e; }
.grid { display: grid; grid-template-columns: 1fr 360px; gap: 8px; padding: 8px; }
.main-col { display: flex; flex-direction: column; gap: 8px; }
.side-col { display: flex; flex-direction: column; gap: 8px; }
.terminal-body { height: 50vh; overflow-y: auto; background: #000; padding: 6px;
  white-space: pre-wrap; word-break: break-word; }
.room-header { background: #16213e; padding: 2px 6px; font-weight: bold; }
.prompt { background: #0f3460; padding: 2px 6px; }
.command-bar { display: flex; gap: 4px; }
.command-bar input { flex: 1; background: #111; color: #cfcfcf; border: 1px solid #333; padding: 4px; }
.convo-body { height: 18vh; overflow-y: auto; background: #050510; padding: 4px; }
.channel-tell { color: #7ec8e3; } .channel-shout { color: #e3a87e; }
.channel-party { color: #9ee37e; } .channel-gossip { color: #c89ee3; }
.compass { display: grid; gap: 2px; width: 150px; margin: 0 auto; }
.compass-row { display: flex; gap: 2px; }
.compass-btn, .ud-btn, .action-btn { background: #1a1a2e; color: #cfcfcf;
  border: 1px solid #333; cursor: pointer; }
.compass-btn { width: 48px; height: 32px; }
.compass-center { display: flex; gap: 2px; width: 48px; }
.ud-btn { width: 23px; height: 32px; }
.action-buttons { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin-top: 6px; }
.action-btn { height: 28px; }
.stat-row, .accuracy-row, .accuracy-header { display: grid;
  grid-template-columns: 1fr auto auto; gap: 8px; padding: 1px 4px; }
.stat-row { grid-template-columns: 1fr auto; }
.col-r, .col-a { width: 48px; text-align: right; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { text-align: left; border-bottom: 1px solid #222; padding: 1px 4px; }
section h4 { margin: 6px 0 2px; border-bottom: 1px solid #333; }
```

### Step 4.9 — verify the frontend builds + tests pass

- [ ] `cd src/mmud/web/frontend && npm run test` — reducer tests PASS.
- [ ] `cd src/mmud/web/frontend && npm run build` — completes; `dist/` is produced.
- [ ] Confirm FastAPI now serves the SPA: with `dist/` present, `WebPanelServer` mounts `StaticFiles` at `/`. Add `tests/web/test_static_mount.py`:

```python
from __future__ import annotations
import pathlib
from mmud.web.server import _FRONTEND_DIST


def test_static_mount_path_points_at_dist():
    assert _FRONTEND_DIST.name == "dist"
    assert _FRONTEND_DIST.parent.name == "frontend"
    # When a build exists, the app serves it; when not, /api still works.
    assert isinstance(_FRONTEND_DIST, pathlib.Path)
```

- [ ] Run `python -m pytest tests/web/test_static_mount.py -q` — PASS.

### Step 4.10 — gitignore the build artifacts + node_modules

- [ ] Append to `.gitignore` (create if missing):

```
src/mmud/web/frontend/node_modules/
src/mmud/web/frontend/dist/
```

---

## Task 5 — Docs + run

### Step 5.1 — README section

- [ ] Add a `## Web Control Panel (browser UI)` section to `README.md` (after the TUI section) containing:

```markdown
## Web Control Panel (browser UI)

A browser UI that mirrors MegaMud's classic multi-window layout (game terminal,
conversations, player/session statistics, online players, quick-tools compass +
action buttons), driven live by the same `GameEventBus` the TUI uses. It is
optional and off by default.

### Install

```bash
# Python extras (FastAPI + uvicorn):
python -m pip install -e '.[web]'

# Build the SPA (one time, or after frontend changes):
cd src/mmud/web/frontend
npm install
npm run build
```

### Enable

Add to your character `.toml`:

```toml
[web]
enabled = true
host    = "127.0.0.1"   # localhost only — see SECURITY below
port    = 8080
```

### Launch

Run the TUI as usual (`python -m mmud.tui --char characters/yours.toml`) and
connect. When `[web].enabled = true` the bot starts the panel automatically;
open `http://127.0.0.1:8080` in your browser. The built SPA is served by
FastAPI from `src/mmud/web/frontend/dist`. For frontend development with hot
reload run `npm run dev` in the frontend directory (it proxies `/api` and `/ws`
to port 8080).

### SECURITY

The panel binds **127.0.0.1 (localhost) by default** and is unauthenticated.
**It can send game commands and edit your config.** Do NOT change `host` to
`0.0.0.0` or expose the port publicly without putting an authenticating reverse
proxy (or SSH tunnel) in front of it. Anyone who can reach the port can drive
your character.
```

- [ ] Verify the README renders (visually scan the markdown).

### Step 5.2 — full suite green

- [ ] Run `python -m pytest -q` from the repo root. Confirm ALL tests pass (existing + new `tests/web/*`, `tests/config/test_web_config.py`).
- [ ] Run `cd src/mmud/web/frontend && npm run test` — all frontend tests pass.

---

## Self-Review

- [ ] **Server is just another `GameEventBus` subscriber.** `WebPanelServer._subscribe_all` calls `bus.subscribe(event_type, self._on_event)` for every event in `_EVENT_TYPES`. It never modifies `events.py` or the bot's emit path — exactly the architecture the original stub in `src/mmud/web/__init__.py` anticipated ("No changes to events.py or bot.py required" — the only bot change is the optional, guarded `maybe_build_web_server`).
- [ ] **Inert without `[web]` config.** `MudConfig.web.enabled` defaults `False`; `maybe_build_web_server` returns `None` and never imports FastAPI when disabled. The TUI launch hook is a no-op. `test_no_web_section_means_no_server` proves it.
- [ ] **Existing tests stay green.** No existing module's behavior changed; new code is additive. The final `python -m pytest -q` run confirms it.
- [ ] **Depends on Doc 1 stats + Doc 2 ConfigService, gracefully.** Session/PlayerStats fields read `state.session.stats[...]` keys that Doc 1's `SessionStatUpdated` emissions will populate; absent keys render `0`/`-`/`0%`. `/api/config` returns 503 and Settings shows a banner until Doc 2's `ConfigService` (`mmud.config.service.ConfigService` with `.as_dict()` / `.apply(patch)`) exists. Neither dependency blocks the panel from shipping.
- [ ] **Type-consistent with the live bot.** Server calls only `bot._conn.send(cmd)` (async), reads `bot._state` (`GameState`) and `bot._session` (`SessionManager`), and uses `bot._config.web` for host/port — all verified against `src/mmud/bot.py`.
- [ ] **Quick-tool command map matches the MegaMud button set** (compass N/NE/E/SE/S/SW/W/NW + U/D, Get-All/Drop-All/Equip-All/Deposit/Search/AFK), each mapped to a MajorMud verb; unknown actions are rejected with HTTP 400.
