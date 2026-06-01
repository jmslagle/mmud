from __future__ import annotations
import pathlib
from dataclasses import dataclass


@dataclass
class MessagePattern:
    name: str
    flags: int           # parsed from hex string e.g. "0010" → 16
    third_field: int
    apply_message: str
    remove_message: str = ""


def load_messages(path: pathlib.Path) -> list[MessagePattern]:
    text = path.read_text(encoding="latin-1")
    patterns: list[MessagePattern] = []
    lines = text.strip().splitlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines
        if not line:
            i += 1
            continue

        # Check if this is a header line (contains at least 2 colons)
        if line.count(":") < 2:
            i += 1
            continue

        # Parse header
        header = line.rstrip(":")
        parts = header.split(":")
        if len(parts) < 3:
            i += 1
            continue

        name = parts[0].strip()
        try:
            flags = int(parts[1].strip(), 16)
        except ValueError:
            flags = 0
        try:
            third = int(parts[2].strip())
        except ValueError:
            third = 0

        # Collect apply and remove messages
        apply_msg = ""
        remove_msg = ""

        i += 1
        msg_lines = []
        while i < len(lines):
            next_line = lines[i].strip()

            # If we hit a header line or empty line followed by header, stop
            if next_line and next_line.count(":") >= 2:
                # Check if this looks like a header
                potential_header = next_line.rstrip(":")
                potential_parts = potential_header.split(":")
                if len(potential_parts) >= 3:
                    # This is a new header, don't consume it
                    break

            if not next_line:
                # Empty line might signal end of entry
                i += 1
                # Look ahead to see if next non-empty line is a header
                j = i
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    lookahead = lines[j].strip()
                    if lookahead.count(":") >= 2:
                        potential_header = lookahead.rstrip(":")
                        potential_parts = potential_header.split(":")
                        if len(potential_parts) >= 3:
                            break
                continue

            msg_lines.append(next_line)
            i += 1

        # Assign apply_msg and remove_msg
        if len(msg_lines) > 0:
            apply_msg = msg_lines[0]
        if len(msg_lines) > 1:
            remove_msg = msg_lines[1]

        patterns.append(MessagePattern(
            name=name,
            flags=flags,
            third_field=third,
            apply_message=apply_msg,
            remove_message=remove_msg,
        ))

    return patterns
