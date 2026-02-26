"""Task Board — kanban-style columns for task status."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


_COLUMN_TITLES = {
    "pending": "PENDING",
    "running": "RUNNING",
    "done": "DONE",
    "failed": "FAILED",
    "skipped": "SKIPPED",
}

_COLUMN_STYLES = {
    "pending": "dim",
    "running": "cyan",
    "done": "green",
    "failed": "red",
    "skipped": "yellow",
}


class TaskCard(Static):
    """A single task card inside a kanban column."""

    class Selected(Message):
        """Posted when the task card is clicked."""

        def __init__(self, task_id: str) -> None:
            super().__init__()
            self.task_id = task_id

    DEFAULT_CSS = """
    TaskCard {
        width: 100%;
        height: 3;
        border: solid $surface-lighten-1;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, task_id: str = "", title: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.task_id = task_id
        self.title = title

    def on_mount(self) -> None:
        text = Text()
        text.append(self.task_id, style="bold")
        text.append("\n")
        text.append(self.title[:30], style="dim italic")
        self.update(text)

    def on_click(self) -> None:
        self.post_message(self.Selected(self.task_id))


class KanbanColumn(Vertical):
    """A single kanban column (PENDING, RUNNING, etc.)."""

    DEFAULT_CSS = """
    KanbanColumn {
        width: 1fr;
        height: 100%;
        border: solid $surface-lighten-1;
        padding: 0 1;
        overflow-y: auto;
    }
    KanbanColumn > .column-header {
        text-style: bold;
        text-align: center;
        width: 100%;
        height: 1;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, column_key: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.column_key = column_key

    def compose(self):
        title = _COLUMN_TITLES.get(self.column_key, self.column_key.upper())
        style = _COLUMN_STYLES.get(self.column_key, "")
        header = Static(Text(title, style=style), classes="column-header")
        yield header

    def set_tasks(self, tasks: list[dict[str, Any]]) -> None:
        # Remove old task cards
        for child in list(self.children):
            if isinstance(child, TaskCard):
                child.remove()

        for task in tasks:
            card = TaskCard(
                task_id=task.get("task_id", "?"),
                title=task.get("title", ""),
            )
            self.mount(card)


class TaskBoard(Widget):
    """Kanban board with columns: Pending | Running | Done | Failed."""

    DEFAULT_CSS = """
    TaskBoard {
        height: auto;
        min-height: 10;
        max-height: 16;
    }
    TaskBoard > Horizontal {
        height: 100%;
    }
    """

    tasks: reactive[list[dict[str, Any]]] = reactive(list, layout=True)

    def compose(self):
        with Horizontal():
            yield KanbanColumn("pending", id="col-pending")
            yield KanbanColumn("running", id="col-running")
            yield KanbanColumn("done", id="col-done")
            yield KanbanColumn("failed", id="col-failed")

    def watch_tasks(self, tasks: list[dict[str, Any]]) -> None:
        self._distribute(tasks)

    def update_tasks(self, tasks: list[dict[str, Any]]) -> None:
        """External API to update the board."""
        self.tasks = tasks

    def _distribute(self, tasks: list[dict[str, Any]]) -> None:
        buckets: dict[str, list[dict[str, Any]]] = {
            "pending": [],
            "running": [],
            "done": [],
            "failed": [],
        }
        for task in tasks:
            status = task.get("status", "pending")
            if status in ("skipped",):
                status = "failed"
            bucket = buckets.get(status, buckets["pending"])
            bucket.append(task)

        for key in ("pending", "running", "done", "failed"):
            try:
                col = self.query_one(f"#col-{key}", KanbanColumn)
                col.set_tasks(buckets[key])
            except Exception:
                pass
