from __future__ import annotations
import random
import re
from typing import Callable

# Spec decompiled from megamud.exe command_template_expand @ 0x00486690:
# "||" random alternatives; {token} substitution; ^X control escapes; ~ -> \x01.
_TOKEN_RE = re.compile(r"\{(\w+)\}")
KNOWN_TOKENS = ("userid", "pswd", "source", "target", "dmg",
                "p1", "p2", "p3", "p4", "p5")


def expand_template(template: str, variables: dict[str, str] | None = None,
                    choose: Callable[[int], int] | None = None) -> str:
    """Expand a megamud command template.

    variables: token values (missing tokens expand to ""). choose: pick the
    index among "||" alternatives (defaults to random) — inject for tests.
    """
    variables = variables or {}
    alts = template.split("||")
    if len(alts) > 1:
        picker = choose or (lambda n: random.randrange(n))
        template = alts[picker(len(alts))]

    out: list[str] = []
    i = 0
    while i < len(template):
        ch = template[i]
        if ch == "{":
            m = _TOKEN_RE.match(template, i)
            if m:
                out.append(variables.get(m.group(1), ""))
                i = m.end()
                continue
            out.append(ch)
        elif ch == "^" and i + 1 < len(template):
            nxt = template[i + 1]
            if nxt == "^":
                out.append("^")
            elif nxt == "~":
                out.append("~")
            else:
                out.append(chr(ord(nxt.upper()) - 0x40))   # ^M -> \r
            i += 2
            continue
        elif ch == "~":
            out.append("\x01")
        else:
            out.append(ch)
        i += 1
    return "".join(out)
