from __future__ import annotations
import re
from enum import Enum, auto


class Condition(Enum):
    POISONED = auto()
    DISEASED = auto()
    HELD = auto()        # held / paralyzed
    STUNNED = auto()
    BLIND = auto()
    CONFUSED = auto()


# Server wording varies; these are broad. Tune against the live server and
# record actual lines in docs/testing-plan.md.
ONSET_PATTERNS: list[tuple[re.Pattern, Condition]] = [
    (re.compile(r"you (?:are|have been|feel) .*poison", re.IGNORECASE), Condition.POISONED),
    (re.compile(r"you (?:are|have been) diseased|you feel very ill", re.IGNORECASE), Condition.DISEASED),
    (re.compile(r"you (?:are|have been) (?:held|paralyzed)|you cannot move", re.IGNORECASE), Condition.HELD),
    (re.compile(r"you (?:are|have been) stunned|you see stars", re.IGNORECASE), Condition.STUNNED),
    (re.compile(r"you (?:are|have been|go) blind|you cannot see", re.IGNORECASE), Condition.BLIND),
    (re.compile(r"you (?:are|feel) confused|your head spins", re.IGNORECASE), Condition.CONFUSED),
]

RECOVERY_PATTERNS: list[tuple[re.Pattern, Condition]] = [
    (re.compile(r"poison has worn off|poison leaves? your", re.IGNORECASE), Condition.POISONED),
    (re.compile(r"you feel healthy again|disease has been cured", re.IGNORECASE), Condition.DISEASED),
    (re.compile(r"you can move again|no longer (?:held|paralyzed)", re.IGNORECASE), Condition.HELD),
    (re.compile(r"no longer stunned|your head clears", re.IGNORECASE), Condition.STUNNED),
    (re.compile(r"you can see again|your (?:sight|vision) returns", re.IGNORECASE), Condition.BLIND),
    (re.compile(r"no longer confused|your mind clears", re.IGNORECASE), Condition.CONFUSED),
]


def scan_onset(line: str) -> Condition | None:
    for pattern, condition in ONSET_PATTERNS:
        if pattern.search(line):
            return condition
    return None


def scan_recovery(line: str) -> Condition | None:
    for pattern, condition in RECOVERY_PATTERNS:
        if pattern.search(line):
            return condition
    return None
