from __future__ import annotations
import dataclasses


def serialize_event(event: object) -> dict:
    """Convert any GameEventBus event dataclass to a JSON-ready dict with a
    stable "type" discriminator (the class name) plus every field."""
    if not dataclasses.is_dataclass(event):
        raise TypeError(f"not a dataclass event: {type(event)!r}")
    return {"type": type(event).__name__, **dataclasses.asdict(event)}
