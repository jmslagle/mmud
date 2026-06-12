from __future__ import annotations
import time
from typing import Callable
from mmud.config.schema import SessionConfig


class SessionManager:
    """Session-scope tracking: capture file, exp rate, time limits.

    Pure logic with an injected clock; the bot feeds it directly
    (on_line / on_exp) and asks tick(now) for the 1Hz safety action.
    """

    def __init__(self, config: SessionConfig,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._cfg = config
        self.started_at = now()
        self._first_exp: tuple[float, int] | None = None   # (t, exp)
        self._last_exp: tuple[float, int] | None = None
        self._capture = None
        self._fired = False    # actions fire once per session
        # Comms counters (lifetime-of-process; NOT cleared on reset)
        self.dialed = 0
        self.dial_failed = 0
        self.connected = 0
        self.carrier_lost = 0

    # ---- feeds ---------------------------------------------------------------

    def on_line(self, raw: str) -> None:
        if not self._cfg.capture_file:
            return
        if self._capture is None:
            self._capture = open(self._cfg.capture_file, "a", encoding="utf-8",
                                 errors="replace")
        self._capture.write(raw if raw.endswith("\n") else raw + "\n")
        self._capture.flush()

    def on_exp(self, value: int, now: float) -> None:
        if self._first_exp is None:
            self._first_exp = (now, value)
        self._last_exp = (now, value)

    def on_dial(self) -> None:
        self.dialed += 1

    def on_dial_failed(self) -> None:
        self.dial_failed += 1

    def on_connect(self) -> None:
        self.connected += 1

    def on_carrier_lost(self) -> None:
        self.carrier_lost += 1

    # ---- queries ---------------------------------------------------------------

    def exp_rate_per_hour(self) -> float:
        if not self._first_exp or not self._last_exp:
            return 0.0
        t0, e0 = self._first_exp
        t1, e1 = self._last_exp
        if t1 <= t0:
            return 0.0
        return (e1 - e0) / ((t1 - t0) / 3600.0)

    def hours_elapsed(self, now: float) -> float:
        return (now - self.started_at) / 3600.0

    def time_to_level_hours(self, exp_to_next: int) -> float:
        rate = self.exp_rate_per_hour()
        if rate <= 0 or exp_to_next <= 0:
            return 0.0
        return exp_to_next / rate

    # ---- 1Hz decision -----------------------------------------------------------

    def tick(self, now: float) -> str | None:
        """Return "hangup" | "relog" | None. Fires at most once per session."""
        if self._fired:
            return None
        if (self._cfg.max_hours_per_day
                and self.hours_elapsed(now) >= self._cfg.max_hours_per_day):
            self._fired = True
            return "hangup"
        if (self._cfg.min_exp_rate
                and (now - self.started_at) >= self._cfg.grace_minutes * 60
                and self._first_exp and self._last_exp
                and self.exp_rate_per_hour() < self._cfg.min_exp_rate):
            self._fired = True
            return self._cfg.low_rate_action
        return None

    def reset(self, now: float) -> None:
        """New session (after relog): restart timers and samples."""
        self.started_at = now
        self._first_exp = None
        self._last_exp = None
        self._fired = False

    def close(self) -> None:
        if self._capture is not None:
            self._capture.close()
            self._capture = None
