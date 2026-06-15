from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

_MENU = """\
[b]mmud — Menu / Help[/b]   (Esc or Ctrl+G to close)

[b]Keys[/b]
  Ctrl+G          this menu
  Ctrl+K          connect / disconnect
  Ctrl+L          start / stop the loop
  Ctrl+O          settings editor
  Ctrl+R          toggle the right panel
  Ctrl+B          toggle the stats bar
  Ctrl+1/2/3      Conversations / Players / Stats tab
  Tab             focus the main window = CHARACTER MODE
                  (keystrokes go raw to the server, for the in-game editor)
  Shift+Tab       leave character mode
  PageUp/PageDn   scroll the terminal (when the main window is focused)
  Esc             clear the command input

[b]Bot commands[/b]  (type in the command bar, prefixed with ':')
  :loop [NAME]    start a loop path (optional name override)
  :stop           stop the loop, clear the queue
  :find QUERY     search rooms by name/code (lists codes to feed :goto)
                    e.g.  :find arena
  :goto TARGET    travel to a room by 4-letter code OR name
                    e.g.  :goto CLKR   or   :goto newhaven arena
  :paths          list available loop paths
  :status         HP/MP, room, loop state
  :connect / :disconnect
  :help           this command list in the log

Anything without a ':' prefix is sent straight to the MUD.
"""


class HelpScreen(ModalScreen):
    """Menu / help overlay (Ctrl+G)."""

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("ctrl+g", "close", "Close", priority=True),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-body"):
            yield Static(_MENU, id="help-text", markup=True)

    def action_close(self) -> None:
        self.dismiss()
