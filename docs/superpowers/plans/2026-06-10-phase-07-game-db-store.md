# Phase 7: Game DB Store (convert/merge + live learning) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execute BEFORE Phase 6** — the pathfinding phase persists its live-learned exits through this store. (The roadmap marks Phase 7 order-flexible; this plan pulls it forward.)

**Goal:** Replace direct-from-binary DB loading with our own JSON store: the MDB2 binaries (MONSTERS/ITEMS/SPELLS.MD) are **converted and merged in at startup** (never written), with **collision detection** against locally-learned/overridden records and automatic **re-import** when the MD source changes. Live learning (unknown monsters, un-gettable/no-equip marks, learned exits) persists in the same store.

**Architecture:** `GameStore` owns one JSON file (atomic tmp+rename writes). An importer fingerprints each MD source (size+sha256) and three-way-merges per record: MD-origin records follow the source; learned/override records survive source changes and raise recorded **collisions** when the source disagrees. `MonsterDB`/`ItemDB` gain `from_store()` constructors; the bot builds the store when `[learning]` is enabled and falls back to today's direct loading when not. **Text sources (.MP corpus, ROOMS.MD, MESSAGES.MD) are explicitly OUT of scope — they are read directly at runtime, never imported.**

**Tech Stack:** Python 3.11+, stdlib only (`json`, `hashlib`, `os.replace`).

**Prerequisites:** Phases 1–5 + MDB2 parser rewrite complete; `pytest -q` green (296).

**Validated facts (no re-derivation needed):**
- `load_monsters/items/spells` (`src/mmud/data/binary.py`) return **788 / 667 / 936** records against `extractions/mm103s.exe.extracted/45DAD/Default/`, and **record ids are unique within each DB** (788/667/936 unique) — keying by id is safe.
- `MonsterSighting.record_id == -1` (`src/mmud/state/game_state.py`) marks an unknown monster — the learning trigger.
- In-memory mark sets today: `GetDecider._ungettable` (`src/mmud/automation/items.py`), `EquipDecider._failed` (`src/mmud/automation/equip.py`).

---

## File Map

```
src/mmud/
  data/store.py             NEW — GameStore + importer + ImportReport
  data/monster_db.py        MODIFY — from_store()
  data/item_db.py           MODIFY — from_store()
  config/schema.py          MODIFY — LearningConfig
  config/loader.py          MODIFY — parse [learning]
  events.py                 MODIFY — DbCollision, DbImported
  bot.py                    MODIFY — build store, learning hooks, seed marks
tests/
  test_store.py             NEW
  test_store_import.py      NEW
  test_config.py            MODIFY
  test_bot.py               MODIFY — learning e2e
characters/example.toml     MODIFY
README.md                   MODIFY — [learning] note
```

---

### Task 1: GameStore core — schema, load, atomic save

**Files:**
- Create: `src/mmud/data/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_store.py
import json
from mmud.data.store import GameStore, STORE_VERSION


def test_fresh_store_has_empty_schema(tmp_path):
    s = GameStore(tmp_path / "gamedb.json")
    assert s.data["version"] == STORE_VERSION
    assert s.data["sources"] == {}
    for section in ("monsters", "items", "spells", "players"):
        assert s.data[section] == {}
    assert s.data["exits"] == []
    assert s.data["marks"] == {"ungettable": [], "no_auto_equip": [], "non_enemy": []}
    assert s.data["collisions"] == []


def test_save_and_reload_roundtrip(tmp_path):
    p = tmp_path / "gamedb.json"
    s = GameStore(p)
    s.data["monsters"]["1"] = {"name": "giant rat", "origin": "md"}
    s.save()
    s2 = GameStore(p)
    assert s2.data["monsters"]["1"]["name"] == "giant rat"


def test_save_is_atomic_no_partial_file(tmp_path):
    p = tmp_path / "gamedb.json"
    s = GameStore(p)
    s.save()
    # the temp file must not linger
    assert [f.name for f in tmp_path.iterdir()] == ["gamedb.json"]
    assert json.loads(p.read_text())["version"] == STORE_VERSION


def test_corrupt_file_starts_fresh(tmp_path):
    p = tmp_path / "gamedb.json"
    p.write_text("{not json")
    s = GameStore(p)
    assert s.data["version"] == STORE_VERSION   # fresh, no crash


def test_marks_api(tmp_path):
    s = GameStore(tmp_path / "gamedb.json")
    s.add_mark("ungettable", "Fountain")
    s.add_mark("ungettable", "fountain")        # dedup, case-insensitive
    assert s.marks("ungettable") == ["fountain"]


def test_exits_api(tmp_path):
    s = GameStore(tmp_path / "gamedb.json")
    s.add_exit("AAAA0001", "n", "BBBB0002")
    s.add_exit("AAAA0001", "n", "BBBB0002")     # dedup
    assert s.exits() == [("AAAA0001", "n", "BBBB0002")]
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `src/mmud/data/store.py`**

```python
from __future__ import annotations
import json
import os
import pathlib

