# In-App Configuration Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user edit and persist bot configuration at runtime from BOTH the Textual TUI and (via a shared service consumed later by the web panel) — no more hand-editing TOML. A single `ConfigService` is the only path that mutates the live `MudConfig`; every mutation is validated, type-coerced, optionally written back to disk preserving comments, and announced on the `GameEventBus` so all frontends live-update.

**Architecture:**
- `config/writer.py` — TOML round-trip writer (tomlkit): load the existing file preserving comments + unknown keys, apply a typed patch derived from the dataclasses, atomic write-back (temp file + `os.replace`).
- `config/runtime.py` — `ConfigService` holds the live `MudConfig`, exposes `.patch(section, field, value, persist=False)`, validates + coerces, optionally persists via the writer, and posts `ConfigChanged` on the bus.
- `events.py` — new `ConfigChanged` dataclass event.
- `automation/remote.py` — the ad-hoc `@auto-*` `getattr`/`setattr` toggles are refactored to route through `ConfigService`; new `@set` / `@save` verbs.
- `tui/settings_screen.py` — a Textual `ModalScreen` presenting config sections as tabs (mirroring MegaMud's Options property-sheet pages); edits route through `ConfigService`; a Save action persists.

**Tech Stack:** Python, tomlkit, Textual, pytest

> **DEPENDS ON Doc 1 (2026-06-11-hardening-and-gap-closure.md) Task 4** — the table-driven loader introspection helper. Doc 1 Task 4 refactors `config/loader.py` to build `MudConfig` by introspecting the dataclasses (instead of the hand-written 200-line `load_config`). It exposes a module `config/introspect.py` with:
>
> ```python
> # config/introspect.py  (delivered by Doc 1 Task 4 — DO NOT re-create it here)
> from __future__ import annotations
> import dataclasses
> from typing import Any
> from mmud.config.schema import MudConfig
>
> # Sections that are a single nested dataclass (everything on MudConfig except `players`).
> def section_dataclasses() -> dict[str, type]:
>     """name -> dataclass type, for each field on MudConfig whose default is a dataclass.
>     e.g. {'server': ServerConfig, 'combat': CombatConfig, ...} (excludes 'players')."""
>
> def section_names() -> list[str]:
>     """Ordered section names (dataclass sections + 'players')."""
>
> def field_type(section: str, field: str) -> type:
>     """The declared type of a scalar field, e.g. field_type('combat','port') -> int.
>     Raises KeyError if section or field is unknown."""
>
> def is_scalar_field(section: str, field: str) -> bool:
>     """True for str/int/float/bool fields; False for list[...] fields and nested dataclasses."""
>
> def scalar_fields(section: str) -> list[str]:
>     """Ordered scalar field names for a section (skips list[...] fields)."""
> ```
>
> **If Doc 1 Task 4 is not yet merged when you start:** create `config/introspect.py` with exactly the functions above first (it is pure dataclass reflection over `MudConfig`, no other dependencies), then proceed. The two docs converge on the same module.

---

## Task 0 — Add the tomlkit dependency

- [ ] **Step 0.1 — add tomlkit to pyproject.**
  `tomlkit` is NOT currently a dependency (current `dependencies = ["textual>=0.62.0"]`). Edit `/Users/jslagle/proj/mmud/pyproject.toml`:

  ```toml
  dependencies = ["textual>=0.62.0", "tomlkit>=0.12.0"]
  ```

- [ ] **Step 0.2 — install it.**
  Run: `python -m pip install "tomlkit>=0.12.0"`
  Verify: `python -c "import tomlkit; print(tomlkit.__version__)"` prints a version. Commit:
  `git add pyproject.toml && git commit -m "build: add tomlkit dependency for config round-trip writer"`

---

## Task 1 — `config/writer.py`: TOML round-trip writer

The writer takes the live `MudConfig` and an existing file path, loads the file with tomlkit (preserving comments + unknown keys), overwrites only the keys that correspond to known scalar fields, and atomically writes the result back. List fields and `players` are written wholesale (replace the array).

### Step 1.1 — Failing test: round-trip equality

- [ ] Create `/Users/jslagle/proj/mmud/tests/test_config_writer.py`:

```python
import pathlib
import tomllib
import pytest

from mmud.config.schema import MudConfig
from mmud.config.writer import write_config


def _write(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    p = tmp_path / "config.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_roundtrip_scalar_change(tmp_path):
    p = _write(tmp_path, "[server]\nhost = \"old\"\nport = 4000\n")
    cfg = MudConfig()
    cfg.server.host = "new"
    cfg.server.port = 9999
    write_config(cfg, p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["server"]["host"] == "new"
    assert data["server"]["port"] == 9999


def test_creates_file_when_missing(tmp_path):
    p = tmp_path / "config.toml"
    cfg = MudConfig()
    cfg.server.host = "fresh"
    write_config(cfg, p)
    assert p.exists()
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["server"]["host"] == "fresh"
```

- [ ] Run: `python -m pytest tests/test_config_writer.py -q` — fails (no `mmud.config.writer`).

### Step 1.2 — Minimal implementation

- [ ] Create `/Users/jslagle/proj/mmud/src/mmud/config/writer.py`:

```python
from __future__ import annotations

import dataclasses
import os
import pathlib

import tomlkit

from mmud.config import introspect
from mmud.config.schema import MudConfig


def _apply_scalars(table, section_obj) -> None:
    """Overwrite scalar keys in a tomlkit table from a dataclass section.

    Preserves any existing comments/whitespace on the keys tomlkit already
    holds; adds keys that are absent. List fields are handled separately.
    """
    section_name = _section_name_for(section_obj)
    for fname in introspect.scalar_fields(section_name):
        table[fname] = getattr(section_obj, fname)
    # list[...] scalar fields (e.g. combat.monster_priority): replace wholesale.
    for fname, ftype in _list_fields(section_obj):
        table[fname] = list(getattr(section_obj, fname))


def _section_name_for(section_obj) -> str:
    for name, dc_type in introspect.section_dataclasses().items():
        if type(section_obj) is dc_type:
            return name
    raise KeyError(f"unknown section dataclass: {type(section_obj)!r}")


def _list_fields(section_obj):
    """Yield (name, elem_type) for list[...] fields whose elements are scalars."""
    for f in dataclasses.fields(section_obj):
        origin = getattr(f.type, "__origin__", None)
        if origin is list:
            (elem,) = getattr(f.type, "__args__", (str,))
            if elem in (str, int, float, bool):
                yield f.name, elem


def _dataclass_list_to_tables(items: list) -> list:
    """Convert a list of dataclass instances to a tomlkit array-of-tables."""
    aot = tomlkit.aot()
    for item in items:
        tbl = tomlkit.table()
        for f in dataclasses.fields(item):
            tbl[f.name] = getattr(item, f.name)
        aot.append(tbl)
    return aot


def _build_document(cfg: MudConfig, existing: tomlkit.TOMLDocument) -> tomlkit.TOMLDocument:
    doc = existing
    for name, _dc_type in introspect.section_dataclasses().items():
        section_obj = getattr(cfg, name)
        if name not in doc:
            doc[name] = tomlkit.table()
        _apply_scalars(doc[name], section_obj)
        # Nested dataclass-list fields inside a section (e.g. spells.bless,
        # party.bless, schedule.events) are array-of-tables.
        for f in dataclasses.fields(section_obj):
            origin = getattr(f.type, "__origin__", None)
            if origin is list:
                (elem,) = getattr(f.type, "__args__", (str,))
                if dataclasses.is_dataclass(elem):
                    doc[name][f.name] = _dataclass_list_to_tables(
                        getattr(section_obj, f.name)
                    )
    # Top-level players array-of-tables.
    doc["players"] = _dataclass_list_to_tables(cfg.players)
    return doc


def write_config(cfg: MudConfig, path: pathlib.Path) -> None:
    """Atomically write `cfg` into the TOML file at `path`.

    Comments and unknown keys already present in the file are preserved.
    Writes to a temp file then os.replace() so a crash never leaves a
    partial config on disk.
    """
    if path.exists():
        existing = tomlkit.parse(path.read_text(encoding="utf-8"))
    else:
        existing = tomlkit.document()
    doc = _build_document(cfg, existing)
    text = tomlkit.dumps(doc)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
```

- [ ] Run: `python -m pytest tests/test_config_writer.py -q` — passes.

### Step 1.3 — Comment preservation test

- [ ] Append to `/Users/jslagle/proj/mmud/tests/test_config_writer.py`:

```python
def test_preserves_comments_and_unknown_keys(tmp_path):
    text = (
        "# top of file\n"
        "[server]\n"
        "host = \"old\"  # inline note\n"
        "port = 4000\n"
        "future_key = \"keep me\"\n"  # unknown to the schema
    )
    p = _write(tmp_path, text)
    cfg = MudConfig()
    cfg.server.host = "new"
    write_config(cfg, p)
    out = p.read_text(encoding="utf-8")
    assert "# top of file" in out
    assert "# inline note" in out
    assert "future_key" in out          # unknown key survives
    assert "keep me" in out
    assert "host = \"new\"" in out
```

- [ ] Run: `python -m pytest tests/test_config_writer.py -q` — passes (tomlkit preserves comments on keys it does not touch and on the file body).

### Step 1.4 — Atomicity test

- [ ] Append to `/Users/jslagle/proj/mmud/tests/test_config_writer.py`:

```python
def test_atomic_no_partial_file_on_dump_error(tmp_path, monkeypatch):
    text = "[server]\nhost = \"good\"\nport = 4000\n"
    p = _write(tmp_path, text)
    cfg = MudConfig()
    cfg.server.host = "halfway"

    import mmud.config.writer as writer_mod
    def boom(_doc):
        raise RuntimeError("serialization failed")
    monkeypatch.setattr(writer_mod.tomlkit, "dumps", boom)

    with pytest.raises(RuntimeError):
        write_config(cfg, p)

    # Original file untouched; no .tmp left behind.
    assert p.read_text(encoding="utf-8") == text
    assert not (tmp_path / "config.toml.tmp").exists()
```

- [ ] Run: `python -m pytest tests/test_config_writer.py -q`.
  If the `.tmp` cleanup assertion fails, wrap the write in try/finally. Update `write_config` so the temp file is always cleaned up on error:

```python
def write_config(cfg: MudConfig, path: pathlib.Path) -> None:
    if path.exists():
        existing = tomlkit.parse(path.read_text(encoding="utf-8"))
    else:
        existing = tomlkit.document()
    doc = _build_document(cfg, existing)
    text = tomlkit.dumps(doc)  # may raise BEFORE any temp file exists
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
```

  Note: `tomlkit.dumps` runs before the temp file is created, so a dump error leaves the original file and produces no `.tmp` — the test passes with the original implementation, but the try/finally guards the rarer `write_text`/`os.replace` failure path. Keep the guarded version.

- [ ] Run the full file: `python -m pytest tests/test_config_writer.py -q` — all pass. Commit:
  `git add src/mmud/config/writer.py tests/test_config_writer.py && git commit -m "feat: config TOML round-trip writer (tomlkit, atomic, comment-preserving)"`

---

## Task 2 — `config/runtime.py`: `ConfigService` + `ConfigChanged` event + remote refactor

### Step 2.1 — Add the `ConfigChanged` event

- [ ] In `/Users/jslagle/proj/mmud/src/mmud/events.py`, add this dataclass immediately after the `TravelEnded` dataclass (before the `class GameEventBus:` line):

```python
@dataclass
class ConfigChanged:
    section: str   # config section name, e.g. "combat"
    field: str     # field name within the section, e.g. "flee_threshold"
    value: object  # the new value, already type-coerced
```

- [ ] No test yet; it is exercised in Step 2.3.

### Step 2.2 — Failing test: ConfigService patch + event + coercion

- [ ] Create `/Users/jslagle/proj/mmud/tests/test_config_runtime.py`:

```python
import pathlib
import tomllib
import pytest

from mmud.config.schema import MudConfig
from mmud.config.runtime import ConfigService
from mmud.events import GameEventBus, ConfigChanged


def _service(tmp_path: pathlib.Path | None = None):
    bus = GameEventBus()
    seen: list[ConfigChanged] = []
    bus.subscribe(ConfigChanged, seen.append)
    path = (tmp_path / "config.toml") if tmp_path else None
    svc = ConfigService(MudConfig(), bus=bus, path=path)
    return svc, seen


def test_patch_updates_live_config_and_emits_event():
    svc, seen = _service()
    svc.patch("combat", "attack_cmd", "bash")
    assert svc.config.combat.attack_cmd == "bash"
    assert seen == [ConfigChanged(section="combat", field="attack_cmd", value="bash")]


def test_patch_coerces_string_to_field_type():
    svc, seen = _service()
    svc.patch("server", "port", "1234")          # string in
    assert svc.config.server.port == 1234         # int out
    assert isinstance(svc.config.server.port, int)


def test_patch_coerces_bool_strings():
    svc, _ = _service()
    svc.patch("stealth", "auto_sneak", "on")
    assert svc.config.stealth.auto_sneak is True
    svc.patch("stealth", "auto_sneak", "off")
    assert svc.config.stealth.auto_sneak is False


def test_patch_coerces_float():
    svc, _ = _service()
    svc.patch("combat", "flee_threshold", "0.25")
    assert svc.config.combat.flee_threshold == pytest.approx(0.25)


def test_unknown_section_raises():
    svc, _ = _service()
    with pytest.raises(KeyError):
        svc.patch("nope", "field", "x")


def test_unknown_field_raises():
    svc, _ = _service()
    with pytest.raises(KeyError):
        svc.patch("combat", "no_such_field", "x")


def test_persist_writes_file(tmp_path):
    svc, _ = _service(tmp_path)
    svc.patch("combat", "attack_cmd", "bash", persist=True)
    data = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert data["combat"]["attack_cmd"] == "bash"


def test_persist_without_path_raises(tmp_path):
    svc, _ = _service(None)
    with pytest.raises(RuntimeError):
        svc.patch("combat", "attack_cmd", "bash", persist=True)


def test_save_writes_current_config(tmp_path):
    svc, _ = _service(tmp_path)
    svc.patch("combat", "attack_cmd", "smash")   # no persist
    assert not (tmp_path / "config.toml").exists()
    svc.save()
    data = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert data["combat"]["attack_cmd"] == "smash"
```

- [ ] Run: `python -m pytest tests/test_config_runtime.py -q` — fails (no `mmud.config.runtime`).

### Step 2.3 — Implement `ConfigService`

- [ ] Create `/Users/jslagle/proj/mmud/src/mmud/config/runtime.py`:

```python
from __future__ import annotations

import pathlib
from typing import Any

from mmud.config import introspect
from mmud.config.schema import MudConfig
from mmud.config.writer import write_config
from mmud.events import ConfigChanged, GameEventBus

_TRUE = {"on", "true", "1", "yes", "y"}
_FALSE = {"off", "false", "0", "no", "n"}


def _coerce(value: Any, target: type) -> Any:
    """Coerce `value` to `target` (one of bool/int/float/str)."""
    if target is bool:
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
        raise ValueError(f"cannot interpret {value!r} as bool")
    if target is int:
        return int(value)
    if target is float:
        return float(value)
    return str(value)


class ConfigService:
    """The single mutation path for the live MudConfig.

    Shared by the TUI settings screen, the remote @set/@save verbs, and
    (later) the web control panel. Every mutation validates the field
    exists, coerces to the declared type, optionally persists to disk, and
    posts a ConfigChanged event so all frontends live-update.
    """

    def __init__(
        self,
        config: MudConfig,
        bus: GameEventBus,
        path: pathlib.Path | None = None,
    ) -> None:
        self.config = config
        self._bus = bus
        self._path = path

    def patch(
        self, section: str, field: str, value: Any, persist: bool = False
    ) -> Any:
        """Apply one field change. Returns the coerced value.

        Raises KeyError for an unknown section/field, ValueError for an
        uncoercible value, RuntimeError if persist=True with no path.
        """
        if not introspect.is_scalar_field(section, field):
            # is_scalar_field raises KeyError for unknown section/field; a
            # known-but-non-scalar (list/dataclass) field is not patchable here.
            raise KeyError(f"{section}.{field} is not a scalar field")
        target = introspect.field_type(section, field)
        coerced = _coerce(value, target)
        setattr(getattr(self.config, section), field, coerced)
        if persist:
            self.save()
        self._bus.post(ConfigChanged(section=section, field=field, value=coerced))
        return coerced

    def save(self) -> None:
        """Persist the current config to the backing file."""
        if self._path is None:
            raise RuntimeError("ConfigService has no backing path; cannot save")
        write_config(self.config, self._path)
```

- [ ] Run: `python -m pytest tests/test_config_runtime.py -q` — all pass.

> **Note on `is_scalar_field` semantics:** Doc 1's `is_scalar_field(section, field)` must raise `KeyError` for an unknown section or unknown field (matching `field_type`). If Doc 1's version returns `False` instead of raising for unknown fields, the `test_unknown_field_raises` test will fail. In that case, adjust `patch` to call `introspect.field_type(section, field)` FIRST (which raises `KeyError`), then check scalar-ness:
>
> ```python
> target = introspect.field_type(section, field)   # raises KeyError if unknown
> if not introspect.is_scalar_field(section, field):
>     raise KeyError(f"{section}.{field} is not a scalar field")
> coerced = _coerce(value, target)
> ```

- [ ] Commit: `git add src/mmud/config/runtime.py src/mmud/events.py tests/test_config_runtime.py && git commit -m "feat: ConfigService — single validated mutation path + ConfigChanged event"`

### Step 2.4 — Wire a ConfigService onto MudBot

- [ ] In `/Users/jslagle/proj/mmud/src/mmud/bot.py`, locate the `__init__` where `self._config` and `self._bus` are assigned (around lines 68 and 78). Immediately after the line `self._bus = event_bus   # assigned early so DB import can emit events`, add:

```python
        from mmud.config.runtime import ConfigService
        self._config_service = ConfigService(
            self._config,
            bus=self._bus or GameEventBus(),
            path=config_path,
        )
```

- [ ] Add a `config_path` parameter to `MudBot.__init__`. Find the signature (starts at line 57) and add `config_path: "pathlib.Path | None" = None,` as a keyword argument alongside `event_bus`. Confirm `import pathlib` and `from mmud.events import GameEventBus` are already present at the top of `bot.py` (they are used elsewhere in the file).

- [ ] Run: `python -m pytest tests/test_remote.py -q` — still green (the new param defaults to None; `_bot()` in the test does not pass it).

### Step 2.5 — Refactor `remote.py` `@auto-*` toggles to route through ConfigService

**Before** (current `automation/remote.py`, lines 91-95 and the `_toggle` method, lines 132-141):

```python
        # Toggle existing config flags, after the original's @auto-* verbs
        self.register("auto-sneak", self._toggle("stealth", "auto_sneak"))
        self.register("auto-hide", self._toggle("stealth", "auto_hide"))
        self.register("auto-get", self._toggle("items", "auto_get"))
        self.register("auto-cash", self._toggle("items", "auto_cash"))
```

```python
    def _toggle(self, section: str, attr: str) -> VerbHandler:
        def toggle(sender: str, arg: str) -> str:
            cfg = getattr(self._bot._config, section)
            if arg:
                value = arg.lower() in ("on", "true", "1", "yes")
            else:
                value = not getattr(cfg, attr)
            setattr(cfg, attr, value)
            return f"{attr} {'on' if value else 'off'}"
        return toggle
```

**After** — the `_toggle` factory now computes the desired boolean and routes the change through `ConfigService.patch` (validation + ConfigChanged event come for free). The registration lines are unchanged.

- [ ] In `/Users/jslagle/proj/mmud/src/mmud/automation/remote.py`, replace the entire `_toggle` method (lines 132-141) with:

```python
    def _toggle(self, section: str, attr: str) -> VerbHandler:
        def toggle(sender: str, arg: str) -> str:
            svc = self._bot._config_service
            if arg:
                value = arg.strip().lower() in ("on", "true", "1", "yes")
            else:
                value = not getattr(getattr(svc.config, section), attr)
            svc.patch(section, attr, value)
            return f"{attr} {'on' if value else 'off'}"
        return toggle
```

- [ ] Run: `python -m pytest tests/test_remote.py::test_auto_sneak_toggle -q` — still passes (config still mutates; reply text unchanged). Then run the whole file: `python -m pytest tests/test_remote.py -q` — green.

- [ ] Commit: `git add src/mmud/bot.py src/mmud/automation/remote.py && git commit -m "refactor: @auto-* toggles route through ConfigService; bot owns the service"`

---

## Task 3 — TUI settings screen

A `ModalScreen` showing config sections as tabs that mirror MegaMud's Options property-sheet pages. Each tab lists the section's scalar fields as labelled `Input` widgets. Editing a field routes through `ConfigService.patch`; a Save button calls `ConfigService.save()`.

Tab grouping (derived from `schema.py` sections, matching the original property-sheet page names):
- **General** → `server`, `login`, `session`
- **Display** → `ui`
- **Combat** → `combat`
- **Spells** → `spells`
- **Health** → `health`, `safety`
- **Events** → `pvp`, `commerce`, `learning`
- **Stealth** → `stealth`, `navigation`
- **Items** → `items`
- **Party** → `party`, `afk`

(`schedule` and `players` are list-of-dataclass sections — out of scope for this scalar-field editor; the web panel in Doc 3 handles array editing.)

### Step 3.1 — Failing widget test

- [ ] Create `/Users/jslagle/proj/mmud/tests/test_settings_screen.py`:

```python
import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input

from mmud.config.schema import MudConfig
from mmud.config.runtime import ConfigService
from mmud.events import GameEventBus, ConfigChanged
from mmud.tui.settings_screen import SettingsScreen


class _Host(App):
    def __init__(self, svc: ConfigService) -> None:
        super().__init__()
        self._svc = svc

    def compose(self) -> ComposeResult:
        yield from ()

    async def on_mount(self) -> None:
        await self.push_screen(SettingsScreen(self._svc))


def _service():
    bus = GameEventBus()
    seen: list[ConfigChanged] = []
    bus.subscribe(ConfigChanged, seen.append)
    return ConfigService(MudConfig(), bus=bus, path=None), seen


@pytest.mark.asyncio
async def test_editing_field_patches_config():
    svc, seen = _service()
    app = _Host(svc)
    async with app.run_test() as pilot:
        inp = app.screen.query_one("#field-combat-attack_cmd", Input)
        inp.value = "bash"
        # Submitting an Input fires Input.Submitted -> handler calls patch.
        await pilot.pause()
        await app.screen._commit_field(inp)
        await pilot.pause()
    assert svc.config.combat.attack_cmd == "bash"
    assert any(e.section == "combat" and e.field == "attack_cmd" for e in seen)


@pytest.mark.asyncio
async def test_invalid_value_does_not_crash():
    svc, _ = _service()
    app = _Host(svc)
    async with app.run_test() as pilot:
        inp = app.screen.query_one("#field-server-port", Input)
        inp.value = "not-a-number"
        await app.screen._commit_field(inp)   # ValueError swallowed, status set
        await pilot.pause()
        assert "not-a-number" not in str(svc.config.server.port)
        assert app.screen.query_one("#settings-status").renderable  # error shown
```

- [ ] Run: `python -m pytest tests/test_settings_screen.py -q` — fails (no `settings_screen`).

### Step 3.2 — Implement the screen

- [ ] Create `/Users/jslagle/proj/mmud/src/mmud/tui/settings_screen.py`:

```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, TabbedContent, TabPane

from mmud.config import introspect
from mmud.config.runtime import ConfigService

# Tab title -> ordered list of section names, mirroring MegaMud's Options pages.
TABS: list[tuple[str, list[str]]] = [
    ("General", ["server", "login", "session"]),
    ("Display", ["ui"]),
    ("Combat", ["combat"]),
    ("Spells", ["spells"]),
    ("Health", ["health", "safety"]),
    ("Events", ["pvp", "commerce", "learning"]),
    ("Stealth", ["stealth", "navigation"]),
    ("Items", ["items"]),
    ("Party", ["party", "afk"]),
]


def _field_id(section: str, field: str) -> str:
    return f"field-{section}-{field}"


class SettingsScreen(ModalScreen):
    """Runtime config editor. Edits route through ConfigService."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close", priority=True),
        Binding("ctrl+s", "save", "Save", priority=True),
    ]

    def __init__(self, service: ConfigService) -> None:
        super().__init__()
        self._svc = service

    def compose(self) -> ComposeResult:
        with TabbedContent(id="settings-tabs"):
            for title, sections in TABS:
                with TabPane(title, id=f"tab-{title.lower()}"):
                    with VerticalScroll():
                        for section in sections:
                            yield Label(f"[{section}]", classes="section-header")
                            for field in introspect.scalar_fields(section):
                                value = getattr(getattr(self._svc.config, section), field)
                                yield Label(f"{field}")
                                yield Input(
                                    value=str(value),
                                    id=_field_id(section, field),
                                )
        yield Static("", id="settings-status")
        yield Button("Save", id="settings-save", variant="primary")

    def _parse_id(self, widget_id: str) -> tuple[str, str]:
        # "field-combat-attack_cmd" -> ("combat", "attack_cmd")
        _, section, field = widget_id.split("-", 2)
        return section, field

    def _commit_field(self, inp: Input) -> None:
        if not inp.id or not inp.id.startswith("field-"):
            return
        section, field = self._parse_id(inp.id)
        status = self.query_one("#settings-status", Static)
        try:
            self._svc.patch(section, field, inp.value)
            status.update(f"{section}.{field} = {inp.value}")
        except (ValueError, KeyError) as exc:
            status.update(f"[red]invalid {section}.{field}: {exc}[/red]")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._commit_field(event.input)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-save":
            self.action_save()

    def action_save(self) -> None:
        # Commit every field, then persist.
        for inp in self.query(Input):
            self._commit_field(inp)
        status = self.query_one("#settings-status", Static)
        try:
            self._svc.save()
            status.update("[green]saved[/green]")
        except RuntimeError as exc:
            status.update(f"[red]{exc}[/red]")

    def action_dismiss(self) -> None:
        self.dismiss()
```

- [ ] Run: `python -m pytest tests/test_settings_screen.py -q` — passes. If `query(Input)` in the test cannot find `#field-server-port`, confirm `server` is in the General tab (it is) and that `introspect.scalar_fields("server")` returns `["host", "port"]`.

### Step 3.3 — Add keybinding + action to the app

- [ ] In `/Users/jslagle/proj/mmud/src/mmud/tui/app.py`, add a binding to the `BINDINGS` list (after the `ctrl+l` loop binding, line 34):

```python
        Binding("ctrl+o", "open_settings", "Settings", show=False, priority=True),
```

- [ ] Add an import near the other tui imports (after line 19):

```python
from mmud.tui.settings_screen import SettingsScreen
```

- [ ] The app needs a `ConfigService`. In `MegaMudApp.__init__` (after `self._bus = GameEventBus()`, line 43), add:

```python
        from mmud.config.runtime import ConfigService
        self._config_service = ConfigService(self._config, bus=self._bus, path=None)
```

  (Path stays `None` here until Doc 1 threads the loaded config path into the app constructor; the TUI can still edit in-memory. When the app constructs its `MudBot`, pass the same service so they share state — see Step 3.4.)

- [ ] Add the action method to `MegaMudApp` (place it next to the other `action_*` methods, e.g. after `action_toggle_loop`):

```python
    def action_open_settings(self) -> None:
        self.push_screen(SettingsScreen(self._config_service))
```

- [ ] **Guard against `on_key` stealing `ctrl+o`:** the existing `on_key` (lines 104-105) already returns early for keys starting with `"ctrl+"`, so `ctrl+o` reaches the binding. No change needed; verify by reading lines 104-106.

### Step 3.4 — Share the service with the bot

- [ ] In `MegaMudApp.action_toggle_connect` (around line 258), pass the app's config path through to the bot so both sides write the same file once a path is known. For now, since the app holds `path=None`, the simplest correct wiring is to have the bot REUSE the app's `ConfigService` rather than build its own. Add a `config_service` parameter to `MudBot.__init__` (keyword, default `None`); when provided, use it instead of constructing one:

  In `/Users/jslagle/proj/mmud/src/mmud/bot.py`, change the ConfigService construction added in Step 2.4 to:

```python
        from mmud.config.runtime import ConfigService
        self._config_service = config_service or ConfigService(
            self._config,
            bus=self._bus or GameEventBus(),
            path=config_path,
        )
```

  and add `config_service=None,` to the signature.

- [ ] In `app.py` `action_toggle_connect`, add `config_service=self._config_service,` to the `MudBot(...)` call (alongside `config=self._config`). This guarantees TUI edits and remote `@set`/`@save` mutate one shared live config.

- [ ] Run the TUI-adjacent tests: `python -m pytest tests/test_settings_screen.py tests/test_remote.py -q` — green. Commit:
  `git add src/mmud/tui/settings_screen.py src/mmud/tui/app.py src/mmud/bot.py tests/test_settings_screen.py && git commit -m "feat: TUI settings screen (Ctrl+O) editing via ConfigService"`

---

## Task 4 — `@set` / `@save` remote verbs

### Step 4.1 — Failing test

- [ ] Append to `/Users/jslagle/proj/mmud/tests/test_remote.py`:

```python
def test_set_verb_mutates_config():
    bot = _bot(WILDCARD)
    h = RemoteCommandHandler(bot)
    reply = h.handle("Friend", "@set combat.attack_cmd bash")
    assert "combat.attack_cmd" in reply and "bash" in reply
    assert bot._config.combat.attack_cmd == "bash"


def test_set_verb_coerces_type():
    bot = _bot(WILDCARD)
    h = RemoteCommandHandler(bot)
    h.handle("Friend", "@set server.port 1234")
    assert bot._config.server.port == 1234


def test_set_verb_usage_on_bad_syntax():
    bot = _bot(WILDCARD)
    h = RemoteCommandHandler(bot)
    assert "usage" in h.handle("Friend", "@set combat.attack_cmd").lower()
    assert "usage" in h.handle("Friend", "@set noseparator value").lower()


def test_set_verb_unknown_field_reports_error():
    bot = _bot(WILDCARD)
    h = RemoteCommandHandler(bot)
    reply = h.handle("Friend", "@set combat.nope x")
    assert "unknown" in reply.lower() or "error" in reply.lower()


def test_save_verb_writes_file(tmp_path):
    import tomllib
    from mmud.config.runtime import ConfigService
    from mmud.events import GameEventBus
    bot = _bot(WILDCARD)
    path = tmp_path / "config.toml"
    bot._config_service = ConfigService(bot._config, bus=GameEventBus(), path=path)
    h = RemoteCommandHandler(bot)
    h.handle("Friend", "@set combat.attack_cmd smash")
    reply = h.handle("Friend", "@save")
    assert "saved" in reply.lower()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["combat"]["attack_cmd"] == "smash"


def test_save_verb_without_path():
    bot = _bot(WILDCARD)   # default service has path=None
    h = RemoteCommandHandler(bot)
    reply = h.handle("Friend", "@save")
    assert "no" in reply.lower() or "cannot" in reply.lower()
```

- [ ] Run: `python -m pytest tests/test_remote.py -k "set_verb or save_verb" -q` — fails (verbs not registered).

### Step 4.2 — Register `@set` and `@save`

- [ ] In `/Users/jslagle/proj/mmud/src/mmud/automation/remote.py`, in `_register_builtins`, add these two registrations right after the `auto-cash` line (line 95):

```python
        self.register("set", self._set_config)
        self.register("save", self._save_config)
```

- [ ] Add the two handler methods (place them next to `_toggle`, e.g. just before it):

```python
    def _set_config(self, sender: str, arg: str) -> str:
        # "@set combat.attack_cmd bash" -> patch combat.attack_cmd = "bash"
        parts = arg.split(None, 1)
        if len(parts) != 2 or "." not in parts[0]:
            return "usage: @set SECTION.FIELD VALUE"
        dotted, value = parts
        section, field = dotted.split(".", 1)
        try:
            self._bot._config_service.patch(section, field, value)
        except KeyError:
            return f"unknown field {section}.{field}"
        except ValueError as exc:
            return f"error: {exc}"
        return f"{section}.{field} = {value}"

    def _save_config(self, sender: str, arg: str) -> str:
        try:
            self._bot._config_service.save()
        except RuntimeError as exc:
            return str(exc)
        return "config saved"
```

- [ ] Run: `python -m pytest tests/test_remote.py -q` — all green.

- [ ] **Permissions note:** these verbs flow through the existing permission gate in `handle()`. A `PlayerRule` must list `"set"`/`"save"` (or `"*"`) in `remote_cmds` to use them. Document this in the README config section if Doc 1 adds a verb table; no code change needed.

- [ ] Commit: `git add src/mmud/automation/remote.py tests/test_remote.py && git commit -m "feat: @set/@save remote verbs route config edits through ConfigService"`

---

## Self-Review

Before declaring done, run the FULL suite and confirm green:

- [ ] `python -m pytest -q` — all existing tests still pass (target: the established 415 + the new writer/runtime/settings/remote tests). The `@auto-*` refactor preserves the exact reply strings (`"auto_sneak on"`), so `test_auto_sneak_toggle` is unchanged.

Verify the invariants this plan guarantees:

- [ ] **Single mutation path.** Grep for stray config writes: `grep -rn "setattr.*_config\|\._config\.\w*\.\w* =" src/mmud` should show only `ConfigService.patch` (in `runtime.py`) writing scalar config fields. The TUI (`SettingsScreen`), the remote verbs (`@set`, `@save`, `@auto-*`), and — in Doc 3 — the web panel all call `ConfigService.patch` / `ConfigService.save`. Nothing else mutates a config scalar.
- [ ] **Read/write symmetry.** Both `loader.py` (read, via Doc 1) and `writer.py` (write) drive off the same `config/introspect.py` reflection — adding a field to a `schema.py` dataclass automatically makes it loadable, writable, patchable, and shown in the TUI with no other edits.
- [ ] **Live update.** Every successful `patch` posts `ConfigChanged(section, field, value)`. Frontends that subscribe (TUI panes, web panel websocket in Doc 3) re-render from a single event. Confirm `ConfigChanged` is exported from `events.py` and imported by `runtime.py`.
- [ ] **No partial files.** `writer.py` writes a temp file then `os.replace`; a serialization error leaves the original untouched and removes the temp file. Comments and unknown keys survive every write.
