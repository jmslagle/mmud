from __future__ import annotations
import asyncio
import pathlib
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Input

from mmud.bot import MudBot
from mmud.config.schema import MudConfig
from mmud.events import (
    GameEventBus, LineReceived, HpChanged, MpChanged,
    ConversationReceived, PlayerSeen, SessionStatUpdated,
)
from mmud.tui.widgets.conversations import ConversationsPane
from mmud.tui.widgets.game_output import GameOutput
from mmud.tui.widgets.players import PlayersPane
from mmud.tui.widgets.right_panel import RightPanel
from mmud.tui.widgets.stats_bar import StatsBar


class MegaMudApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "MegaMud TUI"

    BINDINGS = [
        Binding("ctrl+r", "toggle_right_panel", "Toggle Panel", show=False),
        Binding("ctrl+b", "toggle_stats_bar", "Toggle Stats", show=False),
        Binding("ctrl+1", "switch_tab_conversations", "Conversations", show=False),
        Binding("ctrl+2", "switch_tab_players", "Players", show=False),
        Binding("ctrl+3", "switch_tab_stats", "Stats", show=False),
        Binding("ctrl+k", "toggle_connect", "Connect", show=False),
        Binding("ctrl+l", "toggle_loop", "Loop", show=False),
        Binding("escape", "clear_input", "Clear", show=False),
    ]

    def __init__(self, config: MudConfig, host: str, port: int) -> None:
        super().__init__()
        self._config = config
        self._host = host
        self._port = port
        self._bus = GameEventBus()
        self._bot: MudBot | None = None
        self._bot_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-area"):
            yield GameOutput(id="game-output", highlight=True, markup=True)
            yield RightPanel(
                default_tab=self._config.ui.default_tab,
                id="right-panel",
            )
        yield StatsBar(id="stats-bar")
        yield Input(placeholder="Enter command...", id="command-input")

    async def on_mount(self) -> None:
        self.sub_title = f"{self._host}:{self._port}"
        if not self._config.ui.show_right_panel:
            self.query_one("#right-panel").add_class("hidden")
        if not self._config.ui.show_stats_bar:
            self.query_one("#stats-bar").add_class("hidden")
        self._wire_bus()

    def _wire_bus(self) -> None:
        game_out = self.query_one(GameOutput)
        stats = self.query_one("#stats-bar", StatsBar)

        self._bus.subscribe(
            LineReceived,
            lambda e: game_out.post_message(GameOutput.NewLine(line=e.line)),
        )
        self._bus.subscribe(
            HpChanged,
            lambda e: stats.post_message(StatsBar.HpUpdate(hp=e.hp, max_hp=e.max_hp)),
        )
        self._bus.subscribe(
            MpChanged,
            lambda e: stats.post_message(StatsBar.MpUpdate(mp=e.mp, max_mp=e.max_mp)),
        )
        # Defer nested widget queries to event-fire time — widgets inside
        # RightPanel's TabbedContent may not be mounted yet during on_mount.
        self._bus.subscribe(
            ConversationReceived,
            lambda e: self.query_one("#conversations", ConversationsPane).post_message(
                ConversationsPane.NewMessage(channel=e.channel, sender=e.sender, text=e.text)
            ),
        )
        self._bus.subscribe(
            PlayerSeen,
            lambda e: self.query_one("#players", PlayersPane).post_message(
                PlayersPane.PlayerUpdate(name=e.name, level=e.level, rep=e.rep, gang=e.gang)
            ),
        )
        self._bus.subscribe(
            SessionStatUpdated,
            lambda e: stats.post_message(StatsBar.SessionUpdate(key=e.key, value=e.value)),
        )

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        event.input.clear()
        if cmd and self._bot is not None:
            await self._bot._conn.send(cmd)

    def action_toggle_right_panel(self) -> None:
        panel = self.query_one("#right-panel")
        panel.toggle_class("hidden")
        self._config.ui.show_right_panel = "hidden" not in panel.classes

    def action_toggle_stats_bar(self) -> None:
        bar = self.query_one("#stats-bar")
        bar.toggle_class("hidden")
        self._config.ui.show_stats_bar = "hidden" not in bar.classes

    def action_switch_tab_conversations(self) -> None:
        self.query_one(RightPanel).switch_to("conversations")

    def action_switch_tab_players(self) -> None:
        self.query_one(RightPanel).switch_to("players")

    def action_switch_tab_stats(self) -> None:
        self.query_one(RightPanel).switch_to("stats")

    async def action_toggle_connect(self) -> None:
        if self._bot_task is None or self._bot_task.done():
            data_dir = pathlib.Path("extractions/mm103s.exe.extracted/45DAD/Default")
            self._bot = MudBot(
                self._host,
                self._port,
                data_dir=data_dir if data_dir.exists() else None,
                event_bus=self._bus,
            )
            self._bot_task = asyncio.create_task(self._bot.run())
            self.sub_title = f"{self._host}:{self._port} [connected]"
        else:
            self._bot_task.cancel()
            self._bot_task = None
            self.sub_title = f"{self._host}:{self._port}"

    def action_toggle_loop(self) -> None:
        if self._bot is not None:
            self._bot.toggle_loop()
            running = self._bot._loop_runner is not None and self._bot._loop_runner.running
            self.sub_title = (
                f"{self._host}:{self._port} [looping]" if running
                else f"{self._host}:{self._port} [connected]"
            )

    def action_clear_input(self) -> None:
        self.query_one("#command-input", Input).clear()
