"""Edit Task Screen — modal for editing a task's description."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea


class EditTaskScreen(ModalScreen[tuple[str, str] | None]):
    """Modal for editing a task's description."""

    DEFAULT_CSS = """
    EditTaskScreen {
        align: center middle;
    }
    #edit-modal {
        width: 80%;
        max-width: 100;
        height: auto;
        max-height: 24;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #edit-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        height: 1;
        margin-bottom: 1;
    }
    #edit-area {
        height: 12;
    }
    #edit-hint {
        height: 1;
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, task_id: str, description: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._task_id = task_id
        self._description = description

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-modal"):
            yield Static(f"Edit Task: {self._task_id}", id="edit-title")
            yield TextArea(self._description, id="edit-area")
            yield Static("[Ctrl+S] Save  [ESC] Cancel", id="edit-hint")

    def action_save(self) -> None:
        area = self.query_one("#edit-area", TextArea)
        new_desc = area.text.strip()
        if not new_desc:
            self.notify("Description cannot be empty", severity="warning")
            return
        self.dismiss((self._task_id, new_desc))

    def action_cancel(self) -> None:
        self.dismiss(None)
