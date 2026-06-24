from __future__ import annotations
from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import Horizontal


class StatsBar(Widget):
    """Three-zone bar: HP/MP | session info | combat accuracy."""

    DEFAULT_CSS = """
    StatsBar {
        height: 4;
        layout: horizontal;
    }
    StatsBar .zone {
        width: 1fr;
        border-right: solid $panel;
        padding: 0 1;
    }
    StatsBar .zone:last-of-type {
        border-right: none;
    }
    """

    hp: reactive[int] = reactive(0)
    max_hp: reactive[int] = reactive(0)
    mp: reactive[int] = reactive(0)
    max_mp: reactive[int] = reactive(0)

    class HpUpdate(Message):
        def __init__(self, hp: int, max_hp: int) -> None:
            super().__init__()
            self.hp = hp
            self.max_hp = max_hp

    class MpUpdate(Message):
        def __init__(self, mp: int, max_mp: int) -> None:
            super().__init__()
            self.mp = mp
            self.max_mp = max_mp

    class SessionUpdate(Message):
        def __init__(self, key: str, value: str) -> None:
            super().__init__()
            self.key = key
            self.value = value

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Horizontal(classes="zone"):
            yield Static("HP: 0/0", id="hp-label")
            yield Static("MP: 0/0", id="mp-label")
        with Horizontal(classes="zone"):
            yield Static("", id="session-label")
        with Horizontal(classes="zone"):
            yield Static("", id="combat-label")

    def on_stats_bar_hp_update(self, message: HpUpdate) -> None:
        self.hp = message.hp
        self.max_hp = message.max_hp
        self.query_one("#hp-label", Static).update(f"HP: {message.hp}/{message.max_hp}")

    def on_stats_bar_mp_update(self, message: MpUpdate) -> None:
        self.mp = message.mp
        self.max_mp = message.max_mp
        self.query_one("#mp-label", Static).update(f"MP: {message.mp}/{message.max_mp}")

    # Curated headline fields with friendly labels (no raw snake_case in the UI).
    _NAV_LABELS = {"kills": "Kills", "exp": "Exp", "exp_rate": "Exp/hr",
                   "people_seen": "Seen", "loop": "Loop", "lap": "Lap"}
    _COMBAT_LABELS = {"hit_pct": "Hit", "crit_pct": "Crit", "backstab_pct": "BS",
                      "miss_pct": "Miss", "sneak_pct": "Sneak", "dodge_pct": "Dodge"}

    def on_stats_bar_session_update(self, message: SessionUpdate) -> None:
        self.session[message.key] = message.value
        nav_parts = [f"{lbl} {self.session[k]}"
                     for k, lbl in self._NAV_LABELS.items() if k in self.session]
        combat_parts = [f"{lbl} {self.session[k]}"
                        for k, lbl in self._COMBAT_LABELS.items() if k in self.session]
        self.query_one("#session-label", Static).update("  ".join(nav_parts))
        if combat_parts:
            self.query_one("#combat-label", Static).update("  ".join(combat_parts))
