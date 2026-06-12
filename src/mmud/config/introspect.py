from __future__ import annotations

import dataclasses
import typing

from mmud.config.schema import MudConfig

_SCALARS = (str, int, float, bool)


def section_dataclasses() -> dict[str, type]:
    """name -> dataclass type for each MudConfig field whose type is a dataclass
    (excludes 'players', which is list[PlayerRule]). Order follows MudConfig field order."""
    hints = typing.get_type_hints(MudConfig)
    out: dict[str, type] = {}
    for f in dataclasses.fields(MudConfig):
        hint = hints[f.name]
        if dataclasses.is_dataclass(hint):
            out[f.name] = hint
    return out


def section_names() -> list[str]:
    """Ordered dataclass section names + 'players' appended last."""
    return list(section_dataclasses().keys()) + ["players"]


def _section_cls(section: str) -> type:
    sections = section_dataclasses()
    if section not in sections:
        raise KeyError(section)
    return sections[section]


def field_type(section: str, field: str) -> type:
    """Resolved declared type of a field, e.g. field_type('server','port') -> int.
    Raises KeyError if section unknown OR field unknown."""
    cls = _section_cls(section)
    hints = typing.get_type_hints(cls)
    if field not in hints:
        raise KeyError(field)
    return hints[field]


def is_scalar_field(section: str, field: str) -> bool:
    """True iff the field's resolved type is one of str/int/float/bool.
    Raises KeyError for unknown section/field (same as field_type) — NOT return False."""
    return field_type(section, field) in _SCALARS


def scalar_fields(section: str) -> list[str]:
    """Ordered scalar (str/int/float/bool) field names of a section; skips list[...] fields.
    Raises KeyError for unknown section."""
    cls = _section_cls(section)
    hints = typing.get_type_hints(cls)
    return [f.name for f in dataclasses.fields(cls) if hints[f.name] in _SCALARS]


def scalar_list_fields(section: str) -> list[str]:
    """Ordered field names whose type is list[str|int|float|bool] (scalar lists)."""
    cls = _section_cls(section)
    hints = typing.get_type_hints(cls)
    out: list[str] = []
    for f in dataclasses.fields(cls):
        hint = hints[f.name]
        if typing.get_origin(hint) is list:
            args = typing.get_args(hint)
            if len(args) == 1 and args[0] in _SCALARS:
                out.append(f.name)
    return out


def dataclass_list_fields(section: str) -> list[tuple[str, type]]:
    """Ordered (field_name, element_dataclass_type) for fields typed list[<dataclass>]
    (e.g. ('bless', BlessSpell) for 'spells')."""
    cls = _section_cls(section)
    hints = typing.get_type_hints(cls)
    out: list[tuple[str, type]] = []
    for f in dataclasses.fields(cls):
        hint = hints[f.name]
        if typing.get_origin(hint) is list:
            args = typing.get_args(hint)
            if len(args) == 1 and dataclasses.is_dataclass(args[0]):
                out.append((f.name, args[0]))
    return out