STORE_VERSION = 1

_EMPTY = {
    "version": STORE_VERSION,
    "sources": {},      # filename -> {"fingerprint": "sha256:..."}
    "monsters": {},     # str(record_id) -> {fields..., origin, md_hash}
    "items": {},
    "spells": {},
    "players": {},
    "exits": [],        # [from_hex, command, to_hex] triples (learned only)
    "marks": {"ungettable": [], "no_auto_equip": [], "non_enemy": []},
    "collisions": [],   # importer-recorded conflicts, kept for review
}


class GameStore:
    """Our own game database: JSON file, atomic writes, MD-merged + learned data.

    The MDB2 binaries are merged IN by the importer (Task 2); they are never
    written. Text sources (.MP corpus, ROOMS.MD, MESSAGES.MD) are not stored
    here — they are read directly at runtime.
    """

    def __init__(self, path: pathlib.Path) -> None:
        self.path = pathlib.Path(path)
        self.data: dict = json.loads(json.dumps(_EMPTY))   # deep copy
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and loaded.get("version") == STORE_VERSION:
                    self.data = loaded
            except (json.JSONDecodeError, OSError):
                pass   # corrupt/unreadable: start fresh (file replaced on save)

    def save(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True),
                       encoding="utf-8")
        os.replace(tmp, self.path)

    # ---- marks ------------------------------------------------------------

    def add_mark(self, category: str, name: str) -> None:
        bucket = self.data["marks"][category]
        key = name.strip().lower()
        if key and key not in bucket:
            bucket.append(key)
            self.save()

    def marks(self, category: str) -> list[str]:
        return list(self.data["marks"][category])

    # ---- learned exits (consumed by Phase 6) ------------------------------

    def add_exit(self, from_hex: str, command: str, to_hex: str) -> None:
        triple = [from_hex.upper(), command.lower(), to_hex.upper()]
        if triple not in self.data["exits"]:
            self.data["exits"].append(triple)
            self.save()

    def exits(self) -> list[tuple[str, str, str]]:
        return [tuple(e) for e in self.data["exits"]]
```

- [ ] **Step 4: Run tests** — `pytest tests/test_store.py -v` → 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/mmud/data/store.py tests/test_store.py
git commit -m "feat: GameStore — JSON game database with atomic writes, marks, learned exits"
```

---

### Task 2: Importer — fingerprint, three-way merge, collisions

**Files:**
- Modify: `src/mmud/data/store.py`
- Test: `tests/test_store_import.py`

Merge semantics per record (id-keyed):
- not in store → **add** (`origin="md"`)
- in store with `origin=="md"` → **replace** with current MD version
- in store with `origin in ("learned", "override")` and the MD record's hash
  differs from the stored `md_hash` → **collision**: local wins, the new MD
  version is appended to `collisions` for review
- source fingerprint unchanged → whole file **skipped** (fast start)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_store_import.py
from mmud.data.store import GameStore, import_md, record_hash


def test_initial_import_pins_real_counts(tmp_path, data_dir):
    s = GameStore(tmp_path / "gamedb.json")
    report = import_md(s, data_dir)
    assert report.added["monsters"] == 788
    assert report.added["items"] == 667
    assert report.added["spells"] == 936
    assert report.collisions == 0
    assert s.data["monsters"]["1"]["name"] == "giant rat"
    assert s.data["monsters"]["1"]["origin"] == "md"


