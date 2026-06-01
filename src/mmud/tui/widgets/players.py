from __future__ import annotations
from textual.message import Message
from textual.widgets import DataTable
from textual.widgets.data_table import ColumnKey


class PlayersPane(DataTable):
    """Online player list as a sortable DataTable."""

    class PlayerUpdate(Message):
        def __init__(self, name: str, level: str, rep: str, gang: str) -> None:
            super().__init__()
            self.name = name
            self.level = level
            self.rep = rep
            self.gang = gang

    def on_mount(self) -> None:
        self.add_columns(
            ("Name", "name"),
            ("Level", "level"),
            ("Rep.", "rep"),
            ("Gang", "gang"),
        )
        self.cursor_type = "row"

    def on_players_pane_player_update(self, message: PlayerUpdate) -> None:
        # Upsert: update existing row if name matches, else add new row
        for row_key in self.rows:
            if str(self.get_row(row_key)[0]) == message.name:
                self.update_cell(row_key, "level", message.level)
                self.update_cell(row_key, "rep", message.rep)
                self.update_cell(row_key, "gang", message.gang)
                return
        self.add_row(message.name, message.level, message.rep, message.gang)
