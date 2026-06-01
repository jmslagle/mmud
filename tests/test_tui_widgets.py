# tests/test_tui_widgets.py
import pytest
from textual.app import App, ComposeResult
from mmud.tui.widgets.game_output import GameOutput


class _GameApp(App):
    def compose(self) -> ComposeResult:
        yield GameOutput()


@pytest.mark.asyncio
async def test_game_output_displays_line():
    app = _GameApp()
    async with app.run_test() as pilot:
        widget = app.query_one(GameOutput)
        widget.post_message(GameOutput.NewLine(line="Hello MUD!\r\n"))
        await pilot.pause(0.1)
        text = widget.renderable_lines_text()
        assert "Hello MUD!" in text


from mmud.tui.widgets.conversations import ConversationsPane


class _ConvoApp(App):
    def compose(self) -> ComposeResult:
        yield ConversationsPane()


@pytest.mark.asyncio
async def test_conversations_displays_tell():
    app = _ConvoApp()
    async with app.run_test() as pilot:
        widget = app.query_one(ConversationsPane)
        widget.post_message(
            ConversationsPane.NewMessage(channel="tell", sender="BumbleBee", text="hey!")
        )
        await pilot.pause(0.1)
        text = widget.renderable_lines_text()
        assert "BumbleBee" in text
        assert "hey!" in text


from mmud.tui.widgets.players import PlayersPane


class _PlayersApp(App):
    def compose(self) -> ComposeResult:
        yield PlayersPane()


@pytest.mark.asyncio
async def test_players_shows_player_row():
    app = _PlayersApp()
    async with app.run_test() as pilot:
        widget = app.query_one(PlayersPane)
        widget.post_message(
            PlayersPane.PlayerUpdate(
                name="BumbleBee", level="L5-9", rep="Neutral", gang=""
            )
        )
        await pilot.pause(0.1)
        assert widget.row_count == 1


@pytest.mark.asyncio
async def test_players_upserts_existing_row():
    app = _PlayersApp()
    async with app.run_test() as pilot:
        widget = app.query_one(PlayersPane)
        widget.post_message(PlayersPane.PlayerUpdate(name="BumbleBee", level="L5-9", rep="Neutral", gang=""))
        await pilot.pause(0.1)
        widget.post_message(PlayersPane.PlayerUpdate(name="BumbleBee", level="L10", rep="Criminal", gang="Dragons"))
        await pilot.pause(0.1)
        assert widget.row_count == 1   # still 1 row, not 2


from mmud.tui.widgets.stats_bar import StatsBar


class _StatsApp(App):
    def compose(self) -> ComposeResult:
        yield StatsBar()


@pytest.mark.asyncio
async def test_stats_bar_shows_hp():
    app = _StatsApp()
    async with app.run_test() as pilot:
        bar = app.query_one(StatsBar)
        bar.post_message(StatsBar.HpUpdate(hp=141, max_hp=216))
        await pilot.pause(0.1)
        assert bar.hp == 141
        assert bar.max_hp == 216


@pytest.mark.asyncio
async def test_stats_bar_shows_session_stat():
    app = _StatsApp()
    async with app.run_test() as pilot:
        bar = app.query_one(StatsBar)
        bar.post_message(StatsBar.SessionUpdate(key="kills", value="694"))
        await pilot.pause(0.1)
        assert bar.session["kills"] == "694"


from textual.widgets import TabPane
from mmud.tui.widgets.right_panel import RightPanel


class _PanelApp(App):
    def compose(self) -> ComposeResult:
        yield RightPanel(default_tab="conversations")


@pytest.mark.asyncio
async def test_right_panel_has_three_tabs():
    app = _PanelApp()
    async with app.run_test() as pilot:
        panel = app.query_one(RightPanel)
        # Query TabPane (not Tab) since Textual 8.x prefixes Tab widget IDs
        pane_ids = {pane.id for pane in panel.query(TabPane)}
        assert "tab-conversations" in pane_ids
        assert "tab-players" in pane_ids
        assert "tab-stats" in pane_ids


@pytest.mark.asyncio
async def test_right_panel_switch_to():
    app = _PanelApp()
    async with app.run_test() as pilot:
        panel = app.query_one(RightPanel)
        panel.switch_to("players")
        await pilot.pause(0.1)
        assert panel.active == "tab-players"


from textual.widgets import Input
from mmud.config.schema import MudConfig
from mmud.tui.app import MegaMudApp


@pytest.mark.asyncio
async def test_app_composes():
    """App mounts with all expected widgets."""
    config = MudConfig()
    app = MegaMudApp(config=config, host="localhost", port=4000)
    async with app.run_test() as pilot:
        assert app.query_one(GameOutput) is not None
        assert app.query_one(RightPanel) is not None
        assert app.query_one(StatsBar) is not None
        assert app.query_one(Input) is not None


@pytest.mark.asyncio
async def test_app_toggle_right_panel():
    config = MudConfig()
    app = MegaMudApp(config=config, host="localhost", port=4000)
    async with app.run_test() as pilot:
        panel = app.query_one("#right-panel")
        assert "hidden" not in panel.classes
        app.action_toggle_right_panel()
        assert "hidden" in panel.classes
        app.action_toggle_right_panel()
        assert "hidden" not in panel.classes


import subprocess
import sys


def test_tui_entry_point_help():
    result = subprocess.run(
        [sys.executable, "-m", "mmud.tui", "--help"],
        capture_output=True, text=True,
        cwd="/Users/jslagle/proj/mmud",
    )
    assert result.returncode == 0
    assert "--host" in result.stdout
    assert "--port" in result.stdout
    assert "--char" in result.stdout
