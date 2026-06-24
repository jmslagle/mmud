"""Binary data probing and parsing utilities for game database files (MONSTERS.MD, ITEMS.MD, etc.).

The container is the "MDB2" CDB B-tree engine, fully documented in
docs/cdb-mdb2-format.md (derived from the decompiled cdb_* functions in
megamud.exe). `walk_entries()` implements the true on-disk format; the
`load_*` helpers parse each entry's payload into typed records.

Format summary (true MDB2 walk):
  - Page 0 (bytes 0..0x3ff): file header. Magic "MDB2" in the first 4 bytes;
    root page u16 @0x0a; page count u16 @0x14.
  - Pages 1..N at byte offset page*0x400 (N = len(data)//0x400 - 1).
  - Node header (0x0c bytes): type u8 @0x00 (0=leaf, 1/2=interior — skipped),
    entry count u16 @0x02, free bytes u16 @0x04, prev/next leaf u16 @0x08/0x0a.
  - Entries start at node+0x0c and are length-prefixed: [L u8][body L bytes],
    next entry at ptr+L+1.
  - Entry body: [key-class byte 0x01][ASCII record-id]\\0[int32][tag u8] then the
    fixed-size game-record payload (monsters 210B / items 200B / spells 158B /
    players 248B). The tag (0x80) is the record key class.
  - Payload field offsets used below are the historical marker-relative offsets
    minus 1 (the old "0x80 marker" was this key tag byte).
"""
from __future__ import annotations

import pathlib
import re
import struct
from dataclasses import dataclass

# ── File-format constants ────────────────────────────────────────────────────

_PAGE_SIZE = 1024
_FLAG_ACTIVE = 0x40000000
_FLAG_DELETED = 0x80000000

# ── Low-level helpers ────────────────────────────────────────────────────────


def _cstr(data: bytes, offset: int, maxlen: int) -> str:
    chunk = data[offset : offset + maxlen]
    nul = chunk.find(b"\x00")
    raw = chunk[:nul] if nul >= 0 else chunk
    return raw.decode("latin-1", errors="replace").strip()


def _deleted(flags: int) -> bool:
    return bool(flags & _FLAG_DELETED)


def _active(flags: int) -> bool:
    return bool(flags & _FLAG_ACTIVE) and not _deleted(flags)


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


# ── Monster ──────────────────────────────────────────────────────────────────

@dataclass
class Monster:
    record_id: int
    name: str
    level: int
    exp_value: int
    combat_rating: int   # MegaMud kill-type tier (in-mem record +0x28): 2=good NPC,
                         # 3=neutral, 4=hostile, 5=special. Gates auto-attack
                         # (combat_flee_or_hide_decide: `tier != 4 -> skip`).
    alignment: int
    hp_estimate: int
    short_name1: str
    short_name2: str
    flags: int

    @property
    def is_active(self) -> bool:
        return _active(self.flags)


