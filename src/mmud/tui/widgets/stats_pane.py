from __future__ import annotations
from textual.widgets import Static
from mmud.tui.widgets.stats_bar import StatsBar


class StatsPane(Static):
    """Rich stats panel for the right-panel Stats tab — the MegaMud Player/Session
    layout (Experience, Combat Accuracy with R:/A: ranges, Other, Session). Driven
    by the same StatsBar.SessionUpdate/HpUpdate/MpUpdate messages."""

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._s: dict[str, str] = {}
        self._hp = (0, 0)
        self._mp = (0, 0)

    def on_mount(self) -> None:
        self._render()

    def on_stats_bar_hp_update(self, m: StatsBar.HpUpdate) -> None:
        self._hp = (m.hp, m.max_hp)
        self._render()

    def on_stats_bar_mp_update(self, m: StatsBar.MpUpdate) -> None:
        self._mp = (m.mp, m.max_mp)
        self._render()

    def on_stats_bar_session_update(self, m: StatsBar.SessionUpdate) -> None:
        self._s[m.key] = m.value
        self._render()

    def _render(self) -> None:
        g = self._s.get

        def acc(label: str, pct: str, rng: str = "", avg: str = "") -> str:
            return f"  {label:<6}{g(pct, '0%'):<6} {g(rng, ''):<9} {g(avg, '')}"

        lines = [
            "[b]Experience[/b]",
            f"  Exp made    {g('exp', '-')}",
            f"  Exp needed  {g('exp_needed', '-')}",
            f"  Exp rate    {g('exp_rate', '-')}",
            f"  Will level  {g('will_level_in', '-')}",
            "",
            "[b]Combat Accuracy[/b]      R:        A:",
            acc("Miss", "miss_pct"),
            acc("Hit", "hit_pct", "hit_range", "hit_avg"),
            acc("Crit", "crit_pct", "crit_range", "crit_avg"),
            acc("BS", "backstab_pct", "backstab_range", "backstab_avg"),
            acc("Cast", "cast_pct", "cast_range", "cast_avg"),
            f"  {'Round':<6}{'':<6} {g('round_range', ''):<9} {g('round_avg', '')}",
            "",
            "[b]Other[/b]",
            f"  Sneak {g('sneak_pct', '0%')}   Dodge {g('dodge_pct', '0%')}",
            f"  Kills {g('kills', '0')}   Deposited {g('deposited', '0')}   Income {g('income_rate', '-')}",
            "",
            "[b]Session[/b]",
            f"  HP {self._hp[0]}/{self._hp[1]}   MP {self._mp[0]}/{self._mp[1]}",
            f"  People seen {g('people_seen', '0')}   Attacked {g('attacked', '0')}",
            f"  Ran away {g('had_to_run', '0')}   Health low {g('health_low', '0')}",
            f"  Comms: dial {g('dialed', '0')}  conn {g('connected', '0')}  lost {g('lost_carrier', '0')}",
        ]
        self.update("\n".join(lines))