def test_second_import_skips_unchanged(tmp_path, data_dir):
    s = GameStore(tmp_path / "gamedb.json")
    import_md(s, data_dir)
    report = import_md(s, data_dir)
    assert report.skipped_sources >= 3      # fingerprints unchanged
    assert sum(report.added.values()) == 0


def test_md_origin_record_follows_source(tmp_path, data_dir):
    s = GameStore(tmp_path / "gamedb.json")
    import_md(s, data_dir)
    s.data["monsters"]["1"]["name"] = "tampered"        # still origin=md
    s.data["sources"]["MONSTERS.MD"]["fingerprint"] = "stale"
    report = import_md(s, data_dir)
    assert s.data["monsters"]["1"]["name"] == "giant rat"   # replaced
    assert report.collisions == 0


def test_override_survives_and_collides(tmp_path, data_dir):
    s = GameStore(tmp_path / "gamedb.json")
    import_md(s, data_dir)
    rec = s.data["monsters"]["1"]
    rec["origin"] = "override"
    rec["exp_value"] = 99999                # local edit
    rec["md_hash"] = "sha256:old-version"   # pretend MD changed since our edit
    s.data["sources"]["MONSTERS.MD"]["fingerprint"] = "stale"
    report = import_md(s, data_dir)
    assert s.data["monsters"]["1"]["exp_value"] == 99999    # local wins
    assert report.collisions == 1
    assert s.data["collisions"][0]["db"] == "monsters"
    assert s.data["collisions"][0]["record_id"] == 1


def test_record_hash_is_stable():
    a = {"name": "rat", "exp_value": 10, "origin": "md", "md_hash": "x"}
    b = {"exp_value": 10, "name": "rat", "origin": "override", "md_hash": "y"}
    # origin/md_hash excluded from hashing; field order irrelevant
    assert record_hash(a) == record_hash(b)
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_store_import.py -v`
Expected: FAIL with `ImportError: cannot import name 'import_md'`

- [ ] **Step 3: Append to `src/mmud/data/store.py`**

```python
import dataclasses
import hashlib
from dataclasses import dataclass, field
from mmud.data.binary import load_monsters, load_items, load_spells, load_players

_LOADERS = {
    "MONSTERS.MD": ("monsters", load_monsters),
    "ITEMS.MD": ("items", load_items),
    "SPELLS.MD": ("spells", load_spells),
    "PLAYERS.MD": ("players", load_players),
}


def record_hash(rec: dict) -> str:
    """Stable hash of a record's game fields (origin/md_hash excluded)."""
    fields = {k: v for k, v in rec.items() if k not in ("origin", "md_hash")}
    blob = json.dumps(fields, sort_keys=True)
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


def _file_fingerprint(path: pathlib.Path) -> str:
    data = path.read_bytes()
    return f"sha256:{hashlib.sha256(data).hexdigest()}:{len(data)}"


@dataclass
class ImportReport:
    added: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)
    collisions: int = 0
    skipped_sources: int = 0


def import_md(store: GameStore, data_dir: pathlib.Path) -> ImportReport:
    """Convert/merge the MDB2 binaries into the store. Never writes the MDs.

    Text sources (.MP, ROOMS.MD, MESSAGES.MD) are deliberately not imported.
    """
    report = ImportReport()
    for filename, (section, loader) in _LOADERS.items():
        src = data_dir / filename
        if not src.exists():
            continue
        fp = _file_fingerprint(src)
        if store.data["sources"].get(filename, {}).get("fingerprint") == fp:
            report.skipped_sources += 1
            continue
        added = updated = 0
        bucket = store.data[section]
        for rec_obj in loader(src):
            rec = dataclasses.asdict(rec_obj)
            key = str(rec.get("record_id", rec.get("name")))
            md_hash = record_hash(rec)
            existing = bucket.get(key)
            if existing is None:
                rec["origin"] = "md"
                rec["md_hash"] = md_hash
                bucket[key] = rec
                added += 1
            elif existing.get("origin") == "md":
                rec["origin"] = "md"
                rec["md_hash"] = md_hash
                if record_hash(existing) != md_hash:
                    updated += 1
                bucket[key] = rec
            else:
                # learned/override: local wins; collide if the MD side moved
                if existing.get("md_hash") != md_hash:
                    store.data["collisions"].append({
                        "db": section,
                        "record_id": rec.get("record_id"),
                        "md_version": rec,
                        "local_origin": existing.get("origin"),
                    })
                    existing["md_hash"] = md_hash   # don't re-collide next run
                    report.collisions += 1
        store.data["sources"][filename] = {"fingerprint": fp}
        report.added[section] = added
        report.updated[section] = updated
    store.save()
    return report
