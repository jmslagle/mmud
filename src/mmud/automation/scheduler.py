from __future__ import annotations
import time
from typing import Callable
from mmud.commands import expand_template
from mmud.config.schema import ScheduleConfig

# Type dispatch mirrors megamud.exe scheduler_event_execute @ 0x00404cd0
# (1=Logon, 2=Logoff, 3=Relog, 4=GoTo, 5=Command, 6=LoopPath).


class Scheduler:
    """Timed events driven from the bot's 1Hz ticker.

    Injected callables keep this bot-free and unit-testable:
    send(cmd), goto(room_code), start_loop(name), relog(), logoff().
    """

    def __init__(self, config: ScheduleConfig, *,
                 send: Callable[[str], object],
                 goto: Callable[[str], object],
                 start_loop: Callable[[str], object],
                 relog: Callable[[], object],
                 logoff: Callable[[], object],
                 variables: Callable[[], dict] | None = None,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._events = [e for e in config.events if e.every_seconds > 0]
        self._send = send
        self._goto = goto
        self._start_loop = start_loop
        self._relog = relog
        self._logoff = logoff
        self._variables = variables or (lambda: {})
        start = now()
        self._next_fire = [start + e.every_seconds for e in self._events]
        self._remaining = [e.count if e.count > 0 else -1 for e in self._events]

    def tick(self, now: float) -> None:
        for i, event in enumerate(self._events):
            if self._remaining[i] == 0 or now < self._next_fire[i]:
                continue
            self._next_fire[i] = now + event.every_seconds
            if self._remaining[i] > 0:
                self._remaining[i] -= 1
            self._fire(event)

    def pending(self, now: float) -> list[tuple[str, float]]:
        """(description, seconds_until) per live event — for @events."""
        return [(f"{e.type} {e.arg}".strip(), max(0.0, self._next_fire[i] - now))
                for i, e in enumerate(self._events) if self._remaining[i] != 0]

    def _fire(self, event) -> None:
        kind = event.type.lower()
        if kind == "command":
            cmd = expand_template(event.arg, self._variables()).rstrip("\r")
            self._send(cmd)
        elif kind == "goto":
            self._goto(event.arg)
        elif kind == "loop":
            self._start_loop(event.arg)
        elif kind == "relog":
            self._relog()
        elif kind == "logoff":
            self._logoff()
        # "logon" is a no-op while connected: the port's reconnect (Phase 2)
        # and relog (Phase 9) flows own the connection lifecycle.
