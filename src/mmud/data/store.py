from __future__ import annotations
import json
import os
import pathlib

STORE_VERSION = 3   # v3: corrected SPELLS/PLAYERS layouts (full binary-MD RE pass)

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

    The MDB2 binaries are merged IN by the importer (import_md); they are never
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

    # ---- live learning ----------------------------------------------------

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

    def learn_player(self, name: str, **fields) -> dict:
        """Record/merge a seen player into the spy DB (keyed by lowercased name).
        Only non-empty fields overwrite, so a who-list sighting and a later
        examine accumulate (level/rep/gang + race/class)."""
        key = name.strip().lower()
        rec = self.data["players"].get(key) or {"name": name, "origin": "learned"}
        rec["name"] = name
        for k, v in fields.items():
            if v not in (None, "", 0):
                rec[k] = v
        self.data["players"][key] = rec
        self.save()
        return rec

    def players(self) -> dict:
        return dict(self.data["players"])


# ---- MD importer (binary MDB2 sources only) -------------------------------

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


def prune_learned_resolvable(store: GameStore) -> int:
    """Drop learned (negative-id) monster records whose name now resolves to a
    REAL catalogued monster via adjective matching — e.g. a bogus "happy guardsman"
    recorded back when lookups were exact-only, which would otherwise shadow the
    real "guardsman". Returns the number removed. Self-heals an out-of-date store."""
    from mmud.data.binary import Monster
    from mmud.data.monster_db import MonsterDB
    monsters = store.data["monsters"]
    real = [_to_dataclass(Monster, r) for r in monsters.values()
            if r.get("record_id", 0) >= 0]
    db = MonsterDB(real)
    drop = []
    for key, rec in monsters.items():
        if rec.get("record_id", 0) < 0:
            m = db.find(rec.get("name", ""))
            if m is not None and m.record_id >= 0:
                drop.append(key)
    for key in drop:
        del monsters[key]
    if drop:
        store.save()
    return len(drop)


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
    prune_learned_resolvable(store)   # self-heal bogus learned adjective variants
    return report


# ---- record reconstruction (store -> dataclasses) -------------------------

def _to_dataclass(cls, rec: dict):
    names = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in rec.items() if k in names})


def store_monsters(store: GameStore) -> list:
    from mmud.data.binary import Monster
    return [_to_dataclass(Monster, r) for r in store.data["monsters"].values()]


def store_items(store: GameStore) -> list:
    from mmud.data.binary import Item
    return [_to_dataclass(Item, r) for r in store.data["items"].values()]
