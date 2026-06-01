from __future__ import annotations
import re
from dataclasses import dataclass, field
from mmud.data.messages import MessagePattern

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _to_regex(template: str) -> re.Pattern | None:
    if not template:
        return None
    # Escape everything, then restore placeholder captures
    escaped = re.escape(template)
    def replace(m):
        name = m.group(1)
        if name == "dmg":
            return r"(?P<dmg>\d+)"
        return rf"(?P<{name}>.+?)"
    # re.escape turns \{ into \\\{, so match on the escaped form
    pattern_str = re.sub(r"\\\{(\w+)\\\}", replace, escaped)
    try:
        return re.compile("^" + pattern_str + "$", re.IGNORECASE)
    except re.error:
        return None


@dataclass
class MatchResult:
    pattern: MessagePattern
    is_apply: bool
    captures: dict[str, str] = field(default_factory=dict)


class PatternMatcher:
    def __init__(self, patterns: list[MessagePattern]) -> None:
        self._entries: list[tuple[MessagePattern, re.Pattern | None, re.Pattern | None]] = []
        for p in patterns:
            apply_re = _to_regex(p.apply_message)
            remove_re = _to_regex(p.remove_message)
            self._entries.append((p, apply_re, remove_re))

    def match(self, line: str) -> MatchResult | None:
        line = line.strip()
        for pattern, apply_re, remove_re in self._entries:
            if apply_re:
                m = apply_re.match(line)
                if m:
                    return MatchResult(pattern=pattern, is_apply=True,
                                       captures=dict(m.groupdict()))
            if remove_re:
                m = remove_re.match(line)
                if m:
                    return MatchResult(pattern=pattern, is_apply=False,
                                       captures=dict(m.groupdict()))
        return None
