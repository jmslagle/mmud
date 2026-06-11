"""Binary data probing and parsing utilities for game database files (MONSTERS.MD, ITEMS.MD, etc.).

The container is the "MDB2" CDB B-tree engine; its on-disk format (header, node,
and length-prefixed key layout) is documented in docs/cdb-mdb2-format.md, derived
from the decompiled cdb_* functions in megamud.exe. The summary below is the
empirical view this parser actually uses.

Format note (empirically reverse-engineered):
  Each .MD file is a paged B-tree database:
    - Bytes 0-1023: 1024-byte file header (magic 'MDB2X\\0', metadata)
    - Followed by N*1024-byte pages (N = u16 at header+20)
  Normal data pages (first 2 bytes == 0x00 0x00) hold 2 records each.
  Index pages (first byte == 0x01 or 0x02) hold B-tree index entries.
  Each record entry begins with marker byte 0x80:
    entry+0x00: u8  = 0x80 (marker)
    entry+0x01: u16 LE = record_id
    entry+0x03: char[31] name (null-padded)
    entry+0x22: u32 LE flags (0x40000000=active, 0x80000000=deleted)
    ... stats fields at higher offsets (file-format specific)
  The two entries per page are separated by 221 bytes.
  Page prefix (before entry 1) ends at: 14 + len(level_str_null_term) + 4 padding bytes.
"""
from __future__ import annotations

import pathlib
import re
import struct
from dataclasses import dataclass

# ── File-format constants ────────────────────────────────────────────────────

_PAGE_SIZE = 1024
_ENTRY_MARKER = 0x80
_FLAG_ACTIVE = 0x40000000
_FLAG_DELETED = 0x80000000
_ENTRY_SPACING = 221       # bytes between entry 1 and entry 2 within a page
_ENTRY_SPACING_ALT = 220   # rare variant (some pages)

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


def _find_entry1_offset(page: bytes) -> int:
    """Return offset of first record entry within a 1024-byte page.

    The page prefix contains 14 bytes of fixed metadata, then a
    null-terminated decimal ASCII string (level/type indicator), then
    4 null padding bytes, then the 0x80 entry marker.
    """
    null_pos = 0x0E
    while null_pos < 0x20 and page[null_pos] != 0:
        null_pos += 1
    return null_pos + 1 + 4   # past null terminator + 4 padding zeros


def _iter_page_entries(page: bytes) -> list[int]:
    """Return offsets of all valid 0x80-marked entries in a normal data page."""
    e1 = _find_entry1_offset(page)
    if e1 >= len(page) - 50 or page[e1] != _ENTRY_MARKER:
        return []
    offsets = [e1]
    # Try standard 221-byte spacing, fall back to 220
    for spacing in (_ENTRY_SPACING, _ENTRY_SPACING_ALT):
        e2 = e1 + spacing
        if e2 + 50 < len(page) and page[e2] == _ENTRY_MARKER:
            offsets.append(e2)
            break
    return offsets


def _iter_all_entries(data: bytes):
    """Yield (page_num, entry_offset_in_page, page_bytes) for every record
    entry in all normal data pages of an .MD file."""
    num_pages = len(data) // _PAGE_SIZE
    for page_num in range(1, num_pages):
        page_start = page_num * _PAGE_SIZE
        if page_start + _PAGE_SIZE > len(data):
            break
        page = data[page_start : page_start + _PAGE_SIZE]
        # Normal data page check (first 2 bytes must be 0x00 0x00)
        if page[0] != 0x00 or page[1] != 0x00:
            continue
        for eoff in _iter_page_entries(page):
            yield page_num, eoff, page


# ── Monster ──────────────────────────────────────────────────────────────────

@dataclass
class Monster:
    record_id: int
    name: str
    level: int
    exp_value: int
    combat_rating: int
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


# ── Item ─────────────────────────────────────────────────────────────────────

@dataclass
class Item:
    record_id: int
    name: str
    description: str
    suffix: str
    item_type: int
    equip_slot: int
    ac_or_dmg: int
    weight: int
    value: int
    extra_stat1: int
    extra_stat2: int
    flags: int

    @property
    def is_active(self) -> bool:
        return _active(self.flags)


def load_items(path: pathlib.Path) -> list[Item]:
    """Parse ITEMS.MD and return all active Item records.

    Payload offsets (true MDB2 walk):
      +0x00: u16 record_id   +0x02: char[31] name   +0x21: u32 flags
      +0x21+31..: description/suffix strings
      +0x5f: u8 item_type   +0x60: u8 equip_slot
      +0x63/+0x67/+0x6b: i16 ac_or_dmg / weight / value
      +0x6f/+0x73: u32 extra stats
    Numeric offsets are the old empirical ones shifted -1; they remain
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
    """Parse PLAYERS.MD and return all active Player records.

    Uses the same page-based layout as other .MD files. Within each entry:
      +0x01: u16 record_id (not stored per player — u16 is a 2-byte entry sub-header)
      +0x03: char[31] player name
    Other fields (title, guild, etc.) follow in the entry.
    Returns an empty list if the file has no active records or cannot be parsed.
    """
    if not path.exists():
        return []

    data = path.read_bytes()
    out: list[Player] = []

    for _page_num, eoff, page in _iter_all_entries(data):
        if eoff + 0x80 > len(page):
            continue

        name = _cstr(page, eoff + 0x03, 11)
        if not name:
            continue

        # Scan for flags
        flags = 0
        for foff in range(eoff + 0x22, min(eoff + 0x80, len(page) - 3), 4):
            candidate = struct.unpack_from("<I", page, foff)[0]
            if candidate & (_FLAG_ACTIVE | 0x4000 | 0x8000 | 0x200):
                flags = candidate
                break

        if _deleted(flags):
            continue

        # Text fields following the name
        title    = _cstr(page, eoff + 0x0E, 19)
        guild    = _cstr(page, eoff + 0x21, 31)
        location = _cstr(page, eoff + 0x40, 21)

        # Numeric fields (approximate offsets)
        level      = struct.unpack_from("<h", page, eoff + 0x58)[0] if eoff + 0x5A < len(page) else 0
        alignment  = struct.unpack_from("<h", page, eoff + 0x60)[0] if eoff + 0x62 < len(page) else 0
        class_id   = struct.unpack_from("<h", page, eoff + 0x64)[0] if eoff + 0x66 < len(page) else 0
        race_id    = struct.unpack_from("<h", page, eoff + 0x68)[0] if eoff + 0x6A < len(page) else 0
        reputation = struct.unpack_from("<h", page, eoff + 0x6C)[0] if eoff + 0x6E < len(page) else 0
        first_seen = struct.unpack_from("<i", page, eoff + 0x78)[0] if eoff + 0x7C < len(page) else 0
        last_seen  = struct.unpack_from("<i", page, eoff + 0x7C)[0] if eoff + 0x80 < len(page) else 0

        out.append(Player(
            name=name,
            title=title,
            guild=guild,
            location=location,
            level=level,
            alignment=alignment,
            class_id=class_id,
            race_id=race_id,
            reputation=reputation,
            first_seen=first_seen,
            last_seen=last_seen,
            flags=flags,
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
