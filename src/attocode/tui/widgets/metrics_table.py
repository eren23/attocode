"""Modal screen with DataTable for /status and /budget commands."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static


class MetricsScreen(ModalScreen[None]):
    """Modal screen showing agent metrics in a DataTable."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    MetricsScreen {
        align: center middle;
    }
    #metrics-container {
        width: 70;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        border: double #89b4fa;
        background: $surface;
        padding: 1 2;
    }
    #metrics-table {
        height: auto;
        max-height: 20;
    }
    """

    def __init__(self, title: str, rows: list[tuple[str, str]]) -> None:
        super().__init__()
        self._title = title
        self._rows = rows

    def compose(self) -> ComposeResult:
        with Vertical(id="metrics-container"):
            yield Static(self._title, classes="dialog-title")
            table = DataTable(id="metrics-table")
            table.add_columns("Metric", "Value")
            for key, val in self._rows:
                table.add_row(key, val)
            yield table
            yield Static("[dim]Press Esc or q to close[/dim]", classes="dialog-shortcuts")
