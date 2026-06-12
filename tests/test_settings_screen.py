import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from mmud.config.schema import MudConfig
from mmud.config.runtime import ConfigService
from mmud.events import GameEventBus, ConfigChanged
from mmud.tui.settings_screen import SettingsScreen


class _Host(App):
    def __init__(self, svc: ConfigService) -> None:
        super().__init__()
        self._svc = svc

    def compose(self) -> ComposeResult:
        yield from ()

    async def on_mount(self) -> None:
        await self.push_screen(SettingsScreen(self._svc))


def _service():
    bus = GameEventBus()
    seen = []
    bus.subscribe(ConfigChanged, seen.append)
    return ConfigService(MudConfig(), bus=bus, path=None), seen


@pytest.mark.asyncio
async def test_editing_field_patches_config():
    svc, seen = _service()
    app = _Host(svc)
    async with app.run_test() as pilot:
        inp = app.screen.query_one("#field-combat-attack_cmd", Input)
        inp.value = "bash"
        await pilot.pause()
        app.screen._commit_field(inp)
        await pilot.pause()
    assert svc.config.combat.attack_cmd == "bash"
    assert any(e.section == "combat" and e.field == "attack_cmd" for e in seen)


@pytest.mark.asyncio
async def test_invalid_value_does_not_crash():
    svc, _ = _service()
    app = _Host(svc)
    async with app.run_test() as pilot:
        inp = app.screen.query_one("#field-server-port", Input)
        inp.value = "not-a-number"
        app.screen._commit_field(inp)
        await pilot.pause()
        assert "not-a-number" not in str(svc.config.server.port)
        # textual 8.2.7 renamed Static.renderable -> Static.visual
        assert app.screen.query_one("#settings-status", Static).visual
