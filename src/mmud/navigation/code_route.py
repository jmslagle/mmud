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
import heapq
from collections import defaultdict
from itertools import count
from mmud.data.paths import GamePath
from mmud.data.rooms import Room
from mmud.navigation.graph import RouteStep


# Interchangeable water transport — MegaMud's inventory_item_find_by_name treats these
# as equivalent for a boat-gated leg.
_BOAT_EQUIV = frozenset({"wooden skiff", "log raft", "silverbark canoe"})


def _norm_item(s: str) -> str:
    """Normalise an item name to MegaMud's comparison form: lowercase (it compares
    case-sensitively but server/PATHS data are lowercase), strip apostrophes and a
    trailing '*' marker, collapse whitespace."""
    s = s.lower().replace("'", "").strip().rstrip("*").strip()
    return " ".join(s.split())


def _names_match(a: str, b: str) -> bool:
    """Mirror item_name_match @0x442080: exact compare after apostrophe-stripping, with
    trailing-'s' plural tolerance. NOT substring."""
    return a == b or a == b + "s" or b == a + "s"


def _item_held(requires: str, held: set[str]) -> bool:
    """True if a leg's required item is satisfied by something the bot holds. `held` is
    a set of already-normalised item names. Empty/'none' requirement => always true."""
    req = _norm_item(requires)
    if not req or req == "none":
        return True
    candidates = _BOAT_EQUIV if req in _BOAT_EQUIV else {req}
    return any(_names_match(c, h) for c in candidates for h in held)


def build_code_edges(paths: list[GamePath],
                     held_items=None) -> dict[str, dict[str, GamePath]]:
    """from_code -> {to_code: GamePath}. Self-loops (loops like CRY1->CRY1) are
    skipped for routing. Shorter paths win when a (from,to) pair repeats.

    Item-gated legs (a boat needs a "wooden skiff", a descent needs a "rope and
    grapple") are EXCLUDED unless the required item is in `held_items` — we don't
    model fetching transport items, and crossing water without one drowns the bot.
    But a leg whose item the bot already carries is perfectly walkable, and is often
    the ONLY way into an area (the rope-and-grapple drop into the Cave Worm Area), so
    excluding it unconditionally would make that area unreachable."""
    held = {_norm_item(x) for x in (held_items or [])}
    edges: dict[str, dict[str, GamePath]] = defaultdict(dict)
    for p in paths:
        fc, tc = p.from_code.upper(), p.to_code.upper()
        if fc == tc:
            continue
        if p.requires and not _item_held(p.requires, held):
            continue
        cur = edges[fc].get(tc)
        if cur is None or len(p.steps) < len(cur.steps):
            edges[fc][tc] = p
    return edges


def _route_chain(from_code: str, to_code: str,
                 edges: dict[str, dict[str, GamePath]]) -> list[GamePath] | None:
    """Dijkstra over the code graph weighted by leg STEP count — fewest actual moves,
    not fewest hops. Returns the chain of legs, or None if `to_code` is unreachable."""
    inf = float("inf")
    tie = count()                               # keeps heapq from comparing leg lists
    pq: list[tuple[int, int, str, list[GamePath]]] = [(0, next(tie), from_code, [])]
    best: dict[str, int] = {from_code: 0}
    while pq:
        cost, _, code, legs = heapq.heappop(pq)
        if code == to_code:
            return legs
        if cost > best.get(code, inf):
            continue                            # stale heap entry
        for nxt, path in edges.get(code, {}).items():
            ncost = cost + len(path.steps)
            if ncost < best.get(nxt, inf):
                best[nxt] = ncost
                heapq.heappush(pq, (ncost, next(tie), nxt, legs + [path]))
    return None


def missing_route_items(from_code: str, to_code: str, paths: list[GamePath],
                        held_items=None) -> list[str] | None:
    """Diagnose why a route is blocked. Returns:
      - []   : reachable now with the items currently held (no item gate in the way),
      - [...]: items needed (beyond those held) to make it reachable — the gates on
               the best all-items route, in order, deduped,
      - None : unreachable even with every item (genuinely no recorded path).
    Lets the bot say 'need rope and grapple' instead of wandering off, lost."""
    from_code, to_code = from_code.upper(), to_code.upper()
    if from_code == to_code:
        return []
    held = {_norm_item(x) for x in (held_items or [])}
    # Reachable with what we hold? Then nothing's missing.
    if _route_chain(from_code, to_code, build_code_edges(paths, held_items)) is not None:
        return []
    # Otherwise, route over the graph with ALL item legs allowed, but prefer the route
    # that crosses the FEWEST unheld gates (then fewest steps) — so we report only the
    # items truly required, not extras from a shorter key-shortcut the user can skip.
    all_edges: dict[str, dict[str, GamePath]] = defaultdict(dict)
    for p in paths:
        fc, tc = p.from_code.upper(), p.to_code.upper()
        if fc == tc:
            continue
        cur = all_edges[fc].get(tc)
        if cur is None or len(p.steps) < len(cur.steps):
            all_edges[fc][tc] = p
    GATE = 1_000_000                            # one gate outweighs any step count
    inf = float("inf")
    tie = count()
    pq: list[tuple[int, int, str, list[GamePath]]] = [(0, next(tie), from_code, [])]
    best: dict[str, int] = {from_code: 0}
    chain: list[GamePath] | None = None
    while pq:
        cost, _, code, legs = heapq.heappop(pq)
        if code == to_code:
            chain = legs
            break
        if cost > best.get(code, inf):
            continue
        for nxt, path in all_edges.get(code, {}).items():
            gated = bool(path.requires) and not _item_held(path.requires, held)
            ncost = cost + len(path.steps) + (GATE if gated else 0)
            if ncost < best.get(nxt, inf):
                best[nxt] = ncost
                heapq.heappush(pq, (ncost, next(tie), nxt, legs + [path]))
    if chain is None:
        return None
    need: list[str] = []
    for leg in chain:
        if leg.requires and not _item_held(leg.requires, held):
            item = leg.requires.strip().rstrip("*").strip()
            if item not in need:
                need.append(item)
    return need


def find_code_route(from_code: str, to_code: str, paths: list[GamePath],
                    rooms: dict[str, Room], held_items=None) -> list[RouteStep] | None:
    """A walkable route from `from_code` to `to_code` by chaining .MP paths, as
    RouteSteps (per-step expected destination hash). None if unreachable. Item-gated
    legs are usable only when `held_items` covers the required item (see
    build_code_edges); the route is step-weighted (fewest moves, not fewest legs)."""
    from_code, to_code = from_code.upper(), to_code.upper()
    if from_code == to_code:
        return []
    edges = build_code_edges(paths, held_items)
    chain = _route_chain(from_code, to_code, edges)
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
