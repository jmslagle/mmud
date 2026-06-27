# tests/test_tui_widgets.py
import pytest
from textual.app import App, ComposeResult


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
                name="BumbleBee", alignment="Lawful", title="Sensei"
            )
        )
        await pilot.pause(0.1)
        assert widget.row_count == 1


@pytest.mark.asyncio
async def test_players_upserts_existing_row():
    app = _PlayersApp()
    async with app.run_test() as pilot:
        widget = app.query_one(PlayersPane)
        widget.post_message(PlayersPane.PlayerUpdate(name="BumbleBee", alignment="Lawful", title="Sensei"))
        await pilot.pause(0.1)
        widget.post_message(PlayersPane.PlayerUpdate(name="BumbleBee", alignment="Chaotic", title="Master"))
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


@pytest.mark.asyncio
async def test_stats_bar_shows_location():
    # The bottom-left zone displays where we are (room code/name or hash).
    app = _StatsApp()
    async with app.run_test() as pilot:
        bar = app.query_one(StatsBar)
        bar.post_message(StatsBar.SessionUpdate(key="location", value="SBNK Bank of Godfrey"))
        await pilot.pause(0.1)
        assert bar.room == "SBNK Bank of Godfrey"


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
        assert app.query_one(TerminalView) is not None
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


@pytest.mark.asyncio
async def test_typing_printable_key_routes_to_input():
    """A printable keypress while the command input is unfocused inserts into it
    (regresses the Input.insert API drift that crashed on_key)."""
    from textual.events import Key
    config = MudConfig()
    app = MegaMudApp(config=config, host="localhost", port=4000)
    async with app.run_test() as pilot:
        inp = app.query_one("#command-input", Input)
        inp.blur()
        await pilot.pause()
        app.on_key(Key(key="r", character="r"))  # must not raise TypeError
        await pilot.pause()
        assert inp.value == "r"


def _key(k, character=None):
    from textual.events import Key
    return Key(key=k, character=character)


from mmud.tui.widgets.terminal_view import TerminalView
from mmud.terminal import TerminalEmulator


class _TermApp(App):
    def compose(self) -> ComposeResult:
        yield TerminalView()


@pytest.mark.asyncio
async def test_terminal_view_renders_emulator_screen():
    app = _TermApp()
    async with app.run_test() as pilot:
        view = app.query_one(TerminalView)
        view.attach_emulator(TerminalEmulator())
        view._emulator.feed("Hello MUD!")
        view.refresh_screen()
        await pilot.pause(0.1)
        assert "Hello MUD!" in view.screen_text()


def test_terminal_view_raw_for_key_matches_game_output():
    # Char-mode key mapping is identical to the old GameOutput contract.
    view = TerminalView()
    assert view.raw_for_key(_key("a", "a")) == "a"
    assert view.raw_for_key(_key("enter")) == "\r"
    assert view.raw_for_key(_key("up")) == "\x1b[A"
    assert view.raw_for_key(_key("shift+tab")) is None
    assert view.raw_for_key(_key("ctrl+k")) is None
    assert view.raw_for_key(_key("f1")) is None


@pytest.mark.asyncio
async def test_terminal_view_grid_fills_pane_height():
    # The emulator grid should grow to the pane's height (not a fixed 24) so the
    # game text fills the whole box and the full-screen editor never scrolls off
    # the top. Columns stay 80 (the width the NAWS-declined server formats for).
    app = _TermApp()
    async with app.run_test(size=(100, 50)) as pilot:
        view = app.query_one(TerminalView)
        await pilot.pause(0.1)
        assert view._emulator.lines == view.content_size.height
        assert view._emulator.lines > 24
        assert view._emulator.columns == 80


@pytest.mark.asyncio
async def test_terminal_grid_stable_across_focus_in_app():
    # The focus highlight must be an always-present border (recoloured on focus),
    # NOT an overlay outline (which occluded column 0) and NOT a focus-only border
    # (which would resize the grid mid-edit). So focusing leaves the grid size and
    # the content origin unchanged.
    app = MegaMudApp(config=MudConfig(), host="h", port=23)
    async with app.run_test(size=(120, 50)) as pilot:
        view = app.query_one(TerminalView)
        await pilot.pause(0.1)
        before = view._emulator.lines
        assert before > 24                      # grid filled the pane
        view.focus()
        await pilot.pause(0.1)
        assert view._emulator.lines == before   # focusing did NOT resize the grid


@pytest.mark.asyncio
async def test_terminal_view_mouse_wheel_scrolls_history():
    app = _TermApp()
    async with app.run_test(size=(100, 50)) as pilot:
        view = app.query_one(TerminalView)
        await pilot.pause(0.1)
        calls = []
        view._emulator.prev_page = lambda: calls.append("up")
        view._emulator.next_page = lambda: calls.append("down")
        view.on_mouse_scroll_up(_FakeStop())
        view.on_mouse_scroll_down(_FakeStop())
        assert calls == ["up", "down"]


