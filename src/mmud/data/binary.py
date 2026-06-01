"""Binary data probing utilities for game database files (MONSTERS.MD, ITEMS.MD, etc.)."""
from __future__ import annotations

import pathlib
import re
import struct


def extract_strings(path: pathlib.Path, min_length: int = 4) -> list[str]:
    """Extract printable ASCII strings from a binary file.

    Args:
        path: Path to binary file to read
        min_length: Minimum string length to extract (default 4)

    Returns:
        List of extracted ASCII strings
    """
    data = path.read_bytes()
    # Match sequences of printable ASCII characters (space through ~)
    pattern = re.compile(rb"[ -~]{" + str(min_length).encode() + rb",}")
    return [m.group().decode("ascii", errors="replace") for m in pattern.finditer(data)]


def probe_binary(path: pathlib.Path) -> dict:
    """Probe binary structure by analyzing string locations and gaps.

    This is an exploratory tool to understand the likely record size and structure
    of binary game database files by finding where strings are located and computing
    gaps between them.

    Args:
        path: Path to binary file to probe

    Returns:
        Dictionary containing:
        - total_bytes: File size in bytes
        - string_count: Total number of extracted strings
        - sample_strings: First 10 extracted strings
        - string_offsets: Byte offsets of first 10 string locations
        - likely_record_sizes: Most common gaps between strings (likely record boundaries)
    """
    data = path.read_bytes()
    strings = extract_strings(path, min_length=4)

    # Find byte offsets where strings appear
    offsets = []
    for s in strings[:20]:
        encoded = s.encode("ascii")
        idx = data.find(encoded)
        if idx >= 0:
            offsets.append(idx)

    # Compute gaps between string starts to guess record size
    # Sort offsets and compute differences to find patterns
    sorted_offsets = sorted(set(offsets))
    gaps = []
    for i in range(len(sorted_offsets) - 1):
        gap = sorted_offsets[i + 1] - sorted_offsets[i]
        if gap > 0:
            gaps.append(gap)

    # Count most common gap sizes (likely record boundaries)
    from collections import Counter
    gap_counts = Counter(gaps)
    most_common_gaps = sorted(gap_counts.items(), key=lambda x: x[1], reverse=True)
    likely_record_sizes = [gap for gap, count in most_common_gaps[:5]]

    return {
        "total_bytes": len(data),
        "string_count": len(strings),
        "sample_strings": strings[:10],
        "string_offsets": sorted(offsets)[:10],
        "likely_record_sizes": likely_record_sizes,
    }
