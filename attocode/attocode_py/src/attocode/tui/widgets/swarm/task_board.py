"""Task Board — kanban-style columns for task status."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Static


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

    def __init__(
        self,
        task_id: str = "",
        title: str = "",
        quality_score: int | None = None,
        attempts: int = 0,
        is_foundation: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.task_id = task_id
        self.title = title
        self._quality_score = quality_score
        self._attempts = attempts
        self._is_foundation = is_foundation

    def on_mount(self) -> None:
        text = Text()
        if self._is_foundation:
            text.append("\u2605 ", style="yellow")
        text.append(self.task_id, style="bold")
        # Quality score badge
        if self._quality_score is not None:
            score_style = "green" if self._quality_score >= 3 else "red"
            text.append(f" [{self._quality_score}/5]", style=score_style)
        # Retry count
        if self._attempts > 1:
            text.append(f" r{self._attempts}", style="yellow dim")
        text.append("\n")
        text.append(self.title[:80], style="dim italic")
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
        header_text = Text()
        header_text.append(title, style=style)
        header_text.append("  click to inspect", style="dim italic")
        yield Static(header_text, classes="column-header")

    def set_tasks(self, tasks: list[dict[str, Any]]) -> None:
        # Remove old task cards
        for child in list(self.children):
            if isinstance(child, TaskCard):
                child.remove()

        for task in tasks:
            card = TaskCard(
                task_id=task.get("task_id", "?"),
                title=task.get("title", ""),
                quality_score=task.get("quality_score"),
                attempts=task.get("attempts", 0),
                is_foundation=task.get("is_foundation", False),
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
        # Status mapping from coordinator/event bridge values to display buckets
        status_map = {
            "pending": "pending",
            "ready": "pending",
            "blocked": "pending",
            "running": "running",
            "reviewing": "running",
            "dispatched": "running",
            "done": "done",
            "completed": "done",
            "failed": "failed",
            "skipped": "failed",
            "decomposed": "pending",
        }
        for task in tasks:
            raw_status = task.get("status", "pending")
            status = status_map.get(raw_status, "pending")
            bucket = buckets.get(status, buckets["pending"])
            # Normalize task_id: event bridge uses "id", some places use "task_id"
            if "task_id" not in task and "id" in task:
                task = {**task, "task_id": task["id"]}
            if "title" not in task and "description" in task:
                task = {**task, "title": task["description"]}
            bucket.append(task)

        for key in ("pending", "running", "done", "failed"):
            try:
                col = self.query_one(f"#col-{key}", KanbanColumn)
                col.set_tasks(buckets[key])
            except Exception:
                pass


# ── Status display mapping (shared) ──────────────────────────────────

_TASK_STATUS_MAP = {
    "pending": "pending",
    "ready": "pending",
    "blocked": "pending",
    "running": "running",
    "reviewing": "running",
    "dispatched": "running",
    "done": "done",
    "completed": "done",
    "failed": "failed",
    "skipped": "failed",
    "decomposed": "pending",
}

_STATUS_ICONS = {
    "pending": "\u25cb",   # ○
    "running": "\u21bb",   # ↻
    "done": "\u2713",      # ✓
    "failed": "\u2717",    # ✗
}

_STATUS_SORT_ORDER = {"running": 0, "pending": 1, "done": 2, "failed": 3}


class TasksDataTable(Widget):
    """DataTable-based task list with single-click row selection.

    Posts ``TasksDataTable.TaskSelected`` when a row is selected.
    """

    class TaskSelected(Message):
        """Posted when a task row is selected."""

        def __init__(self, task_id: str) -> None:
            super().__init__()
            self.task_id = task_id

    DEFAULT_CSS = """
    TasksDataTable {
        height: 1fr;
    }
    TasksDataTable > DataTable {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._task_rows: list[dict[str, Any]] = []

    def compose(self):
        table = DataTable(id="tasks-table", cursor_type="row")
        table.add_columns("Status", "ID", "Title", "Kind", "Agent", "Attempts", "Deps")
        yield table

    def update_tasks(self, tasks: list[dict[str, Any]]) -> None:
        """Replace all task rows."""
        self._task_rows = tasks
        self._rebuild()

    def _rebuild(self) -> None:
        try:
            table = self.query_one("#tasks-table", DataTable)
        except Exception:
            return

        table.clear()

        # Sort: running first, then pending, done, failed
        sorted_tasks = sorted(
            self._task_rows,
            key=lambda t: _STATUS_SORT_ORDER.get(
                _TASK_STATUS_MAP.get(t.get("status", "pending"), "pending"), 99
            ),
        )

        for task in sorted_tasks:
            raw_status = task.get("status", "pending")
            bucket = _TASK_STATUS_MAP.get(raw_status, "pending")
            icon = _STATUS_ICONS.get(bucket, "?")

            status_text = Text(f"{icon} {raw_status}", style={
                "pending": "dim",
                "running": "cyan bold",
                "done": "green",
                "failed": "red bold",
            }.get(bucket, ""))

            task_id = task.get("task_id", task.get("id", "?"))
            title = task.get("title", task.get("description", ""))[:50]
            kind = task.get("task_kind", "")
            agent = task.get("assigned_agent", "")
            attempts = task.get("attempts", 0)
            deps = task.get("depends_on", task.get("deps", []))
            deps_str = ", ".join(str(d) for d in deps[:3])
            if len(deps) > 3:
                deps_str += f" +{len(deps) - 3}"

            table.add_row(
                status_text,
                task_id,
                title,
                kind,
                agent,
                str(attempts) if attempts else "",
                deps_str,
                key=task_id,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value:
            self.post_message(self.TaskSelected(str(event.row_key.value)))
