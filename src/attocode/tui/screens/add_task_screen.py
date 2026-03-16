"""Add Task Screen — modal for adding a new task to the DAG."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static, TextArea


class AddTaskScreen(ModalScreen[dict[str, Any] | None]):
    """Modal for adding a new task to the DAG."""

    DEFAULT_CSS = """
    AddTaskScreen {
        align: center middle;
    }
    #add-modal {
        width: 80%;
        max-width: 100;
        height: auto;
        max-height: 30;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #add-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        height: 1;
        margin-bottom: 1;
    }
    .field-label {
        height: 1;
        margin-top: 1;
        color: $text-muted;
    }
    #add-desc-area {
        height: 6;
    }
    #add-hint {
        height: 1;
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "submit", "Submit", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="add-modal"):
            yield Static("Add New Task", id="add-title")
            yield Static("Title:", classes="field-label")
            yield Input(placeholder="Short task title", id="add-title-input")
            yield Static("Description:", classes="field-label")
            yield TextArea(id="add-desc-area")
            yield Static("Dependencies (comma-separated task IDs, optional):", classes="field-label")
            yield Input(placeholder="task-1, task-2", id="add-deps-input")
            yield Static("Target files (comma-separated, optional):", classes="field-label")
            yield Input(placeholder="src/foo.py, src/bar.py", id="add-files-input")
            yield Static("[Ctrl+S] Submit  [ESC] Cancel", id="add-hint")

    def action_submit(self) -> None:
        title = self.query_one("#add-title-input", Input).value.strip()
        if not title:
            self.notify("Title is required", severity="warning")
            return
        desc = self.query_one("#add-desc-area", TextArea).text.strip()
        deps_raw = self.query_one("#add-deps-input", Input).value.strip()
        deps = [d.strip() for d in deps_raw.split(",") if d.strip()] if deps_raw else []
        files_raw = self.query_one("#add-files-input", Input).value.strip()
        target_files = [f.strip() for f in files_raw.split(",") if f.strip()] if files_raw else []

        self.dismiss({
            "title": title,
            "description": desc or title,
            "deps": deps,
            "target_files": target_files,
            "task_kind": "implement",
        })

    def action_cancel(self) -> None:
        self.dismiss(None)
