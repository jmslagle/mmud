# The CDB / "MDB2" database engine

Reverse-engineered from `megamud.exe` (Ghidra project `mmud.gpr`). This is the
keyed-record B-tree engine that reads and writes every `*.MD` game-data file
(`MONSTERS.MD`, `ITEMS.MD`, `SPELLS.MD`, `PLAYERS.MD`, `ROOMS.MD`, …). The
engine functions are named `cdb_*` and live at `0x004a0000`–`0x004a4500`; the
on-disk format is identified by the 4-byte magic **`MDB2`**.

> Status: the read path is well understood and matches the empirical parser in
> `src/mmud/data/binary.py`. Offsets below are taken directly from the
> decompiled `cdb_*` functions; a few fields whose purpose isn't fully pinned
> are marked *(unconfirmed)*. The current Python loaders only read records — they
> never need to write — so the write/split path is documented for completeness,
> not because the port exercises it.

## File shape

A `.MD` file is a sequence of fixed **0x400-byte (1024) pages**:

```
page 0   : file header (first 0x1c bytes used; rest of the page reserved)
page 1.. : B-tree nodes (leaf "data" pages + interior "index" pages)
```

Page `N` lives at byte offset `(N+1) * 0x400` for data nodes — page numbers in
the header/nodes are **1-based**, and `cdb_write_page_raw` writes page `p` at
`(p+1)*0x400`. Page 0 (the header) is at offset 0.

### File header (page 0, 0x1c = 28 bytes)

From `cdb_read_header_page` (`0x004a09c0`) and `cdb_header_init` (`0x004a2d70`):

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| `0x00` | 4 | magic `"MDB2"` | only the first 4 bytes are compared (`strncmp`, `DAT_004c6e98`). `binary.py` reads it as `MDB2X\0` — bytes 4–5 are *not* part of the magic check |
| `0x04` | 2 | record/entry count | zeroed on init |
| `0x0a` | 2 | **root page** | `=1` on a fresh DB |
| `0x0c` | 2 | first/next page *(unconfirmed)* | `=1` on init |
| `0x10` | 2 | next-free page *(unconfirmed)* | `=1` on init |
| `0x14` | 2 | page count | `binary.py` reads page count here |
| …      |   | generation counter *(unconfirmed offset)* | bumped by `cdb_write_header_from_handle` on every header write; readers compare it to detect a stale page cache |

`cdb_read_header_page` returns `0` on a valid header, or a negative status:
`-5` (`0xfffffffb`) bad magic, `-7` (`0xfffffff9`) seek failure, `-9`
(`0xfffffff7`) short read. These are the same negative status codes the rest of
the engine uses.

### B-tree node (every page ≥ 1, 0x400 bytes)

