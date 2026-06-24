from __future__ import annotations
import os
import time
from datetime import datetime
from typing import Callable


class SessionLogger:
    """Append-only, human-readable session log for debugging.

    Interleaves what the server sent (RX), what the bot sent (TX), and key
    decision/state events (EVT), each timestamped, so a whole session can be
    read back from one file. Disabled (a no-op) when `path` is empty.

    Format: ``HH:MM:SS.mmm <TAG> <text>`` — greppable by tag.
    """

    def __init__(self, path: str = "", clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._clock = clock
        self._fh = None

    @property
    def enabled(self) -> bool:
        return bool(self._path)

    def _write(self, tag: str, text: str) -> None:
        if not self._path:
            return
        if self._fh is None:
            parent = os.path.dirname(self._path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._fh = open(self._path, "a", encoding="utf-8", errors="replace")
        ts = datetime.fromtimestamp(self._clock()).strftime("%H:%M:%S.%f")[:-3]
        self._fh.write(f"{ts} {tag:<3} {text}\n")
        self._fh.flush()

    def rx(self, line: str) -> None:
        self._write("RX", line.rstrip("\n"))

    def tx(self, cmd: str) -> None:
        self._write("TX", cmd)

    def event(self, message: str) -> None:
        self._write("EVT", message)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
