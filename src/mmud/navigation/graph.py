from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from mmud.data.paths import GamePath
from mmud.data.rooms import Room


class NavStatus(Enum):
    OK = auto()
    UNKNOWN_START = auto()
    UNKNOWN_DEST = auto()
    NO_PATH = auto()


@dataclass
class RouteStep:
    command: str              # raw command (may carry a [bracket] annotation)
    expect: frozenset[str]    # ALL recorded destinations of (from, command)
    chosen: str               # the destination BFS planned through


@dataclass
class NavResult:
    status: NavStatus
    steps: list[RouteStep]


class RoomGraph:
    """Directed room graph over .MP hex ids. Adjacency is multi-destination:
    the corpus records the same (room, command) landing in different hexes
    (2,482 of 9,002 pairs) — arrival validation must accept any of them."""

    def __init__(self) -> None:
        self._adj: dict[str, dict[str, set[str]]] = {}

    # ---- construction ------------------------------------------------------

    def add_edge(self, from_hex: str, command: str, to_hex: str) -> None:
        a, c, b = from_hex.upper(), command.lower(), to_hex.upper()
        self._adj.setdefault(a, {}).setdefault(c, set()).add(b)
        self._adj.setdefault(b, {})   # destination is a node even if no exits

    @classmethod
    def from_paths(cls, paths: list[GamePath], rooms: dict[str, Room]) -> "RoomGraph":
        g = cls()
        for p in paths:
            hexes = [s.hex_id.upper() for s in p.steps]
            for i, step in enumerate(p.steps):
                if i + 1 < len(p.steps):
                    g.add_edge(hexes[i], step.command, hexes[i + 1])
                else:
                    # final edge: last command leads to the destination room
                    room = rooms.get(p.to_code.upper())
                    if room and room.hex_id:
                        g.add_edge(hexes[i], step.command, room.hex_id)
        return g

    def add_learned(self, exits: list[tuple[str, str, str]]) -> None:
        for from_hex, cmd, to_hex in exits:
            self.add_edge(from_hex, cmd, to_hex)

    # ---- introspection (pinned in tests) ------------------------------------

    def node_count(self) -> int:
        return len(self._adj)

    def edge_count(self) -> int:
        return sum(len(dests) for cmds in self._adj.values()
                   for dests in cmds.values())

    def multi_dest_pairs(self) -> int:
        return sum(1 for cmds in self._adj.values()
                   for dests in cmds.values() if len(dests) > 1)

    def reachable(self, start_hex: str) -> set[str]:
        start = start_hex.upper()
        if start not in self._adj:
            return set()
        seen = {start}
        frontier = deque([start])
        while frontier:
            node = frontier.popleft()
            for dests in self._adj[node].values():
                for nxt in dests:
                    if nxt not in seen:
                        seen.add(nxt)
                        frontier.append(nxt)
        return seen

    # ---- pathfinding ---------------------------------------------------------

    def find_path(self, from_hex: str, to_hex: str) -> NavResult:
        src, dst = from_hex.upper(), to_hex.upper()
        if src not in self._adj:
            return NavResult(NavStatus.UNKNOWN_START, [])
        if dst not in self._adj:
            return NavResult(NavStatus.UNKNOWN_DEST, [])
        # BFS; parent[node] = (prev_node, command)
        parent: dict[str, tuple[str, str]] = {src: ("", "")}
        frontier = deque([src])
        while frontier:
            node = frontier.popleft()
            if node == dst:
                break
            for cmd, dests in self._adj[node].items():
                for nxt in dests:
                    if nxt not in parent:
                        parent[nxt] = (node, cmd)
                        frontier.append(nxt)
        if dst not in parent:
            return NavResult(NavStatus.NO_PATH, [])
        # reconstruct
        steps: list[RouteStep] = []
        node = dst
        while node != src:
            prev, cmd = parent[node]
            steps.append(RouteStep(command=cmd,
                                   expect=frozenset(self._adj[prev][cmd]),
                                   chosen=node))
            node = prev
        steps.reverse()
        return NavResult(NavStatus.OK, steps)
