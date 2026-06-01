from __future__ import annotations
import pathlib
from dataclasses import dataclass


@dataclass
class Room:
    code: str        # 4-letter code e.g. "AALY"
    hex_id: str      # primary hex ID e.g. "CAB00180"
    hex_id2: str     # secondary hex ID or ""
    flags: tuple[int, int, int]
    region: str
    name: str


def load_rooms(path: pathlib.Path) -> dict[str, Room]:
    rooms: dict[str, Room] = {}
    for line in path.read_text(encoding="latin-1").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(":")
        if len(parts) >= 8:
            # Full format: HexID1:HexID2:f1:f2:f3:Code:Region:Name
            code = parts[5].strip()
            # Name can contain colons, so join parts from 7 onwards
            name = ":".join(parts[7:]).strip()
            room = Room(
                code=code,
                hex_id=parts[0].strip(),
                hex_id2=parts[1].strip(),
                flags=(int(parts[2] or 0), int(parts[3] or 0), int(parts[4] or 0)),
                region=parts[6].strip(),
                name=name,
            )
        elif len(parts) == 3:
            # Short format: Code:Region:Name
            code = parts[0].strip()
            room = Room(
                code=code,
                hex_id="",
                hex_id2="",
                flags=(0, 0, 0),
                region=parts[1].strip(),
                name=parts[2].strip(),
            )
        else:
            continue
        rooms[code] = room
    return rooms
