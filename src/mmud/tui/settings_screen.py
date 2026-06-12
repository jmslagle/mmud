from __future__ import annotations
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, TabbedContent, TabPane
from mmud.config import introspect
from mmud.config.runtime import ConfigService

TABS: list[tuple[str, list[str]]] = [
    ("General", ["server", "login", "session"]),
    ("Display", ["ui"]),
    ("Combat", ["combat"]),
    ("Spells", ["spells"]),
    ("Health", ["health", "safety"]),
    ("Events", ["pvp", "commerce", "learning"]),
    ("Stealth", ["stealth", "navigation"]),
    ("Items", ["items"]),
    ("Party", ["party", "afk"]),
]


def _field_id(section: str, field: str) -> str:
    return f"field-{section}-{field}"


class SettingsScreen(ModalScreen):
    """Runtime config editor; edits route through ConfigService."""

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("ctrl+s", "save", "Save", priority=True),
    ]

    def __init__(self, service: ConfigService) -> None:
        super().__init__()
        self._svc = service

    def compose(self) -> ComposeResult:
        with TabbedContent(id="settings-tabs"):
            for title, sections in TABS:
                with TabPane(title, id=f"tab-{title.lower()}"):
                    with VerticalScroll():
                        for section in sections:
                            yield Label(f"[{section}]", classes="section-header")
                            for field in introspect.scalar_fields(section):
                                value = getattr(getattr(self._svc.config, section), field)
                                yield Label(field)
                                yield Input(value=str(value), id=_field_id(section, field))
        yield Static("", id="settings-status")
        yield Button("Save", id="settings-save", variant="primary")

    def _parse_id(self, widget_id: str) -> tuple[str, str]:
        _, section, field = widget_id.split("-", 2)
        return section, field

    def _commit_field(self, inp: Input) -> None:
        if not inp.id or not inp.id.startswith("field-"):
            return
        section, field = self._parse_id(inp.id)
        status = self.query_one("#settings-status", Static)
        try:
            self._svc.patch(section, field, inp.value)
            status.update(f"{section}.{field} = {inp.value}")
        except (ValueError, KeyError) as exc:
            status.update(f"[red]invalid {section}.{field}: {exc}[/red]")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._commit_field(event.input)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-save":
            self.action_save()

    def action_save(self) -> None:
        for inp in self.query(Input):
            self._commit_field(inp)
        status = self.query_one("#settings-status", Static)
        try:
            self._svc.save()
            status.update("[green]saved[/green]")
        except RuntimeError as exc:
            status.update(f"[red]{exc}[/red]")

    def action_close(self) -> None:
        self.dismiss()
