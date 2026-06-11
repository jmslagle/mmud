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
