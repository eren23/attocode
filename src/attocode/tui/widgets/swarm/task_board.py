"""Task Board — kanban-style columns for task status."""

from __future__ import annotations

import contextlib
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

    Posts ``TasksDataTable.TaskSelected`` when a row is highlighted or selected.
    Uses differential updates to preserve cursor position across refreshes.
    """

    class TaskSelected(Message):
        """Posted when a task row is selected or highlighted."""

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
        self._prev_task_map: dict[str, dict[str, str]] = {}
        self._selected_key: str | None = None
        self._prev_order: list[str] = []
        self._restoring_cursor: bool = False

    def compose(self):
        table = DataTable(id="tasks-table", cursor_type="row")
        table.add_columns("Status", "ID", "Title", "Kind", "Agent", "Attempts", "Deps")
        yield table

    def update_tasks(self, tasks: list[dict[str, Any]]) -> None:
        """Replace all task rows with differential updates."""
        self._task_rows = tasks
        self._rebuild()

    @staticmethod
    def _make_row_data(task: dict[str, Any]) -> dict[str, str]:
        """Extract display values from a task dict."""
        raw_status = task.get("status", "pending")
        bucket = _TASK_STATUS_MAP.get(raw_status, "pending")
        task_id = task.get("task_id", task.get("id", "?"))
        title = task.get("title", task.get("description", ""))[:50]
        kind = task.get("task_kind", "")
        agent = task.get("assigned_agent", "")
        attempts = task.get("attempts", 0)
        deps = task.get("depends_on", task.get("deps", []))
        deps_str = ", ".join(str(d) for d in deps[:3])
        if len(deps) > 3:
            deps_str += f" +{len(deps) - 3}"
        return {
            "raw_status": raw_status,
            "bucket": bucket,
            "task_id": task_id,
            "title": title,
            "kind": kind,
            "agent": agent,
            "attempts": str(attempts) if attempts else "",
            "deps": deps_str,
        }

    @staticmethod
    def _status_text(raw_status: str, bucket: str) -> Text:
        icon = _STATUS_ICONS.get(bucket, "?")
        return Text(f"{icon} {raw_status}", style={
            "pending": "dim",
            "running": "cyan bold",
            "done": "green",
            "failed": "red bold",
        }.get(bucket, ""))

    def _rebuild(self) -> None:
        try:
            table = self.query_one("#tasks-table", DataTable)
        except Exception:
            return

        # Sort: status bucket primary, task_id secondary. Cross-bucket transitions
        # (e.g. pending→running) change the order and trigger a full rebuild;
        # only intra-bucket changes (cell updates) use the differential path.
        sorted_tasks = sorted(
            self._task_rows,
            key=lambda t: (
                _STATUS_SORT_ORDER.get(
                    _TASK_STATUS_MAP.get(t.get("status", "pending"), "pending"), 99
                ),
                t.get("task_id", ""),
            ),
        )

        new_map: dict[str, dict[str, str]] = {}
        new_order: list[str] = []
        for task in sorted_tasks:
            row_data = self._make_row_data(task)
            tid = row_data["task_id"]
            new_map[tid] = row_data
            new_order.append(tid)

        old_keys = set(self._prev_task_map)
        new_keys = set(new_map)

        # Detect if sort order changed (requires full rebuild)
        order_changed = new_order != self._prev_order

        if order_changed or not self._prev_task_map:
            # Full rebuild (first time or sort order changed)
            table.clear()
            for tid in new_order:
                rd = new_map[tid]
                table.add_row(
                    self._status_text(rd["raw_status"], rd["bucket"]),
                    rd["task_id"],
                    rd["title"],
                    rd["kind"],
                    rd["agent"],
                    rd["attempts"],
                    rd["deps"],
                    key=tid,
                )
        else:
            # Differential update
            # Remove deleted rows
            for removed_key in old_keys - new_keys:
                with contextlib.suppress(Exception):
                    table.remove_row(removed_key)

            # Add new rows
            for added_key in new_keys - old_keys:
                rd = new_map[added_key]
                table.add_row(
                    self._status_text(rd["raw_status"], rd["bucket"]),
                    rd["task_id"],
                    rd["title"],
                    rd["kind"],
                    rd["agent"],
                    rd["attempts"],
                    rd["deps"],
                    key=added_key,
                )

            # Accumulate transitions for batched toasts
            transitions: dict[str, int | list[str]] = {
                "started": 0, "completed": 0, "failed": [],
            }

            # Update changed cells in existing rows
            col_keys = list(table.columns.keys())
            for tid in old_keys & new_keys:
                old_rd = self._prev_task_map[tid]
                new_rd = new_map[tid]

                # Track status transitions for batched notification
                if old_rd["bucket"] != new_rd["bucket"]:
                    if new_rd["bucket"] == "running":
                        transitions["started"] += 1  # type: ignore[operator]
                    elif new_rd["bucket"] == "done":
                        transitions["completed"] += 1  # type: ignore[operator]
                    elif new_rd["bucket"] == "failed":
                        transitions["failed"].append(tid)  # type: ignore[union-attr]

                # Update individual cells that changed
                field_to_col = [
                    ("raw_status", 0),  # Status column
                    ("task_id", 1),
                    ("title", 2),
                    ("kind", 3),
                    ("agent", 4),
                    ("attempts", 5),
                    ("deps", 6),
                ]
                for field, col_idx in field_to_col:
                    if old_rd.get(field) != new_rd.get(field):
                        try:
                            if col_idx < len(col_keys):
                                value = new_rd[field]
                                if field == "raw_status":
                                    value = self._status_text(
                                        new_rd["raw_status"], new_rd["bucket"],
                                    )
                                table.update_cell(tid, col_keys[col_idx], value)
                        except Exception:
                            pass

            # Emit batched toast notifications (max 3)
            started = transitions["started"]
            if started == 1:
                self.notify("1 task started", severity="information")
            elif started:  # type: ignore[truthy-bool]
                self.notify(f"{started} tasks started", severity="information")

            completed = transitions["completed"]
            if completed == 1:
                self.notify("1 task completed", severity="information")
            elif completed:  # type: ignore[truthy-bool]
                self.notify(f"{completed} tasks completed", severity="information")

            failed_list: list[str] = transitions["failed"]  # type: ignore[assignment]
            if len(failed_list) == 1:
                self.notify(f"Task {failed_list[0]} failed", severity="warning")
            elif failed_list:
                self.notify(f"{len(failed_list)} tasks failed", severity="warning")

        self._prev_task_map = new_map
        self._prev_order = new_order

        # Restore cursor position
        if self._selected_key and self._selected_key in new_keys:
            try:
                row_idx = new_order.index(self._selected_key)
                self._restoring_cursor = True
                table.move_cursor(row=row_idx)
                self._restoring_cursor = False
            except (ValueError, Exception):
                self._restoring_cursor = False

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._restoring_cursor:
            return
        if event.row_key and event.row_key.value:
            self._selected_key = str(event.row_key.value)
            self.post_message(self.TaskSelected(self._selected_key))
