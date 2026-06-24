from __future__ import annotations
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import TabbedContent, TabPane
from mmud.tui.widgets.conversations import ConversationsPane
from mmud.tui.widgets.players import PlayersPane
from mmud.tui.widgets.stats_pane import StatsPane


class RightPanel(Widget):
    """Tabbed right panel: Conversations | Players | Stats."""

    DEFAULT_CSS = """
    RightPanel {
        width: 1fr;
        height: 1fr;
    }
    RightPanel TabbedContent {
        width: 1fr;
        height: 1fr;
    }
    """

    def __init__(self, default_tab: str = "conversations", **kwargs) -> None:
        super().__init__(**kwargs)
        self._default_tab = default_tab

    def compose(self) -> ComposeResult:
        with TabbedContent(id="right-tabs", initial=f"tab-{self._default_tab}"):
            with TabPane("Conversations", id="tab-conversations"):
                yield ConversationsPane(id="conversations")
            with TabPane("Players", id="tab-players"):
                yield PlayersPane(id="players")
            with TabPane("Stats", id="tab-stats"):
                yield StatsPane(id="stats-pane")

    def switch_to(self, tab: str) -> None:
        """Switch active tab: 'conversations' | 'players' | 'stats'."""
        self.query_one("#right-tabs", TabbedContent).active = f"tab-{tab}"

    @property
    def active(self) -> str:
        """Return the active tab id."""
        return self.query_one("#right-tabs", TabbedContent).active
