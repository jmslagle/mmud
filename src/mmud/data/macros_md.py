from __future__ import annotations
import pathlib
from dataclasses import dataclass

# MACROS.MD is TEXT (probed): "key_code:shift:ctrl:alt:command" lines,
# command suffix "^M" = press enter. Read directly (never imported into the
# game-DB store, per the project's text-source rule).

# Windows virtual-key codes -> terminal key names (numpad block).
_VK_KEYS = {96: "kp_0", 97: "kp_1", 98: "kp_2", 99: "kp_3", 100: "kp_4",
            101: "kp_5", 102: "kp_6", 103: "kp_7", 104: "kp_8", 105: "kp_9",
            110: "kp_decimal"}


@dataclass
class Macro:
    key_code: int
    shift: bool
    ctrl: bool
    alt: bool
    command: str
    press_enter: bool


def vk_to_key_name(vk: int) -> str | None:
    return _VK_KEYS.get(vk)


def load_macros(path: pathlib.Path) -> list[Macro]:
    if not path.exists():
        return []
    macros: list[Macro] = []
    for line in path.read_text(encoding="latin-1").splitlines():
        parts = line.strip().split(":", 4)
        if len(parts) != 5 or not parts[0].isdigit():
            continue
        command = parts[4]
        press_enter = command.endswith("^M")
        if press_enter:
            command = command[:-2]
        macros.append(Macro(
            key_code=int(parts[0]),
            shift=parts[1] == "1", ctrl=parts[2] == "1", alt=parts[3] == "1",
            command=command, press_enter=press_enter,
        ))
    return macros
