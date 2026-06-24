from __future__ import annotations
from typing import Callable
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option


class SearchPickerScreen(ModalScreen):
    """Incremental-search picker: type to filter, Enter/click to choose. Used by
    :goto (rooms) and :loop (loop paths). `provider(query)` returns (key, label)
    pairs to show; `on_select(key)` runs when one is chosen."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    DEFAULT_CSS = """
    SearchPickerScreen { align: center middle; }
    SearchPickerScreen #picker {
        width: 70%; height: 70%;
        border: round $accent; background: $panel; padding: 1;
    }
    SearchPickerScreen OptionList { height: 1fr; }
    """

    def __init__(self, title: str,
                 provider: Callable[[str], list[tuple[str, str]]],
                 on_select: Callable[[str], None]) -> None:
        super().__init__()
        self._title = title
        self._provider = provider
        self._on_select = on_select

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Label(self._title)
            yield Input(placeholder="type to filter…", id="picker-input")
            yield OptionList(id="picker-list")

    def on_mount(self) -> None:
        self._refilter("")
        self.query_one("#picker-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._refilter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        ol = self.query_one("#picker-list", OptionList)
        if ol.option_count:
            opt = ol.get_option_at_index(ol.highlighted or 0)
            self._choose(opt.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._choose(event.option.id)

    def _refilter(self, query: str) -> None:
        ol = self.query_one("#picker-list", OptionList)
        ol.clear_options()
        for key, label in self._provider(query):
            ol.add_option(Option(label, id=key))

    def _choose(self, key: str | None) -> None:
        if key is not None:
            self._on_select(key)
        self.dismiss(key)

    def action_cancel(self) -> None:
        self.dismiss(None)