class _FakeStop:
    def stop(self): pass
    def prevent_default(self): pass


@pytest.mark.asyncio
async def test_terminal_view_char_mode_sends_raw():
    class _StubConn:
        def __init__(self): self.raw = []
        async def send_raw(self, data): self.raw.append(data)

    class _StubBot:
        def __init__(self): self._conn = _StubConn()

    config = MudConfig()
    app = MegaMudApp(config=config, host="localhost", port=4000)
    async with app.run_test() as pilot:
        app._bot = _StubBot()
        view = app.query_one(TerminalView)
        view.focus()
        await pilot.pause()
        assert view.has_focus
        await pilot.press("a", "enter", "up")
        await pilot.pause()
        assert app._bot._conn.raw == ["a", "\r", "\x1b[A"]
        assert app.query_one("#command-input", Input).value == ""


@pytest.mark.asyncio
async def test_app_screen_updated_rerenders_terminal():
    config = MudConfig()
    app = MegaMudApp(config=config, host="localhost", port=4000)
    async with app.run_test() as pilot:
        view = app.query_one(TerminalView)
        view._emulator.feed("ALIVE")
        app._bus.post(__import__("mmud.events", fromlist=["ScreenUpdated"]).ScreenUpdated())
        await pilot.pause(0.1)
        assert "ALIVE" in view.screen_text()


@pytest.mark.asyncio
async def test_tab_from_command_line_focuses_terminal_view():
    config = MudConfig()
    app = MegaMudApp(config=config, host="localhost", port=4000)
    async with app.run_test() as pilot:
        app.query_one("#command-input", Input).focus()
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert app.query_one(TerminalView).has_focus


@pytest.mark.asyncio
async def test_ctrl_q_quits_even_in_char_mode():
    # Live pain: a stalled bot left the user unable to quit (no Ctrl-Q binding) so
    # they had to kill the process. Ctrl-Q must quit, and as a priority binding it
    # must work even when the TerminalView holds focus (character mode).
    app = MegaMudApp(config=MudConfig(), host="h", port=23)
    async with app.run_test() as pilot:
        called = []
        app.exit = lambda *a, **k: called.append(True)
        app.query_one(TerminalView).focus()
        await pilot.pause()
        await pilot.press("ctrl+q")
        await pilot.pause()
        assert called   # reached action_quit -> exit, despite char-mode focus


@pytest.mark.asyncio
async def test_quit_command_exits():
    # Reliable quit that doesn't depend on the Ctrl-Q keystroke reaching the app
    # (terminals can swallow Ctrl+Q/S as XON/XOFF flow control).
    app = MegaMudApp(config=MudConfig(), host="h", port=23)
    async with app.run_test() as pilot:
        called = []
        app.exit = lambda *a, **k: called.append(True)
        await app._handle_bot_command("quit")
        assert called


@pytest.mark.asyncio
async def test_ctrl_g_opens_menu_and_escape_closes():
    from mmud.tui.help_screen import HelpScreen
    app = MegaMudApp(config=MudConfig(), host="h", port=23)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)   # closed


@pytest.mark.asyncio
async def test_escape_closes_settings_screen():
    from mmud.tui.settings_screen import SettingsScreen
    app = MegaMudApp(config=MudConfig(), host="h", port=23)
    async with app.run_test() as pilot:
        app.action_open_settings()
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)   # closed


@pytest.mark.asyncio
async def test_escape_still_clears_input_on_main_screen():
    app = MegaMudApp(config=MudConfig(), host="h", port=23)
    async with app.run_test() as pilot:
        inp = app.query_one("#command-input", Input)
        inp.focus()
        inp.value = "garbage"
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert inp.value == ""


from mmud.tui.widgets.stats_pane import StatsPane


class _StatsPaneApp(App):
    def compose(self) -> ComposeResult:
        yield StatsPane(id="stats-pane")


@pytest.mark.asyncio
async def test_stats_pane_renders_without_error():
    # Regression: StatsPane must not override Textual's internal _render(); mount +
    # update + render (via pilot.pause) would crash on the name collision.
    app = _StatsPaneApp()
    async with app.run_test() as pilot:
        pane = app.query_one(StatsPane)
        pane.post_message(StatsBar.SessionUpdate(key="hit_pct", value="38%"))
        pane.post_message(StatsBar.HpUpdate(hp=46, max_hp=46))
        await pilot.pause(0.1)
        assert "Combat Accuracy" in pane.last_text
        assert "46/46" in pane.last_text