```

- [ ] **Step 4: Run tests** — `pytest tests/test_store_import.py -v` → 5 passed
(initial import of all four MDs takes ~1s — acceptable; subsequent runs skip).

- [ ] **Step 5: Commit**

```bash
git add src/mmud/data/store.py tests/test_store_import.py
git commit -m "feat: MD importer — fingerprinted convert/merge with collision detection"
```

---

### Task 3: DB wrappers from the store + bot wiring + config

**Files:**
- Modify: `src/mmud/data/monster_db.py`, `src/mmud/data/item_db.py`,
  `src/mmud/config/schema.py`, `src/mmud/config/loader.py`, `src/mmud/bot.py`,
  `src/mmud/events.py`
- Test: `tests/test_store.py` (append), `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_learning_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[learning]
enabled = true
store_path = "mydb.json"
""")
    cfg = load_config(p)
    assert cfg.learning.enabled is True
    assert cfg.learning.store_path == "mydb.json"


def test_learning_disabled_by_default():
    cfg = load_config(None)
    assert cfg.learning.enabled is False
    assert cfg.learning.store_path == "gamedb.json"
```

Append to `tests/test_store.py`:

```python
def test_dbs_built_from_store(tmp_path, data_dir):
    from mmud.data.store import import_md
    from mmud.data.monster_db import MonsterDB
    from mmud.data.item_db import ItemDB
    s = GameStore(tmp_path / "gamedb.json")
    import_md(s, data_dir)
    mdb = MonsterDB.from_store(s)
    assert mdb.find("giant rat") is not None
    idb = ItemDB.from_store(s)
    assert idb.find("a statue of a bard") is not None
```

- [ ] **Step 2: Run to confirm failure** — both new tests FAIL (`AttributeError` / no `from_store`)

- [ ] **Step 3: Record reconstruction in `src/mmud/data/store.py`** — append:

```python
def _to_dataclass(cls, rec: dict):
    names = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in rec.items() if k in names})


def store_monsters(store: GameStore) -> list:
    from mmud.data.binary import Monster
    return [_to_dataclass(Monster, r) for r in store.data["monsters"].values()]


def store_items(store: GameStore) -> list:
    from mmud.data.binary import Item
    return [_to_dataclass(Item, r) for r in store.data["items"].values()]
```

- [ ] **Step 4: `from_store` constructors** — in `monster_db.py` (after `from_file`):

```python
    @classmethod
    def from_store(cls, store) -> "MonsterDB":
        from mmud.data.store import store_monsters
        return cls(store_monsters(store))
```

and the analogous `ItemDB.from_store` using `store_items`.

- [ ] **Step 5: Config** — `LearningConfig` in `schema.py` (after `PvpConfig`):

```python
@dataclass
class LearningConfig:
    enabled: bool = False            # opt-in: use the GameStore + learning hooks
    store_path: str = "gamedb.json"  # JSON store location (relative to CWD)
```

`MudConfig` gains `learning: LearningConfig = field(default_factory=LearningConfig)`
(after `pvp`). Loader block (after pvp; add `LearningConfig` to imports):

```python
    if le := data.get("learning"):
        cfg.learning = LearningConfig(
            enabled=le.get("enabled", False),
            store_path=le.get("store_path", "gamedb.json"),
        )
```

- [ ] **Step 6: Events** — add to `events.py` (before `GameEventBus`):

```python
@dataclass
class DbImported:
    added: int
    updated: int
    collisions: int

@dataclass
class DbCollision:
    db: str
    record_id: int
```

- [ ] **Step 7: Bot wiring** — in `MudBot.__init__`, replace the monster_db/item_db
construction block with:

```python
        from mmud.data.monster_db import MonsterDB
        from mmud.data.item_db import ItemDB
        self._store = None
        if self._config.learning.enabled and data_dir is not None:
            from mmud.data.store import GameStore, import_md
            self._store = GameStore(pathlib.Path(self._config.learning.store_path))
            report = import_md(self._store, data_dir)
            self._monster_db = MonsterDB.from_store(self._store)
            self._item_db = ItemDB.from_store(self._store)
        else:
            monsters_md = (data_dir / "MONSTERS.MD") if data_dir else None
            self._monster_db = (MonsterDB.from_file(monsters_md)
                                if monsters_md and monsters_md.exists() else MonsterDB([]))
            items_md = (data_dir / "ITEMS.MD") if data_dir else None
            self._item_db = (ItemDB.from_file(items_md)
                             if items_md and items_md.exists() else ItemDB([]))
```

Emit `DbImported(added=sum(report.added.values()), updated=sum(report.updated.values()),
collisions=report.collisions)` after the import, and one `DbCollision(db=c["db"],
record_id=c["record_id"])` per new collision. NOTE: `_emit` requires `self._bus`,
which is assigned later in `__init__` — either move the `self._bus = event_bus`
assignment above this block, or stash the report and emit at the top of `run()`.
Choose the bus-assignment move (one-line reorder, no behavior change).

- [ ] **Step 8: Run** — `pytest -q` → green; document `[learning]` in
`characters/example.toml`:

```toml
[learning]
# Use our own JSON game DB: MD binaries convert/merge in at startup (never
# written); unknown monsters / marks / learned exits persist across sessions.
enabled    = false
store_path = "gamedb.json"
```

- [ ] **Step 9: Commit**

```bash
git add src/mmud/data/ src/mmud/config/ src/mmud/events.py src/mmud/bot.py tests/ characters/example.toml
git commit -m "feat: DBs build from GameStore when [learning] enabled; import events"
```

---

### Task 4: Live learning hooks

**Files:**
- Modify: `src/mmud/data/store.py`, `src/mmud/bot.py`,
  `src/mmud/automation/items.py`, `src/mmud/automation/equip.py`
- Test: `tests/test_store.py` (append), `tests/test_bot.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_store.py`:

```python
def test_learn_monster_allocates_negative_ids(tmp_path):
    s = GameStore(tmp_path / "gamedb.json")
    rec1 = s.learn_monster("shadow fiend")
    rec2 = s.learn_monster("dust wraith")
    assert rec1["record_id"] == -1 and rec2["record_id"] == -2
    assert rec1["origin"] == "learned"
    assert s.learn_monster("Shadow Fiend")["record_id"] == -1   # dedup by name
```

Append to `tests/test_bot.py`:

```python
@pytest.mark.asyncio
async def test_unknown_monster_learned_when_enabled(tmp_path):
    config = MudConfig()
    config.learning.enabled = True
    config.learning.store_path = str(tmp_path / "gamedb.json")
    bot = make_transcript_bot(["Also here: a glimmering wisp.\n"], config=config)
    from mmud.data.store import GameStore
    bot._store = GameStore(tmp_path / "gamedb.json")   # transcript bot has no data_dir
    await bot.run()
    names = [r["name"] for r in bot._store.data["monsters"].values()]
    assert "glimmering wisp" in names
```

- [ ] **Step 2: Run to confirm failure** — `learn_monster` missing → AttributeError

- [ ] **Step 3: `learn_monster` in `GameStore`** — append to the class:

```python
    def learn_monster(self, name: str) -> dict:
        """Record an unseen monster; learned ids are negative. Dedup by name."""
        key = name.strip().lower()
        for rec in self.data["monsters"].values():
            if rec.get("origin") == "learned" and rec["name"] == key:
                return rec
        next_id = min((r["record_id"] for r in self.data["monsters"].values()
                       if r["record_id"] < 0), default=0) - 1
        rec = {"record_id": next_id, "name": key, "origin": "learned",
               "md_hash": "", "level": 0, "exp_value": 0, "combat_rating": 0,
               "alignment": 0, "hp_estimate": 0, "short_name1": "", "short_name2": "",
               "flags": 0}
        self.data["monsters"][str(next_id)] = rec
        self.save()
        return rec
```

- [ ] **Step 4: Bot hook** — in `_parse_room`'s sighting loop, after appending the
`MonsterSighting`, add:

```python
                    if rec is None and self._store is not None:
                        self._store.learn_monster(name)
```

- [ ] **Step 5: Persist marks** — give `GetDecider` and `EquipDecider` an optional
store: add an `on_mark: Callable[[str], None] | None = None` constructor kwarg to
each; call it inside `mark_ungettable` / `mark_failed`. In bot wiring pass:

```python
        self._get_decider = GetDecider(
            self._config.items,
            on_mark=(lambda n: self._store.add_mark("ungettable", n)) if self._store else None)
```

(and `no_auto_equip` for EquipDecider). Seed at startup, right after the deciders
are built:

```python
        if self._store is not None:
            for n in self._store.marks("ungettable"):
                self._get_decider.mark_ungettable(n)
            for n in self._store.marks("no_auto_equip"):
                self._equip_decider.mark_failed(n)
```

(Seeding calls the mark methods, which re-call `on_mark` — `add_mark` dedups, so
this is idempotent; no special-casing needed.)

- [ ] **Step 6: Run** — `pytest -q` → green

- [ ] **Step 7: Commit**

```bash
git add src/mmud/data/store.py src/mmud/bot.py src/mmud/automation/items.py src/mmud/automation/equip.py tests/
git commit -m "feat: live learning — unknown monsters + persistent ungettable/no-equip marks"
```

---

### Task 5: Collision/learning visibility — @db verb + README

**Files:**
- Modify: `src/mmud/automation/remote.py`, `README.md`
- Test: `tests/test_remote.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_db_verb_reports_store_stats():
    bot = _bot(WILDCARD)
    from mmud.data.store import GameStore
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        bot._store = GameStore(pathlib.Path(td) / "g.json")
        bot._store.data["monsters"]["1"] = {"record_id": 1, "name": "rat", "origin": "md"}
        bot._store.data["collisions"].append({"db": "monsters", "record_id": 1})
        h = RemoteCommandHandler(bot)
        reply = h.handle("Friend", "@db")
        assert "1 monsters" in reply and "1 collisions" in reply


def test_db_verb_without_store():
    bot = _bot(WILDCARD)
    bot._store = None
    h = RemoteCommandHandler(bot)
    assert "disabled" in h.handle("Friend", "@db").lower()
```

- [ ] **Step 2: Run to confirm failure** — `@db` unknown verb → first test fails

- [ ] **Step 3: Register the verb** — in `_register_builtins`:

```python
        self.register("db", self._db_stats)
```

and the method:

```python
    def _db_stats(self, sender: str, arg: str) -> str:
        store = getattr(self._bot, "_store", None)
        if store is None:
            return "learning disabled"
        d = store.data
        return (f"{len(d['monsters'])} monsters, {len(d['items'])} items, "
                f"{len(d['spells'])} spells, {len(d['exits'])} learned exits, "
                f"{len(d['collisions'])} collisions")
```

NOTE: `MudBot.__init__` constructs `RemoteCommandHandler(self)` before the store
block from Task 3 — `getattr(..., None)` keeps the verb safe regardless of order.

- [ ] **Step 4: README** — add a short "Game DB store (`[learning]`)" subsection
under the config reference: what it does (own JSON DB, MD merge-on-start, never
writes MDs, collision policy = local wins + logged), the `@db` verb, and that
deleting `gamedb.json` rebuilds it from the MDs losing learned data.

- [ ] **Step 5: Run** — `pytest -q` → green

- [ ] **Step 6: Commit**

```bash
git add src/mmud/automation/remote.py README.md tests/test_remote.py
git commit -m "feat: @db verb — store stats; README learning docs"
```

---

## Verification

- `pytest -q` — full suite green after every task.
- Manual: with `[learning] enabled = true`, start the bot once against the data
  dir → `gamedb.json` appears with 788/667/936 records; start again → instant
  (fingerprints skip); edit one record's `origin` to `"override"`, change a field
  and stale the fingerprint → next start logs exactly one collision and keeps
  the local value.
- Phase 6 consumes `store.add_exit`/`store.exits()` — that integration is tested
  in the Phase 6 plan, not here.
