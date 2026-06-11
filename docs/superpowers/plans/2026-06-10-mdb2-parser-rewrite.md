# MDB2 Parser Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execute BEFORE Phase 4** — Phase 4's `monster_db.py` and Phase 5's `item_db.py` consume these loaders.

**Goal:** Replace `binary.py`'s coincidental marker-scan parser with the true MDB2 B-tree entry walk, recovering ~60 missed monsters, ~250 missed item names, and all 936 spell entries.

**Architecture:** One new generator `_walk_entries()` implements the real on-disk format (length-prefixed entries inside 0x400-byte leaf nodes, key = class byte + ASCII id + int32 + tag, payload after the tag). The four `load_*` functions are rewired to consume it with payload-relative offsets (old marker-relative − 1). Dataclasses and public signatures are unchanged.

**Tech Stack:** Python 3.11+, stdlib `struct`/`pathlib`. No new dependencies.

**Background:** `docs/cdb-mdb2-format.md` (from the megamud.exe RE). Validated empirically against `extractions/mm103s.exe.extracted/45DAD/Default/`:

| File | Entries (true walk) | Active | Payload size | Old parser found |
|------|--------------------:|-------:|-------------:|------------------|
| MONSTERS.MD | 788 | 788 (all) | 210 every entry | 594 unique names (60 names missed entirely, e.g. "ankheg", "black orc", "acid slime") |
| ITEMS.MD | 1336 | 667 | 200 every entry | 381 unique names (337 missed, e.g. "a statue of a bard") |
| SPELLS.MD | 936 | n/a (see Task 4) | 158 every entry | 137 names via flag-scan luck |
| CLASSES.MD | 15 | — | — | — |

