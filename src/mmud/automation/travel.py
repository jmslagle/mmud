from __future__ import annotations
import re
from mmud.config.schema import CombatConfig, ItemsConfig, StealthConfig
from mmud.combat.combat import attackable_sightings
from mmud.events import GameEventBus, TravelResynced, TravelEnded
from mmud.navigation.graph import RouteStep
from mmud.state.game_state import GameState

_ANNOTATION_RE = re.compile(r"^(.*?)\[(.*)\]$")
_MAX_RETRIES = 2


def expand_annotated(command: str) -> list[str]:
    """'w[search w]' -> ['search w', 'w'] (run the bracketed prep, then move).
    'e[]' -> ['e'] — an EMPTY annotation is just a bare move; the brackets must be
    stripped, not sent literally (the live 'e[]' door-room bug). Plain commands pass
    through."""
    m = _ANNOTATION_RE.match(command.strip())
    if m and m.group(1).strip():
        move = m.group(1).strip()
        inner = m.group(2).strip()
        return [inner, move] if inner else [move]
    return [command.strip()]


class TravelDecider:
    """PRIO_TRAVEL slot: execute a Route one step per arrival, with resync.

    Replaces bulk-enqueue path following. The bot feeds arrival signals
    (exits lines) via on_arrival() and movement failures via on_move_failed().
    """

    def __init__(self, items: ItemsConfig, stealth: StealthConfig,
                 bus: GameEventBus, combat: CombatConfig | None = None) -> None:
        self._items = items
        self._stealth = stealth
        self._bus = bus
        # For the "engage OR move" gate: hold travel while an attackable monster is here.
        self._attack_neutral = (combat or CombatConfig()).attack_neutral
        self._steps: list[RouteStep] = []
        self._cursor = 0
        self._in_flight = False
        self._retries = 0
        self._loop = False
        self._loop_from = 0
        self._from_hex = ""   # hex we issued the in-flight move FROM
        self._from_seen: set[str] = set()  # candidate hashes of the room we left
        self._redisplay_ignored = False   # one-shot departure-re-display guard
        self._wander_targets: set[str] | None = None   # hexes that end wandering
        self._on_reach = None                          # callback(hex) when reached
        self._on_giveup = None                         # callback() when wander limit hit
        self._wander_limit = 0                         # max wander moves (0 = unbounded)
        self._wander_moves = 0
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

    @property
    def wandering(self) -> bool:
        return self._wander_targets is not None

    @property
    def in_approach(self) -> bool:
        """Following the one-time lead-in to a loop's start (before the loop body)."""
        return bool(self._steps) and self._loop and self._cursor < self._loop_from

    @property
    def loop_step(self) -> tuple[int, int]:
        """(1-based position, total) within the loop body, or (0, 0) if not in it.
        e.g. (35, 68) = on step 35 of a 68-step loop."""
        if not self._loop or not self._steps:
            return (0, 0)
        total = len(self._steps) - self._loop_from
        pos = self._cursor - self._loop_from
        if total <= 0 or pos < 0:
            return (0, 0)
        return (pos + 1, total)

    @property
    def step(self) -> tuple[int, int]:
        """(1-based cursor position, total) over the WHOLE active route — for any
        route, not just loops. (0, 0) when no route is armed."""
        if not self._steps:
            return (0, 0)
        return (min(self._cursor + 1, len(self._steps)), len(self._steps))

    @property
    def current(self) -> RouteStep | None:
        """The step about to be executed (the cursor's step), or None."""
        if self._steps and 0 <= self._cursor < len(self._steps):
            return self._steps[self._cursor]
        return None

    def set_wander(self, targets: set[str], on_reach, limit: int = 0,
                   on_giveup=None) -> None:
        """Enter wander mode: pick an exit each arrival until the room's hash is in
        `targets`, then call on_reach(hex) (which typically arms the real route).
        Used to recover an unknown start position — MegaMud wanders onto its loop.
        `limit` caps the number of wander moves; on exceeding it `on_giveup()` fires
        and wandering stops (so a lost bot doesn't wander a colliding maze forever)."""
        self._steps = []
        self._cursor = 0
        self._in_flight = False
        self._retries = 0
        self._wander_targets = {h.upper() for h in targets if h}
        self._on_reach = on_reach
        self._on_giveup = on_giveup
        self._wander_limit = limit
        self._wander_moves = 0
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
        # Arming a route cancels any active wander (decide() checks wander first, so a
        # leftover wander would otherwise shadow the new route).
        self._wander_targets = None
        self._on_reach = None
        self._on_giveup = None

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
        if self._wander_limit and self._wander_moves >= self._wander_limit:
            # Wandered the limit without relocating -> give up (don't loop a
            # hash-colliding maze like the graveyard forever).
            cb = self._on_giveup
            self._wander_targets = None
            self._on_reach = None
            self._on_giveup = None
            if cb:
                cb()
            return None
        exits = list(state.last_exits or [])
        if not exits:
            return None
        rev = self._REVERSE.get(self._last_dir)   # don't immediately backtrack
        choice = next((e for e in exits if e != rev), exits[0])
        self._last_dir = choice
        self._from_hex = (state.current_hex or "").upper()
        self._in_flight = True
        self._wander_moves += 1
        return choice

    def decide(self, state: GameState) -> str | None:
        # Hold for combat: MegaMud's combat_engage_or_move_decide engages OR moves, never
        # both. While an attackable monster is present, don't travel — the higher-priority
        # combat/spell slots fight it; once the room clears, travel resumes. (Without this
        # the bot wandered off mid-fight at the cast->melee switch, once the CASTING task
        # stopped pinning travel.) Neutral NPCs/guards (kill-type 2) are not attackable,
        # so the bot still walks past them. EXCEPTION: in "run" mode (combat toggled off)
        # we quick-move THROUGH monster rooms instead of stopping to fight.
        if getattr(state, "combat_enabled", True) and attackable_sightings(
                state, self._attack_neutral):
            return None
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
        self._from_seen = {h.upper() for h in getattr(state, "last_room_hexes", ()) if h}
        self._redisplay_ignored = False
        self._in_flight = True
        return cmds[0]

    # ---- signals from the bot -------------------------------------------------

    def on_arrival(self, state: GameState, seen="", confident_hex: str = "") -> None:
        """`seen` is the SET of candidate room hashes computed from the arrived
        room's display (room title x exits). We match it against the corpus-recorded
        destinations (step.expect / step.chosen are .MP hashes), which is how we
        place ourselves even in rooms absent from ROOMS.MD. A bare hex string is
        accepted too (tests/back-compat).

        `confident_hex` is the hex of a room the bot NAME-DETECTED in ROOMS.MD (high
        confidence, not a colliding computed hash). When set, we resync to the
        matching route waypoint even if it's far ahead — that recovers when the
        recorded path takes a detour the live map doesn't have (e.g. a phantom
        Silver St loop before Town Square on Temple->WALT)."""
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
                self._on_giveup = None
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
        is_redisplay = bool(seen_hexes) and not on_track and (
            self._from_hex in seen_hexes or bool(seen_hexes & self._from_seen))
        if is_redisplay and not self._redisplay_ignored:
            # The room we're leaving re-displayed (e.g. the sneak prefix or an idle
            # refresh racing the move). Recognise it by the departure room's hash SET
            # (`_from_seen`), not just `current_hex` — at route start current_hex is
            # often stale, so the old from_hex-only check missed the re-display and
            # optimistic advance desynced the whole route by one (goto stuck after a
            # premature turn). Ignore ONCE; if it persists, the move really resolved
            # (often to a hash-COLLIDING room) so we advance rather than deadlock.
            self._redisplay_ignored = True
            return
        self._in_flight = False
        self._retries = 0
        if on_track:                                   # arrived as planned
            state.current_hex = next(iter(on_track))
            self._cursor += 1
            self._finish_if_done()
            return
        # Confident (name-detected) waypoint: resync to the matching step even far
        # ahead, FORWARD ONLY. This is a reliable position (a ROOMS.MD name match,
        # not a colliding hash), so it can safely skip a phantom detour the recorded
        # path has but the live map doesn't. Forward-only keeps the loop-30->3 guard.
        ch = confident_hex.upper() if confident_hex else ""
        if ch:
            for idx in range(self._cursor, len(self._steps)):
                if ch in self._steps[idx].expect:
                    if idx != self._cursor:
                        self._bus.post(TravelResynced(from_step=self._cursor + 1,
                                                      to_step=idx + 1))
                    state.current_hex = ch
                    self._cursor = idx + 1
                    self._finish_if_done()
                    return
        # No CONFIDENT placement: advance exactly one step (follow the command).
        # We deliberately do NOT hash-resync to a nearby step here — room hashes
        # collide heavily (runs of identical rooms: Temple St, the cemetery), so a
        # later step's dest hash routinely shows up in an earlier room's candidate
        # set, and jumping on it desynced the cursor and turned the route early into
        # a dead end ("lost in chains"). Re-anchoring is reserved for confidently
        # name-detected rooms (handled above). Trust the move worked and advance via
        # the planned destination; a real dead-end surfaces as a nav failure ("no
        # exit") -> on_move_failed -> blocked, so we don't loop forever.
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