def load_monsters(path: pathlib.Path) -> list[Monster]:
    """Parse MONSTERS.MD and return all active (non-deleted) Monster records.

    Field offsets within each entry payload (true MDB2 walk; see
    docs/cdb-mdb2-format.md):
      +0x00: u16 record_id
      +0x02: char[31] name
      +0x21: u32 flags
      +0x25: u8  combat_rating (kill-type tier; see dataclass note)
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


# ── Item ─────────────────────────────────────────────────────────────────────

@dataclass
class Item:
    record_id: int
    name: str
    source: str          # the shop the item is sold by (e.g. "Furniture Shop")
    suffix: str
    item_type: int
    equip_slot: int
    ac_or_dmg: int
    weight: int
    value: int
    extra_stat1: int
    flags: int

    @property
    def is_active(self) -> bool:
        return _active(self.flags)


def load_items(path: pathlib.Path) -> list[Item]:
    """Parse ITEMS.MD records.

    On-disk payload layout, derived from `items_md_save` (megamud.exe 0x00441210)
    which str_copy_safe's each field into a fixed buffer, and verified against the
    real file (e.g. record 1093 'desk': source 'Furniture Shop' @0x20; value 100
    for the quarterstaff @0x5d):
      +0x00 u16 record_id   +0x02 char[30] name   +0x20 char[41] source
      +0x49 char[14] suffix
      +0x57 i16 ac_or_dmg   +0x59 i16 weight   +0x5b u8 item_type
      +0x5d i16 value       +0x5f u32 extra_stat1   +0x63 u32 flags
      +0xa3 u8 equip_slot
    NB: items differ from monsters — 0x20 is the *source* string, NOT flags (the
    old parser cloned the monster layout, corrupting every field). No active-flag
    filter: items_md_save writes only active records and removes deleted ones from
    the B-tree, so walk_entries already yields live records only. Numeric field
    *semantics* (item_type/ac_or_dmg/…) are best-effort; the offsets are
    save-derived, name/source/suffix/value are confirmed.
    """
    out: list[Item] = []
    for entry in walk_entries(path):
        p = entry.payload
        name = _cstr(p, 0x02, 30)
        if not name:
            continue
        out.append(Item(
            record_id=struct.unpack_from("<H", p, 0x00)[0],
            name=name,
            source=_cstr(p, 0x20, 41),
            suffix=_cstr(p, 0x49, 14),
            ac_or_dmg=struct.unpack_from("<h", p, 0x57)[0],
            weight=struct.unpack_from("<h", p, 0x59)[0],
            item_type=p[0x5B],
            value=struct.unpack_from("<h", p, 0x5D)[0],
            extra_stat1=struct.unpack_from("<I", p, 0x5F)[0],
            flags=struct.unpack_from("<I", p, 0x63)[0],
            equip_slot=p[0xA3],
        ))
    return out


# ── Spell ────────────────────────────────────────────────────────────────────

@dataclass
class Spell:
    record_id: int
    short_name: str
    full_name: str
    description: str
    kai_cost: int
    level_req: int
    duration: int
    flags: int

    @property
    def is_known(self) -> bool:
        return bool(self.flags & 0x1000)

    @property
    def is_active(self) -> bool:
        return _active(self.flags)


def load_spells(path: pathlib.Path) -> list[Spell]:
    """Parse SPELLS.MD records.

    On-disk layout derived from `spells_md_save` (megamud.exe 0x0047cfc0) and
    verified against the real file (record 1 'magic missile': short 'mmis',
    flags 0x40000064, level_req 1):
      +0x00 u16 record_id        +0x02 char[30] full_name   +0x20 char[7] short_name
      +0x27 u32 flags (0x40000000=active, 0x1000=known)
      +0x2b char[41] description (empty in the shipped file)
      +0x54 u8 level_req   +0x56 u16 duration   +0x63 u8 kai_cost
    No active filter (file holds live records; save writes active-only).
    """
    out: list[Spell] = []
    for entry in walk_entries(path):
        p = entry.payload
        full_name = _cstr(p, 0x02, 30)
        if not full_name:
            continue
        out.append(Spell(
            record_id=struct.unpack_from("<H", p, 0x00)[0],
            full_name=full_name,
            short_name=_cstr(p, 0x20, 7),
            description=_cstr(p, 0x2B, 41),
            flags=struct.unpack_from("<I", p, 0x27)[0],
            level_req=p[0x54],
            duration=struct.unpack_from("<H", p, 0x56)[0],
            kai_cost=p[0x63],
        ))
    return out


# ── Class / Race (id → name) ─────────────────────────────────────────────────

@dataclass
class ClassDef:
    record_id: int
    name: str


@dataclass
class Race:
    record_id: int
    name: str


def _load_id_name(path: pathlib.Path, cls):
    """CLASSES.MD / RACES.MD share a layout (confirmed via classes_md_save
    0x004153e0 / races_md_save 0x0046ff20): on-disk record is
      +0x00 i16 record_id   +0x02 char[30] name   (+ stat-mod bytes after).
    Both filter only on the deleted bit (no active flag); the file holds live
    records, so load all."""
    out = []
    for entry in walk_entries(path):
        p = entry.payload
        name = _cstr(p, 0x02, 30)
        if not name:
            continue
        out.append(cls(record_id=struct.unpack_from("<h", p, 0x00)[0], name=name))
    return out


def load_classes(path: pathlib.Path) -> list[ClassDef]:
    return _load_id_name(path, ClassDef)


def load_races(path: pathlib.Path) -> list[Race]:
    return _load_id_name(path, Race)


# ── Player ───────────────────────────────────────────────────────────────────

@dataclass
class Player:
    name: str
    title: str
    guild: str
    location: str
    level: int
    alignment: int
    class_id: int
    race_id: int
    reputation: int
    first_seen: int
    last_seen: int
    flags: int

    @property
    def is_friend(self) -> bool:
        return bool(self.flags & 0x4000)

    @property
    def is_enemy(self) -> bool:
        return bool(self.flags & 0x8000)

    @property
    def is_active(self) -> bool:
        return _active(self.flags)


def load_players(path: pathlib.Path) -> list[Player]:
    """Parse PLAYERS.MD (the spy DB) — non-deleted records.

    Layout from players_md_save_one_record (megamud.exe 0x0046c719). That function
    writes the 0xF8=248B record via explicit EBP-relative offsets (so these are
    EXACT, not stack-reconstructed). PLAYERS.MD is KEYED BY NAME (no numeric
    record_id at +0x00 — the old parser wrongly assumed one and was shifted +2):
      +0x00 char[11] name (the key)   +0x0b char[19] title
      +0x1e char[31] guild            +0x3d char[21] location
      +0x52 u32 flags (0x4000=friend 0x8000=enemy 0x80000000=deleted)
      +0x56 i16 level   +0x58 i16 exp_rank   +0x5a i16 alignment
      +0x5c i16 class_id   +0x5e i16 race_id   +0x76 i16 reputation
      +0x78 u32 combat_rating   +0x7c i32 last_seen   +0x80 i32 first_seen
    (PLAYERS.MD is absent from the public extraction, so this is Ghidra-confirmed
    but not file-verified.)
    """
    if not path.exists():
        return []
    out: list[Player] = []
    for entry in walk_entries(path):
        rec = parse_player_record(entry.payload)
        if rec is not None and not _deleted(rec.flags):
            out.append(rec)
    return out


def parse_player_record(p: bytes) -> Player | None:
    """Parse one 0xF8 PLAYERS.MD payload (split out so it's testable without a
    file — PLAYERS.MD isn't shipped). Offsets per players_md_save_one_record."""
    name = _cstr(p, 0x00, 11)
    if not name:
        return None
    return Player(
        name=name,
        title=_cstr(p, 0x0B, 19),
        guild=_cstr(p, 0x1E, 31),
        location=_cstr(p, 0x3D, 21),
        level=struct.unpack_from("<h", p, 0x56)[0],
        alignment=struct.unpack_from("<h", p, 0x5A)[0],
        class_id=struct.unpack_from("<h", p, 0x5C)[0],
        race_id=struct.unpack_from("<h", p, 0x5E)[0],
        reputation=struct.unpack_from("<h", p, 0x76)[0],
        first_seen=struct.unpack_from("<i", p, 0x80)[0],
        last_seen=struct.unpack_from("<i", p, 0x7C)[0],
        flags=struct.unpack_from("<I", p, 0x52)[0],
    )


# ── Paths index (PATHS.MD) ───────────────────────────────────────────────────

@dataclass
class PathIndex:
    """One PATHS.MD directory entry — metadata indexing a `.MP` path-step file
    (the steps themselves are parsed by mmud.data.paths from the .MP files)."""
    from_desc: str    # "CODE:Region:Name" of the start room
    npc: str
    mp_file: str       # .MP filename (the cdb record key)
    to_region_name: str
    to_code: str
    flags: int


def load_paths_index(path: pathlib.Path) -> list[PathIndex]:
    """Parse the PATHS.MD index. Layout from paths_md_save (megamud.exe 0x00465860)
    + the real file; records are VARIABLE-length (cdb stores trimmed payloads), so
    short records simply yield empty trailing fields:
      +0x00 from_desc[61]  +0x3d npc[41]  +0x66 mp_file[14] (key)
      +0x74 to_region_name[31]  +0x93 to_code[14]  +0xaf u32 flags
    The .MP files are the primary path source; this index is the directory.
    """
    out: list[PathIndex] = []
    for entry in walk_entries(path):
        p = entry.payload
        from_desc = _cstr(p, 0x00, 61)
        if not from_desc:
            continue
        out.append(PathIndex(
            from_desc=from_desc,
            npc=_cstr(p, 0x3D, 41),
            mp_file=_cstr(p, 0x66, 14),
            to_region_name=_cstr(p, 0x74, 31),
            to_code=_cstr(p, 0x93, 14),
            flags=struct.unpack_from("<I", p, 0xAF)[0] if len(p) >= 0xB3 else 0,
        ))
    return out


# ── Probe utilities (kept for backward-compatibility with existing tests) ────

def extract_strings(path: pathlib.Path, min_length: int = 4) -> list[str]:
    """Extract printable ASCII strings from a binary file.

    Args:
        path: Path to binary file to read
        min_length: Minimum string length to extract (default 4)

    Returns:
        List of extracted ASCII strings
    """
    data = path.read_bytes()
    # Match sequences of printable ASCII characters (space through ~)
    pattern = re.compile(rb"[ -~]{" + str(min_length).encode() + rb",}")
    return [m.group().decode("ascii", errors="replace") for m in pattern.finditer(data)]


def probe_binary(path: pathlib.Path) -> dict:
    """Probe binary structure by analyzing string locations and gaps.

    This is an exploratory tool to understand the likely record size and structure
    of binary game database files by finding where strings are located and computing
    gaps between them.

    Args:
        path: Path to binary file to probe

    Returns:
        Dictionary containing:
        - total_bytes: File size in bytes
        - string_count: Total number of extracted strings
        - sample_strings: First 10 extracted strings
        - string_offsets: Byte offsets of first 10 string locations
        - likely_record_sizes: Most common gaps between strings (likely record boundaries)
    """
    data = path.read_bytes()
    strings = extract_strings(path, min_length=4)

    # Find byte offsets where strings appear
    offsets = []
    for s in strings[:20]:
        encoded = s.encode("ascii")
        idx = data.find(encoded)
        if idx >= 0:
            offsets.append(idx)

    # Compute gaps between string starts to guess record size
    # Sort offsets and compute differences to find patterns
    sorted_offsets = sorted(set(offsets))
    gaps = []
    for i in range(len(sorted_offsets) - 1):
        gap = sorted_offsets[i + 1] - sorted_offsets[i]
        if gap > 0:
            gaps.append(gap)

    # Count most common gap sizes (likely record boundaries)
    from collections import Counter
    gap_counts = Counter(gaps)
    most_common_gaps = sorted(gap_counts.items(), key=lambda x: x[1], reverse=True)
    likely_record_sizes = [gap for gap, count in most_common_gaps[:5]]

    return {
        "total_bytes": len(data),
        "string_count": len(strings),
        "sample_strings": strings[:10],
        "string_offsets": sorted(offsets)[:10],
        "likely_record_sizes": likely_record_sizes,
    }
