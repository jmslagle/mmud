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
