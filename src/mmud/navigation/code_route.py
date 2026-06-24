"""Route between named rooms by chaining recorded .MP paths over the room-CODE
graph — NOT the 32-bit room-hash graph.

The hash graph (RoomGraph) is unusable for BFS: ~4400 corpus rooms collapse into a
12-bit title-hash space, so a single (hash, command) edge fans out to many real
rooms (e.g. one node's 'w' reaching 5 different rooms). BFS over it invents
unwalkable shortcuts. The .MP files, by contrast, are recorded valid walks between
named rooms (from_code -> to_code); chaining them yields a real route, and the
per-step destination hash still confirms position as we go.
"""
from __future__ import annotations
from collections import defaultdict, deque
from mmud.data.paths import GamePath
from mmud.data.rooms import Room
from mmud.navigation.graph import RouteStep


def build_code_edges(paths: list[GamePath]) -> dict[str, dict[str, GamePath]]:
    """from_code -> {to_code: GamePath}. Self-loops (loops like CRY1->CRY1) are
    skipped for routing. Shorter paths win when a (from,to) pair repeats."""
    edges: dict[str, dict[str, GamePath]] = defaultdict(dict)
    for p in paths:
        fc, tc = p.from_code.upper(), p.to_code.upper()
        if fc == tc:
            continue
        cur = edges[fc].get(tc)
        if cur is None or len(p.steps) < len(cur.steps):
            edges[fc][tc] = p
    return edges


def find_code_route(from_code: str, to_code: str, paths: list[GamePath],
                    rooms: dict[str, Room]) -> list[RouteStep] | None:
    """A walkable route from `from_code` to `to_code` by chaining .MP paths, as
    RouteSteps (per-step expected destination hash). None if unreachable."""
    from_code, to_code = from_code.upper(), to_code.upper()
    edges = build_code_edges(paths)
    if from_code == to_code:
        return []
    q: deque[tuple[str, list[GamePath]]] = deque([(from_code, [])])
    seen = {from_code}
    chain: list[GamePath] | None = None
    while q:
        code, legs = q.popleft()
        if code == to_code:
            chain = legs
            break
        for nxt, path in edges.get(code, {}).items():
            if nxt not in seen:
                seen.add(nxt)
                q.append((nxt, legs + [path]))
    if chain is None:
        return None
    all_steps = [s for leg in chain for s in leg.steps]
    hexes = [s.hex_id.upper() for s in all_steps]
    dest_room = rooms.get(to_code)
    dest_hex = dest_room.hex_id.upper() if dest_room and dest_room.hex_id else ""
    steps: list[RouteStep] = []
    for i, s in enumerate(all_steps):
        nxt = hexes[i + 1] if i + 1 < len(all_steps) else dest_hex
        expect = frozenset({nxt}) if nxt else frozenset()
        steps.append(RouteStep(command=s.command, expect=expect, chosen=nxt))
    return steps