**Key facts (no re-derivation needed):**
- Header (page 0, offset 0): magic `"MDB2"` in first 4 bytes (compare 4 bytes ONLY — byte 4 varies).
- Pages 1..N at byte offset `page * 0x400`; `N = len(data)//0x400 - 1`.
- Node header: type `u8@0x00` (`0`=leaf, `1`/`2`=interior — skip interior), entry count `u16@0x02`, free bytes `u16@0x04`, prev/next leaf `u16@0x08/0x0a`. Entries start at node+`0x0c`.
- Entry walk: first byte is length `L`; entry body is the next `L` bytes; next entry at `ptr + L + 1`.
- Entry body: `[key-class byte 0x01][ASCII record-id]\0[int32][tag u8]` then the payload. Parse: `nul = body.find(0)`; key name = `body[:nul]`; tag = `body[nul+5]` (always `0x80` in these files); payload = `body[nul+6:]`.
- Payload field offsets = old marker-relative offsets − 1 (the old "0x80 marker" was the key's tag byte).
- Monsters/items flags `u32` at payload+`0x21` (`0x40000000` active, `0x80000000` deleted). **Spells do NOT have this flag dword** — do not filter spells on it (only 9/936 coincidentally match).
- ROOMS.MD is NOT MDB2 (text format, magic reads `CAB0`) — the magic check must reject it loudly.

---

## File Map

```
src/mmud/data/binary.py    MODIFY — new walker; rewire 4 loaders; delete dead heuristics
tests/test_binary.py       MODIFY — new walker tests; updated count/name pins
docs/cdb-mdb2-format.md    MODIFY — addendum: key-name encoding, payload sizes
README.md                  MODIFY — data-file table record counts
```

---

### Task 1: `_walk_entries` — the true-format walker

**Files:**
- Modify: `src/mmud/data/binary.py`
- Test: `tests/test_binary.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_binary.py`:

```python
# ── True MDB2 walker ─────────────────────────────────────────────────────────
import pytest
from mmud.data.binary import MdEntry, walk_entries


def test_walker_monster_totals(data_dir):
    entries = list(walk_entries(data_dir / "MONSTERS.MD"))
    assert len(entries) == 788
    assert all(e.tag == 0x80 for e in entries)
    assert all(len(e.payload) == 210 for e in entries)


def test_walker_item_totals(data_dir):
    entries = list(walk_entries(data_dir / "ITEMS.MD"))
    assert len(entries) == 1336
    assert all(len(e.payload) == 200 for e in entries)


def test_walker_spell_totals(data_dir):
    entries = list(walk_entries(data_dir / "SPELLS.MD"))
    assert len(entries) == 936
    assert all(len(e.payload) == 158 for e in entries)


def test_walker_classes_totals(data_dir):
    assert len(list(walk_entries(data_dir / "CLASSES.MD"))) == 15


def test_walker_key_id_matches_payload_id(data_dir):
    # The key's ASCII record-id equals the u16 at payload+0
    import struct
    for e in list(walk_entries(data_dir / "MONSTERS.MD"))[:50]:
        assert e.record_id == struct.unpack_from("<H", e.payload, 0)[0]


def test_walker_rejects_non_mdb2(data_dir):
    # ROOMS.MD is the text-format DB, not MDB2
    with pytest.raises(ValueError, match="MDB2"):
        list(walk_entries(data_dir / "ROOMS.MD"))
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_binary.py -v -k walker`
Expected: FAIL with `ImportError: cannot import name 'MdEntry'`

- [ ] **Step 3: Implement the walker**

In `src/mmud/data/binary.py`, after the `_active` helper, add:

```python
# ── True MDB2 B-tree walk (see docs/cdb-mdb2-format.md) ─────────────────────

_MAGIC = b"MDB2"
_NODE_HEADER_SIZE = 0x0C


@dataclass
class MdEntry:
    """One B-tree leaf entry: key fields + the game-record payload."""
    key_class: int    # first byte of the key name (0x01 = by-record-number)
    record_id: int    # the key's ASCII record id, as int
    key_int: int      # int32 after the key name's NUL (0 in all observed files)
    tag: int          # key class tag byte (0x80 = record)
    payload: bytes    # the game record (210B monsters / 200 items / 158 spells)


def walk_entries(path: pathlib.Path):
    """Yield every MdEntry from an MDB2 file, walking leaves in page order.

    Entries are length-prefixed: [L u8][body L bytes], next at ptr+L+1.
    Body = [key-class][ascii-id]\\0[int32][tag] + payload.
    Raises ValueError if the file is not an MDB2 database (e.g. ROOMS.MD).
    """
    data = path.read_bytes()
    if data[:4] != _MAGIC:
        raise ValueError(f"{path.name}: not an MDB2 database (magic {data[:4]!r})")
    num_pages = len(data) // _PAGE_SIZE - 1
    for page_num in range(1, num_pages + 1):
        page = data[page_num * _PAGE_SIZE : (page_num + 1) * _PAGE_SIZE]
        if page[0] in (1, 2):       # interior/index node
            continue
        count = struct.unpack_from("<H", page, 0x02)[0]
        ptr = _NODE_HEADER_SIZE
        for _ in range(count):
            length = page[ptr]
            body = page[ptr + 1 : ptr + 1 + length]
            ptr += length + 1
            nul = body.find(b"\x00")
            if nul < 1 or nul + 6 > len(body):
                continue            # malformed entry: skip, never crash
            ascii_id = body[1:nul]
            yield MdEntry(
                key_class=body[0],
                record_id=int(ascii_id) if ascii_id.isdigit() else -1,
                key_int=struct.unpack_from("<i", body, nul + 1)[0],
                tag=body[nul + 5],
                payload=bytes(body[nul + 6 :]),
            )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_binary.py -v -k walker`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/mmud/data/binary.py tests/test_binary.py
git commit -m "feat: true MDB2 length-prefixed entry walker"
```

---

### Task 2: Rewire `load_monsters`

**Files:**
- Modify: `src/mmud/data/binary.py:121-171` (`load_monsters`)
- Test: `tests/test_binary.py` (append + update)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_binary.py`:

```python
def test_monsters_recovered_by_true_walk(data_dir):
    from mmud.data.binary import load_monsters
    monsters = load_monsters(data_dir / "MONSTERS.MD")
    assert len(monsters) == 788          # every entry is active in this file
    names = {m.name.lower() for m in monsters}
    # Previously missed by the 2-per-page heuristic:
    for missed in ("ankheg", "black orc", "acid slime", "bounty hunter"):
        assert missed in names
    # Still present:
    assert "giant rat" in names
    assert all(m.is_active for m in monsters)
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_binary.py -v -k recovered_by_true`
Expected: FAIL — `len(monsters)` is ~712, "ankheg" missing

- [ ] **Step 3: Rewrite `load_monsters`**

Replace the body of `load_monsters` (keep the docstring's field table, shifting each offset down by 1 and noting they are payload-relative):

```python
def load_monsters(path: pathlib.Path) -> list[Monster]:
    """Parse MONSTERS.MD and return all active (non-deleted) Monster records.

    Field offsets within each entry payload (true MDB2 walk; see
    docs/cdb-mdb2-format.md):
      +0x00: u16 record_id
      +0x02: char[31] name
      +0x21: u32 flags
      +0x25: u8  combat_rating
      +0x35: i16 level
      +0x39: i16 exp_value
      +0x3d: i16 alignment
      +0x3f: i16 hp_estimate
    Short names appear within the name field (null-separated) for some monsters.
    """
    out: list[Monster] = []
    for entry in walk_entries(path):
        p = entry.payload
        flags = struct.unpack_from("<I", p, 0x21)[0]
        if not _active(flags):
            continue
        name = _cstr(p, 0x02, 31)
        if not name:
            continue
        name_block = p[0x02 : 0x02 + 31]
        parts = name_block.split(b"\x00")
        short_name1 = parts[1].decode("latin-1", errors="replace").strip() if len(parts) > 1 else ""
        short_name2 = parts[2].decode("latin-1", errors="replace").strip() if len(parts) > 2 else ""
        out.append(Monster(
            record_id=struct.unpack_from("<H", p, 0x00)[0],
            name=name,
            level=struct.unpack_from("<h", p, 0x35)[0],
            exp_value=struct.unpack_from("<h", p, 0x39)[0],
            combat_rating=p[0x25],
            alignment=struct.unpack_from("<h", p, 0x3D)[0],
            hp_estimate=struct.unpack_from("<h", p, 0x3F)[0],
            short_name1=short_name1,
            short_name2=short_name2,
            flags=flags,
        ))
    return out
```

- [ ] **Step 4: Run the full binary test file**

Run: `pytest tests/test_binary.py -v`
Expected: all pass (the old `test_monster_count_reasonable` asserts `> 100`, still true).

- [ ] **Step 5: Commit**

```bash
git add src/mmud/data/binary.py tests/test_binary.py
git commit -m "feat: load_monsters via true MDB2 walk — recovers 60 missed monsters (788 total)"
```

---

### Task 3: Rewire `load_items`

**Files:**
- Modify: `src/mmud/data/binary.py:196-261` (`load_items`)
- Test: `tests/test_binary.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
def test_items_recovered_by_true_walk(data_dir):
    from mmud.data.binary import load_items
    items = load_items(data_dir / "ITEMS.MD")
    assert len(items) == 667             # active entries of 1336 total
    names = {i.name.lower() for i in items}
    assert "a statue of a bard" in names   # missed by the old heuristic
    assert all(i.is_active for i in items)
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_binary.py -v -k items_recovered`
Expected: FAIL — old parser returns ~400 items

- [ ] **Step 3: Rewrite `load_items`**

Same shape as Task 2. Items' flags are at a fixed payload offset `0x21` — replace the old flag-scan loop with the direct read. All other field offsets shift −1:

```python
def load_items(path: pathlib.Path) -> list[Item]:
    """Parse ITEMS.MD and return all active Item records.

    Payload offsets (true MDB2 walk):
      +0x00: u16 record_id   +0x02: char[31] name   +0x21: u32 flags
      +0x21+31..: description/suffix strings
      +0x5f: u8 item_type   +0x60: u8 equip_slot
      +0x63/+0x67/+0x6b: i16 ac_or_dmg / weight / value
      +0x6f/+0x73: u32 extra stats
    Numeric offsets are the old empirical ones shifted −1; they remain
    approximate until Phase 5's item_db consumes them in anger.
    """
    out: list[Item] = []
    for entry in walk_entries(path):
        p = entry.payload
        flags = struct.unpack_from("<I", p, 0x21)[0]
        if not _active(flags):
            continue
        name = _cstr(p, 0x02, 31)
        if not name:
            continue
        desc_start = 0x02 + 31
        out.append(Item(
            record_id=struct.unpack_from("<H", p, 0x00)[0],
            name=name,
            description=_cstr(p, desc_start, 40),
            suffix=_cstr(p, desc_start + 40, 14),
            item_type=p[0x5F],
            equip_slot=p[0x60],
            ac_or_dmg=struct.unpack_from("<h", p, 0x63)[0],
            weight=struct.unpack_from("<h", p, 0x67)[0],
            value=struct.unpack_from("<h", p, 0x6B)[0],
            extra_stat1=struct.unpack_from("<I", p, 0x6F)[0],
            extra_stat2=struct.unpack_from("<I", p, 0x73)[0],
            flags=flags,
        ))
    return out
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_binary.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/mmud/data/binary.py tests/test_binary.py
git commit -m "feat: load_items via true MDB2 walk — 667 active items (was ~400)"
```

---

### Task 4: Rewire `load_spells` — no flag filter

**Files:**
- Modify: `src/mmud/data/binary.py:286-343` (`load_spells`)
- Test: `tests/test_binary.py` (append + adjust)

> Spell records do NOT carry the monsters/items active-flag dword (validated:
> only 9/936 payloads have `0x40000000` at +0x21 — coincidence). The old
> parser's 141 "active" spells were flag-scan luck, and its short-name /
> kai_cost / level_req extraction was unreliable. The true layout (validated
> sample, "major healing"): short name is a NUL-terminated string at payload
> +0x21 (e.g. "han"), and u16 stats live near +0x5a. Load ALL entries; mark
> stat fields provisional.

- [ ] **Step 1: Write the failing tests**

```python
def test_spells_all_entries_loaded(data_dir):
    from mmud.data.binary import load_spells
    spells = load_spells(data_dir / "SPELLS.MD")
    assert len(spells) == 936
    names = {s.full_name.lower() for s in spells}
    assert "major healing" in names
    by_name = {s.full_name.lower(): s for s in spells}
    assert by_name["major healing"].short_name == "han"
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_binary.py -v -k spells_all`
Expected: FAIL — old parser returns ~141 spells

- [ ] **Step 3: Rewrite `load_spells`**

```python
def load_spells(path: pathlib.Path) -> list[Spell]:
    """Parse SPELLS.MD and return ALL spell records (no flag filtering).

    Spell records do not carry the monsters/items active/deleted flag dword.
    Payload offsets (true MDB2 walk; stats provisional until a consumer
    validates them against in-game values):
      +0x00: u16 record_id
      +0x02: char[31] full spell name
      +0x21: char[~10] short name / incantation (NUL-terminated)
      +0x5a: u16 (provisional: mana/kai cost)
      +0x5c: u16 (provisional: level requirement)
    """
    out: list[Spell] = []
    for entry in walk_entries(path):
        p = entry.payload
        full_name = _cstr(p, 0x02, 31)
        if not full_name:
            continue
        out.append(Spell(
            record_id=struct.unpack_from("<H", p, 0x00)[0],
            short_name=_cstr(p, 0x21, 10),
            full_name=full_name,
            description="",
            kai_cost=struct.unpack_from("<H", p, 0x5A)[0],
            level_req=struct.unpack_from("<H", p, 0x5C)[0],
            duration=0,
            flags=0,
        ))
    return out
```

Note: `Spell.description`/`duration`/`flags` are kept in the dataclass for API
stability but are no longer populated (the old values were garbage reads).
`is_known`/`is_active` now return False — nothing consumes them yet.

- [ ] **Step 4: Fix the older spell tests**

The existing `test_load_spells_has_known_names` and `test_spell_count_reasonable`
(`> 50`) should still pass. If `test_load_spells_has_known_names` asserts a name
that was a misparse, update it to assert names verified above.

Run: `pytest tests/test_binary.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/mmud/data/binary.py tests/test_binary.py
git commit -m "feat: load_spells via true MDB2 walk — all 936 entries, honest field set"
```

---

### Task 5: `load_players`, `probe_binary`, delete dead code, docs sync

**Files:**
- Modify: `src/mmud/data/binary.py` (remainder), `docs/cdb-mdb2-format.md`, `README.md`
- Test: `tests/test_binary.py` (existing tests keep passing)

- [ ] **Step 1: Rewire `load_players`**

PLAYERS.MD is absent from the extraction (the test is `does_not_crash`). Keep
behavior: return `[]` when missing; otherwise walk entries with offsets −1
(name `+0x02` len 11, title `+0x0d` len 19, guild `+0x20` len 31, location
`+0x3f` len 21, numerics at old offsets −1, flags read directly at `+0x21` —
same dword position as monsters/items; players DO carry friend/enemy flags):

```python
def load_players(path: pathlib.Path) -> list[Player]:
    """Parse PLAYERS.MD and return all non-deleted Player records."""
    if not path.exists():
        return []
    out: list[Player] = []
    for entry in walk_entries(path):
        p = entry.payload
        name = _cstr(p, 0x02, 11)
        if not name:
            continue
        flags = struct.unpack_from("<I", p, 0x21)[0]
        if _deleted(flags):
            continue
        out.append(Player(
            name=name,
            title=_cstr(p, 0x0D, 19),
            guild=_cstr(p, 0x20, 31),
            location=_cstr(p, 0x3F, 21),
            level=struct.unpack_from("<h", p, 0x57)[0],
            alignment=struct.unpack_from("<h", p, 0x5F)[0],
            class_id=struct.unpack_from("<h", p, 0x63)[0],
            race_id=struct.unpack_from("<h", p, 0x67)[0],
            reputation=struct.unpack_from("<h", p, 0x6B)[0],
            first_seen=struct.unpack_from("<i", p, 0x77)[0],
            last_seen=struct.unpack_from("<i", p, 0x7B)[0],
            flags=flags,
        ))
    return out
```

- [ ] **Step 2: Delete the dead heuristics**

Remove from `binary.py`: `_find_entry1_offset`, `_iter_page_entries`,
`_iter_all_entries`, `_ENTRY_MARKER`, `_ENTRY_SPACING`, `_ENTRY_SPACING_ALT`.
Rewrite the module docstring "Format note" to describe the true format (copy
the **Key facts** block from this plan's header). Keep `extract_strings` and
`probe_binary` as-is (they are format-agnostic probe tools).

- [ ] **Step 3: Run everything**

Run: `pytest -q`
Expected: full suite green; `grep -n "_ENTRY_SPACING" src/ -r` → no hits.

- [ ] **Step 4: Docs sync**

- `docs/cdb-mdb2-format.md` — in the "Entry / key structure" section, add:
  the key name observed in game DBs is `[key-class byte 0x01][ASCII record-id]`
  (not the record's display name); payload sizes are fixed per DB
  (monsters 210 / items 200 / spells 158 / players 248); tag `0x80` is the
  record key class; remove/replace the note speculating about `binary.py`'s
  221-byte heuristic (now rewritten to the true walk).
- `README.md` data-file table: MONSTERS.MD "788 monster records",
  ITEMS.MD "667 active item records (1336 entries)", SPELLS.MD "936 spell records".

- [ ] **Step 5: Commit**

```bash
git add src/mmud/data/binary.py tests/test_binary.py docs/cdb-mdb2-format.md README.md
git commit -m "refactor: remove marker-scan heuristics; players loader on true walk; docs sync"
```

---

## Verification

- `pytest -q` — full suite green (210 pre-existing + new binary tests).
- Sanity probe (should print 788 / 667 / 936):
  ```bash
  python3 -c "
  import pathlib
  from mmud.data.binary import load_monsters, load_items, load_spells
  d = pathlib.Path('extractions/mm103s.exe.extracted/45DAD/Default')
  print(len(load_monsters(d/'MONSTERS.MD')), len(load_items(d/'ITEMS.MD')), len(load_spells(d/'SPELLS.MD')))"
  ```
- No consumer breakage possible: `grep -rn "load_monsters\|load_items\|load_spells\|load_players" src/mmud --include='*.py'` shows binary.py only (loaders unused by bot logic until Phase 4).
