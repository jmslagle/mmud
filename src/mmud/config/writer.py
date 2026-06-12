"""TOML round-trip writer for MudConfig.

Loads existing TOML with tomlkit (preserving comments and unknown keys),
overwrites known scalar keys per section, replaces scalar-list fields wholesale,
rewrites dataclass-list fields (e.g. spells.bless, party.bless, schedule.events)
and the top-level ``players`` array as arrays-of-tables, then writes atomically
(temp file + os.replace, cleaning up the temp file on error).

All scalar/list classification is driven through :mod:`mmud.config.introspect`,
which resolves field types via ``get_type_hints`` (schema.py uses
``from __future__ import annotations``, so raw dataclass ``f.type`` is a string
at runtime and cannot be introspected directly).
"""

from __future__ import annotations

import dataclasses
import os
import pathlib

import tomlkit

from mmud.config import introspect
from mmud.config.schema import MudConfig


def _dataclass_list_to_aot(items: list):
    """Build a tomlkit array-of-tables from a list of dataclass instances."""
    aot = tomlkit.aot()
    for item in items:
        tbl = tomlkit.table()
        for f in dataclasses.fields(item):
            tbl[f.name] = getattr(item, f.name)
        aot.append(tbl)
    return aot


def _apply_section(table, section: str, section_obj) -> None:
    """Overwrite known keys of a section table from the live dataclass instance."""
    for fname in introspect.scalar_fields(section):
        table[fname] = getattr(section_obj, fname)
    for fname in introspect.scalar_list_fields(section):
        table[fname] = list(getattr(section_obj, fname))
    for fname, _elem in introspect.dataclass_list_fields(section):
        table[fname] = _dataclass_list_to_aot(getattr(section_obj, fname))


def _build_document(cfg: MudConfig, existing):
    doc = existing
    for name in introspect.section_dataclasses():
        if name not in doc:
            doc[name] = tomlkit.table()
        _apply_section(doc[name], name, getattr(cfg, name))
    doc["players"] = _dataclass_list_to_aot(cfg.players)
    return doc


def write_config(cfg: MudConfig, path: pathlib.Path) -> None:
    """Write ``cfg`` to ``path`` as TOML, preserving comments/unknown keys.

    Creates the file if missing. Writes atomically via a sibling temp file and
    ``os.replace``; the temp file is removed if anything fails.
    """
    if path.exists():
        existing = tomlkit.parse(path.read_text(encoding="utf-8"))
    else:
        existing = tomlkit.document()
    doc = _build_document(cfg, existing)
    text = tomlkit.dumps(doc)  # may raise BEFORE any temp file exists
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
