"""Confirmation modal for stopping a running swarm."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class ConfirmStopScreen(ModalScreen[bool | None]):
    """Ask the operator to confirm a graceful swarm stop request."""

    DEFAULT_CSS = """
    ConfirmStopScreen {
        align: center middle;
    }
    #confirm-stop-modal {
        width: 70%;
        max-width: 84;
        height: auto;
        border: round $warning;
        background: $surface;
        padding: 1 2;
    }
    #confirm-stop-title {
        text-align: center;
        text-style: bold;
        color: $warning;
        height: 1;
        margin-bottom: 1;
    }
    #confirm-stop-body {
        height: auto;
        margin-bottom: 1;
    }
    #confirm-stop-hint {
        height: 2;
        color: $text-muted;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("enter", "confirm", "Stop", show=True),
        Binding("y", "confirm", "Stop", show=False),
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("n", "cancel", "Cancel", show=False),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-stop-modal"):
            yield Static("Stop Swarm?", id="confirm-stop-title")
            yield Static(
                "This requests a graceful coordinator shutdown.\n"
                "Use [q] to leave the dashboard without stopping the run.",
                id="confirm-stop-body",
            )
            yield Static("[Enter/Y] Stop  [ESC/N] Cancel", id="confirm-stop-hint")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
