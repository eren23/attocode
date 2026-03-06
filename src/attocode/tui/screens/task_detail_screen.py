"""Task Detail Screen — modal overlay for inspecting task/agent details."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from attocode.tui.widgets.swarm.detail_inspector import DetailInspector


class TaskDetailScreen(ModalScreen[None]):
    """Full-screen modal that shows a DetailInspector for a task or agent.

    Dismissible via ESC or q.
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    TaskDetailScreen {
        align: center middle;
    }
    #task-detail-modal {
        width: 80%;
        max-width: 100;
        height: 80%;
        max-height: 30;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    .modal-hint {
        height: 1;
        color: $text-muted;
        text-align: right;
    }
    """

    def __init__(self, detail: dict[str, Any]) -> None:
        super().__init__()
        self._detail = detail

    def compose(self) -> ComposeResult:
        with Vertical(id="task-detail-modal"):
            yield Static("[ESC to close]", classes="modal-hint")
            yield DetailInspector(id="modal-detail")

    def on_mount(self) -> None:
        self.query_one("#modal-detail", DetailInspector).inspect(self._detail)
