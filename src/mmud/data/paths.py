"""Parser for MegaMud path files (.MP) and PATHS.MD binary index."""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field


@dataclass
class PathStep:
    hex_id: str
    command: str


@dataclass
class GamePath:
    from_code: str
    from_region: str
    from_name: str
    to_code: str
    to_region: str
    to_name: str
    npc: str          # optional NPC associated with path
    steps: list[PathStep] = field(default_factory=list)
    requires: str = ""  # item needed to traverse (e.g. "wooden skiff" for a boat leg)


_BRACKET_RE = re.compile(r"\[([^\]]*)\]")


def _parse_bracket_line(line: str) -> list[str]:
    """Return list of bracketed values from a line like [A][B] or [A:B:C]."""
    return _BRACKET_RE.findall(line)


def _parse_block(lines: list[str], filename_stem: str = "") -> GamePath | None:
    """Parse one path block from its lines (already stripped of blank lines).

    Three formats exist in the wild:

    Format A – Standard point-to-point path (1010 files):
      line 0: [][NPC] or [][]           (description bracket empty or NPC name)
      line 1: [FromCode:Region:Name]
      line 2: [ToCode:Region:Name]
      line 3: summary (HexID:HexID:count:-1:0:::)
      lines 4+: HexID:flags:command

    Format B – Loop / patrol path (68 files):
      line 0: [Description][NPC]        (description is area name, not empty)
      line 1: [Code:Region:Name]        (single location; from_code == to_code)
      line 2: summary
      lines 3+: HexID:flags:command

    Format C – NPC-only, no location lines (120 files):
      line 0: [][NPC]
      line 1: summary (starts with hex chars, not '[')
      lines 2+: HexID:flags:command
      from/to codes are derived from the 8-char filename stem.
    """
    if len(lines) < 2:
        return None

    # Line 0: [][NPC], [][], or [Description][NPC]
    header_matches = _parse_bracket_line(lines[0])
    description = header_matches[0] if header_matches else ""
    npc = header_matches[1] if len(header_matches) > 1 else ""

    line1 = lines[1].strip()
    is_bracket1 = line1.startswith("[") and line1.endswith("]")

    if is_bracket1:
        # Format A or B: line 1 is a bracket location line
        loc1_inner = line1[1:-1]
        loc1_parts = loc1_inner.split(":", 2)
        if not loc1_parts:
            return None

        line2 = lines[2].strip() if len(lines) > 2 else ""
        is_bracket2 = line2.startswith("[") and line2.endswith("]")

        if is_bracket2:
            # Format A: two location lines
            if len(lines) < 4:
                return None
            loc2_inner = line2[1:-1]
            loc2_parts = loc2_inner.split(":", 2)
            from_code = loc1_parts[0].strip()
            from_region = loc1_parts[1].strip() if len(loc1_parts) > 1 else ""
            from_name = loc1_parts[2].strip() if len(loc1_parts) > 2 else ""
            to_code = loc2_parts[0].strip() if loc2_parts else ""
            to_region = loc2_parts[1].strip() if len(loc2_parts) > 1 else ""
            to_name = loc2_parts[2].strip() if len(loc2_parts) > 2 else ""
            summary = lines[3] if len(lines) > 3 else ""
            step_lines = lines[4:]
        else:
            # Format B: single location line (loop path; from == to)
            from_code = to_code = loc1_parts[0].strip()
            from_region = to_region = loc1_parts[1].strip() if len(loc1_parts) > 1 else ""
            from_name = to_name = loc1_parts[2].strip() if len(loc1_parts) > 2 else ""
            summary = line2
            step_lines = lines[3:]
    else:
        # Format C: no location lines — derive codes from filename
        stem = filename_stem.upper()
        from_code = stem[:4] if len(stem) >= 4 else stem
        to_code = stem[4:8] if len(stem) >= 8 else ""
        from_region = from_name = to_region = to_name = ""
        summary = lines[1].strip() if len(lines) > 1 else ""
        step_lines = lines[2:]
    # Summary line: from_hex:to_hex:count:-1:0:REQUIRED_ITEM:: — field 5 is the item
    # needed to traverse this path (e.g. a boat's "wooden skiff").
    summary_parts = summary.split(":")
    requires = summary_parts[5].strip() if len(summary_parts) > 5 else ""

    # Step lines: HexID:flags:command  (command may contain spaces but no extra colons)
    steps = []
    for step_line in step_lines:
        step_line = step_line.strip()
        if not step_line:
            continue
        parts = step_line.split(":", 2)  # split at most into 3 parts
        if len(parts) >= 3:
            steps.append(PathStep(hex_id=parts[0].strip(), command=parts[2].strip()))

    return GamePath(
        from_code=from_code,
        from_region=from_region,
        from_name=from_name,
        to_code=to_code,
        to_region=to_region,
        to_name=to_name,
        npc=npc,
        steps=steps,
        requires=requires,
    )


def load_mp_file(path: pathlib.Path) -> GamePath:
    """Load a single .MP file and return its GamePath."""
    lines = [l for l in path.read_text(encoding="latin-1").splitlines() if l.strip()]
    parsed = _parse_block(lines, filename_stem=path.stem)
    if parsed is None:
        raise ValueError(f"Could not parse {path}")
    return parsed


def load_paths(path: pathlib.Path) -> list[GamePath]:
    """Load all paths referenced by PATHS.MD.

    PATHS.MD is a binary index that contains references to .MP files.
    We extract the unique .MP filenames from the binary data and load each one.
    """
    data = path.read_bytes()
    parent = path.parent

    # Extract all .MP / .mp file references from the binary index
    mp_ref_re = re.compile(rb"([A-Z0-9]{8}\.[mM][pP])", re.IGNORECASE)
    seen: set[str] = set()
    result: list[GamePath] = []

    for match in mp_ref_re.finditer(data):
        ref = match.group(1).decode("ascii").upper()
        if ref in seen:
            continue
        seen.add(ref)
        mp_path = parent / ref
        if mp_path.exists():
            try:
                result.append(load_mp_file(mp_path))
            except (ValueError, UnicodeDecodeError):
                pass

    return result
