"""Runtime patches for third-party libraries we don't control.

Textual's Linux input thread decodes stdin as STRICT UTF-8 (in
`textual.drivers.linux_driver.run_input_thread`:
`getincrementaldecoder("utf-8")()`). A stray non-UTF-8 byte on stdin — e.g. an
8-bit control or a Meta/Alt key arriving under `screen`/`tmux`, or a mouse
report — raises `UnicodeDecodeError`, kills the input thread, and crashes the app
with a traceback (observed: "'utf-8' codec can't decode byte 0x80 ..."). Terminal
input isn't guaranteed UTF-8, so a TUI must decode tolerantly rather than die.

`patch_textual_input_decoder()` swaps the strict decoder for an `errors="replace"`
one (invalid bytes become U+FFFD). Idempotent and version-guarded — a no-op if the
Textual internals it targets aren't present.
"""
from __future__ import annotations
import codecs


def patch_textual_input_decoder() -> None:
    try:
        from textual.drivers import linux_driver
    except Exception:
        return  # not on a platform with the linux driver / Textual changed
    if getattr(linux_driver, "_mmud_tolerant_decoder", False):
        return
    if getattr(linux_driver, "getincrementaldecoder", None) is None:
        return

    def tolerant_getincrementaldecoder(encoding):
        cls = codecs.getincrementaldecoder(encoding)
        # run_input_thread calls this factory with no args; force errors="replace".
        def factory(errors="replace"):
            return cls("replace")
        return factory

    linux_driver.getincrementaldecoder = tolerant_getincrementaldecoder
    linux_driver._mmud_tolerant_decoder = True
