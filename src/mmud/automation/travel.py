from __future__ import annotations
import re
from mmud.config.schema import ItemsConfig, StealthConfig
from mmud.events import GameEventBus, TravelResynced, TravelEnded
from mmud.navigation.graph import RouteStep
from mmud.state.game_state import GameState

_ANNOTATION_RE = re.compile(r"^(.*?)\[(.+)\]$")
_MAX_RETRIES = 2


def expand_annotated(command: str) -> list[str]:
    """'w[search w]' -> ['search w', 'w']; plain commands pass through."""
    m = _ANNOTATION_RE.match(command.strip())
    if m and m.group(1).strip():
        return [m.group(2).strip(), m.group(1).strip()]
    return [command.strip()]


class TravelDecider:
    """PRIO_TRAVEL slot: execute a Route one step per arrival, with resync.

    Replaces bulk-enqueue path following. The bot feeds arrival signals
    (exits lines) via on_arrival() and movement failures via on_move_failed().
    """

    def __init__(self, items: ItemsConfig, stealth: StealthConfig,
                 bus: GameEventBus) -> None:
        self._items = items
        self._stealth = stealth
        self._bus = bus
        self._steps: list[RouteStep] = []
        self._cursor = 0
        self._in_flight = False
        self._retries = 0
        self._loop = False
        self._loop_from = 0
        self._from_hex = ""   # hex we issued the in-flight move FROM
        self._redisplay_ignored = False   # one-shot departure-re-display guard
        self._wander_targets: set[str] | None = None   # hexes that end wandering
        self._on_reach = None                          # callback(hex) when reached
        self._last_dir = ""                            # last wander move (avoid U-turn)
        self.lap = 0

    _REVERSE = {"n": "s", "s": "n", "e": "w", "w": "e", "ne": "sw", "sw": "ne",
                "nw": "se", "se": "nw", "u": "d", "d": "u"}

    # ---- route control ------------------------------------------------------

    @property
    def active(self) -> bool:
        return bool(self._steps) or self._wander_targets is not None

    @property
    def route(self) -> list[RouteStep]:
        return list(self._steps)

    def set_wander(self, targets: set[str], on_reach) -> None:
        """Enter wander mode: pick an exit each arrival until the room's hash is in
        `targets`, then call on_reach(hex) (which typically arms the real route).
        Used to recover an unknown start position — MegaMud wanders onto its loop."""
        self._steps = []
        self._cursor = 0
        self._in_flight = False
        self._retries = 0
        self._wander_targets = {h.upper() for h in targets if h}
        self._on_reach = on_reach
        self._last_dir = ""

    def set_route(self, steps: list[RouteStep], loop: bool = False,
                  loop_from: int = 0, start_at: int = 0) -> None:
        """Arm a route. When `loop`, a completed lap restarts at `loop_from`
        (not 0) — so a one-time approach prefix [0:loop_from] isn't replayed.
        `start_at` begins the FIRST pass partway in (resuming a loop already in
        progress); subsequent laps still restart at `loop_from`."""
        self._steps = list(steps)
        self._cursor = start_at
        self._in_flight = False
        self._retries = 0
        self._loop = loop
        self._loop_from = loop_from
        self.lap = 0

    def clear(self, reason: str = "stopped") -> None:
        if self._steps or self._wander_targets is not None:
            self._bus.post(TravelEnded(reason=reason))
        self._steps = []
        self._wander_targets = None
        self._on_reach = None
        self._in_flight = False

    # ---- decider ------------------------------------------------------------

    def _decide_wander(self, state: GameState) -> str | None:
        if self._in_flight:
            return None
        exits = list(state.last_exits or [])
        if not exits:
            return None
        rev = self._REVERSE.get(self._last_dir)   # don't immediately backtrack
        choice = next((e for e in exits if e != rev), exits[0])
        self._last_dir = choice
        self._from_hex = (state.current_hex or "").upper()
        self._in_flight = True
        return choice

    def decide(self, state: GameState) -> str | None:
        if self._wander_targets is not None:
            return self._decide_wander(state)
        if not self._steps or self._in_flight:
            return None
        level = state.inventory.encumbrance_level
        if ((self._items.dont_go_heavy and level == "heavy")
                or (self._items.dont_go_medium and level in ("medium", "heavy"))):
            return None
        step = self._steps[self._cursor]
        cmds = expand_annotated(step.command)
        if self._stealth.auto_sneak:
            cmds = ["sneak"] + cmds   # MegaMud hardcodes the sneak verb (ref §3)
        for extra in cmds[1:]:
            state.enqueue(extra)
        self._from_hex = (state.current_hex or "").upper()
        self._redisplay_ignored = False
        self._in_flight = True
        return cmds[0]

    # ---- signals from the bot -------------------------------------------------

    def on_arrival(self, state: GameState, seen="") -> None:
        """`seen` is the SET of candidate room hashes computed from the arrived
        room's display (room title x exits). We match it against the corpus-recorded
        destinations (step.expect / step.chosen are .MP hashes), which is how we
        place ourselves even in rooms absent from ROOMS.MD. A bare hex string is
        accepted too (tests/back-compat)."""
        if self._wander_targets is not None:
            self._in_flight = False
            seen_hexes = ({h.upper() for h in seen if h}
                          if isinstance(seen, (set, frozenset))
                          else ({seen.upper()} if seen else set()))
            hit = self._wander_targets & seen_hexes
            if hit:
                on_reach = self._on_reach
                self._wander_targets = None
                self._on_reach = None
                if on_reach:
                    on_reach(next(iter(hit)))   # arms the real route (set_route)
            return
        if not self._steps or not self._in_flight:
            return
        if isinstance(seen, (set, frozenset)):
            seen_hexes = {h.upper() for h in seen if h}
        else:
            seen_hexes = {seen.upper()} if seen else set()
        step = self._steps[self._cursor]
        on_track = step.expect & seen_hexes
        if (seen_hexes and self._from_hex in seen_hexes and not on_track
                and not self._redisplay_ignored):
            # The room we're leaving re-displayed (e.g. an idle refresh racing the
            # move). Ignore it ONCE; if it persists, the move did resolve (often to
            # a different room that hash-COLLIDES with the departure — common in the
            # graveyard where many rooms share a hash) so we must advance, not
            # deadlock waiting forever.
            self._redisplay_ignored = True
            return
        self._in_flight = False
        self._retries = 0
        if on_track:                                   # arrived as planned
            state.current_hex = next(iter(on_track))
            self._cursor += 1
            self._finish_if_done()
            return
        for idx, other in enumerate(self._steps):      # resync against any step
            hit = other.expect & seen_hexes
            if hit:
                self._bus.post(TravelResynced(from_step=self._cursor + 1,
                                              to_step=idx + 1))
                state.current_hex = next(iter(hit))
                self._cursor = idx + 1
                self._finish_if_done()
                return
        # No hash placed us on the route (only the room's description/junk lines
        # hashed, or we're genuinely off-route): trust that the move worked and
        # advance via the planned destination. A real dead-end surfaces as a nav
        # failure ("no exit") -> on_move_failed -> blocked, so we don't loop forever.
        state.current_hex = step.chosen
        self._cursor += 1
        self._finish_if_done()

    def on_move_failed(self) -> None:
        if not self._steps:
            return
        self._in_flight = False
        self._retries += 1
        if self._retries > _MAX_RETRIES:
            self.clear(reason="blocked")

    def retry_current(self) -> None:
        """A door handler cleared the obstacle: re-send the same step free."""
        self._in_flight = False
        self._retries = 0

    def _finish_if_done(self) -> None:
        if self._cursor < len(self._steps):
            return
        if self._loop:
            self._cursor = self._loop_from
            self.lap += 1
        else:
            self._bus.post(TravelEnded(reason="arrived"))
            self._steps = []
