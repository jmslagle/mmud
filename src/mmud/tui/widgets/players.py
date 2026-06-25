from __future__ import annotations
from textual.message import Message
from textual.widgets import DataTable
from textual.widgets.data_table import ColumnKey


class PlayersPane(DataTable):
    """Online player list as a sortable DataTable."""

    class PlayerUpdate(Message):
        def __init__(self, name: str, alignment: str = "", title: str = "") -> None:
            super().__init__()
            self.name = name
            self.alignment = alignment
            self.title = title

    def on_mount(self) -> None:
        self.add_columns(
            ("Name", "name"),
            ("Align", "alignment"),
            ("Title", "title"),
        )
        self.cursor_type = "row"

    def on_players_pane_player_update(self, message: PlayerUpdate) -> None:
        # Upsert: update existing row if name matches, else add new row
        for row_key in self.rows:
            if str(self.get_row(row_key)[0]) == message.name:
                self.update_cell(row_key, "alignment", message.alignment)
                self.update_cell(row_key, "title", message.title)
                return
        self.add_row(message.name, message.alignment, message.title)