From `cdb_node_init` (`0x004a2da0`) and `cdb_node_entry_at` (`0x004a1d60`):

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| `0x00` | 1 | node type | `0` = leaf/data node, `1`/`2` = interior/index node (matches `binary.py`'s "first byte 0x01/0x02 = index page") |
| `0x02` | 2 | entry count | number of variable-length entries in this node |
| `0x04` | 2 | free bytes | `0x3f4` (1012) when empty — i.e. `0x400` minus the 0xc-byte node header |
| `0x06` | 2 | reserved *(unconfirmed)* | |
| `0x08` | 2 | prev-leaf page | `0xffff` = none (leaf nodes are doubly linked) |
| `0x0a` | 2 | next-leaf page | `0xffff` = none |
| `0x0c` | … | entry area | variable-length entries, total `0x3f4` bytes |

**Entries are variable-length and length-prefixed.** Each entry starts with a
1-byte length `L`, and the next entry is reached by `ptr += L + 1`
(`cdb_node_entry_at` walks them this way; there is no fixed stride). To get the
i-th entry you must walk from the first.

> This length-prefixed walk is why the empirical `binary.py` uses a `0x80`
> record-marker scan with a ~221-byte spacing heuristic: it's reading the entry
> *payloads* without modelling the length prefix. The authoritative structure is
> the length-prefixed walk above.

### Entry / key structure

A key is a packed tuple, compared by `cdb_key_compare` (`0x004a1030`) and split
out by `cdb_key_get_int` (`0x004a0fd0`), `cdb_key_get_tag` (`0x004a0ff0`),
`cdb_key_get_child_page` (`0x004a1010`):

```
[ name bytes ... \0 ][ int32 ][ tag u8 ]   (+ child-page u16, interior nodes only)
```

- **name** — NUL-terminated string (record name, e.g. a monster name).
- **int32** — the numeric record id, immediately after the name's NUL.
- **tag** — 1 byte after the int32. In `cdb_key_compare` the tag is masked with
  `0x7f`; a masked value of `0` acts as a **wildcard** that skips the tag
  comparison (lets you look a record up by name+id without knowing the tag).
- **child page** — interior (index) node entries carry a `u16` child page
  number used to descend the tree.

Comparison order is: name (`strcmp`) → int32 → tag (unless wildcard).

## Algorithms

### Lookup (read path)

`cdb_btree_find_leaf_entry` (`0x004a12e0`): load the root page from the header
(`cdb_load_root_from_header`), descend interior nodes to the target leaf
(`cdb_btree_descend_to_leaf`, `0x004a18b0`), then scan the leaf for the first
entry `>=` the search key. Cursors (`cdb_cursor_*`) keep a per-level key buffer
(21 levels, `cdb_cursor_keybufs_init`) and walk the leaf chain via the
prev/next-leaf links for `cdb_cursor_next` / `cdb_cursor_prev`.

### Page cache

An LRU cache of `0x410`-byte slots (a 0x400 page + a small header), head at
`DAT_004dcd60`. `cdb_get_page_cached` (`0x004a0b20`) looks a `(fd, page)` slot
up, reads + promotes to MRU on a miss (`cdb_cache_move_to_front`), and evicts /
flushes dirty slots on the write path. Cache validity is keyed off the header
**generation counter**: `cdb_check_lock_generation` re-reads the header, and if
the generation changed (another process wrote the file) it invalidates the fd's
cache (`cdb_cache_invalidate_fd`) and reloads the root
(`cdb_refresh_root_if_changed`).

### Concurrency / locking

Multi-process safe via byte-range file locks (`_locking`, the `crt_locking`
wrapper): `cdb_acquire_record_lock` / `cdb_release_record_lock`
(`0x004a0780` / `0x004a07f0`) take non-blocking locks over the file regions
`0x200..0x27f` (a 128-slot lock table), and `cdb_file_lock_index_region` locks
the index region at `offset+0x200`. The generation-counter scheme above is how a
reader notices a writer committed underneath it.

### Write path (not exercised by the port)

`cdb_btree_insert` (`0x004a2de0`) does leaf insert/replace with node split and
parent fixup; helpers in `0x004a3000`–`0x004a3c60` handle page split-point
selection, key-entry construction, cursor-path key-count adjustment, and
write-back cache stores. `cdb_grow_file` appends zero-filled pages,
`cdb_write_header_from_handle` rewrites the header and bumps the generation,
`cdb_rebuild_database` (`0x004a0510`) compacts a DB by copying every record
across its 19 key classes into a fresh file.

## Function map

| Address | Name | Role |
|---------|------|------|
| `0x004a05f0` | `cdb_header_magic_check` | validate magic + open/closed state byte |
| `0x004a0620` | `cdb_header_magic_write` | stamp magic + state byte |
| `0x004a0640`–`0x004a06e0` | `cdb_region_lock_*`, `cdb_file_lock_index_region` | byte-range record/index locks |
| `0x004a09c0` | `cdb_read_header_page` | read + verify the 0x1c header |
| `0x004a0b20` | `cdb_get_page_cached` | cached page fetch |
| `0x004a0fd0`–`0x004a1030` | `cdb_key_get_int` / `_tag` / `_child_page` / `cdb_key_compare` | key field access + 3-way compare |
| `0x004a12e0` | `cdb_btree_find_leaf_entry` | top-level keyed lookup |
| `0x004a18b0` | `cdb_btree_descend_to_leaf` | interior-node descent |
| `0x004a1d60` | `cdb_node_entry_at` | i-th variable-length entry pointer |
| `0x004a1d90`–`0x004a27c0` | `cdb_cursor_*` | cursor seek / next / prev / reload |
| `0x004a2d70` / `0x004a2da0` | `cdb_header_init` / `cdb_node_init` | fresh header / node layout |
| `0x004a2de0` | `cdb_btree_insert` | leaf insert + split |
| `0x004a3e40` / `0x004a4290` | `cdb_write_record` / `cdb_read_record` | record-level write / read |
| `0x004a4480` | `cdb_read_record_chain` | reassemble a multi-chunk record |

Per-record field layouts (the *value* half of each entry — stat blocks for
monsters/items/spells/players) are documented separately; see
`src/mmud/data/binary.py` and the binary-struct notes.
