from __future__ import annotations
import pathlib
from typing import Any
from mmud.config import introspect
from mmud.config.schema import MudConfig
from mmud.config.writer import write_config
from mmud.events import ConfigChanged, GameEventBus

_TRUE = {"on", "true", "1", "yes", "y"}
_FALSE = {"off", "false", "0", "no", "n"}


def _coerce(value: Any, target: type) -> Any:
    if target is bool:
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
        raise ValueError(f"cannot interpret {value!r} as bool")
    if target is int:
        return int(value)
    if target is float:
        return float(value)
    return str(value)


class ConfigService:
    """Single validated mutation path for the live MudConfig. Shared by the TUI
    settings screen, remote @set/@save verbs, and (later) the web panel."""

    def __init__(self, config: MudConfig, bus: GameEventBus,
                 path: pathlib.Path | None = None) -> None:
        self.config = config
        self._bus = bus
        self._path = path

    def patch(self, section: str, field: str, value: Any, persist: bool = False) -> Any:
        target = introspect.field_type(section, field)   # raises KeyError if unknown
        if not introspect.is_scalar_field(section, field):
            raise KeyError(f"{section}.{field} is not a scalar field")
        coerced = _coerce(value, target)
        setattr(getattr(self.config, section), field, coerced)
        if persist:
            self.save()
        self._bus.post(ConfigChanged(section=section, field=field, value=coerced))
        return coerced

    def save(self) -> None:
        if self._path is None:
            raise RuntimeError("ConfigService has no backing path; cannot save")
        write_config(self.config, self._path)
