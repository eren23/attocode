"""Tab 3: Tasks pane — comprehensive task inspector with DataTable + deep detail."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Static


_STATUS_COLORS = {
    "pending": "dim",
    "ready": "white",
    "dispatched": "cyan",
    "completed": "green",
    "failed": "red",
    "skipped": "yellow",
    "decomposed": "magenta",
}


class TaskDeepInspector(Widget):
    """Right panel: detailed view of a selected task."""

    DEFAULT_CSS = """
    TaskDeepInspector {
        height: 1fr;
        border: solid $accent;
        padding: 1;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._task: dict[str, Any] | None = None
        self._quality: dict[str, Any] | None = None

    def render(self) -> Text:
        text = Text()
        if not self._task:
            text.append("Select a task to inspect", style="dim italic")
            return text

        t = self._task
        text.append("Task Inspector\n", style="bold underline")
        text.append("\n")

        text.append(f"ID: {t.get('id', '?')}\n", style="bold")
        text.append(f"Status: {t.get('status', '?')}\n", style=_STATUS_COLORS.get(t.get("status", ""), "white"))
        text.append(f"Type: {t.get('type', '?')}\n", style="dim")
        text.append(f"Complexity: {t.get('complexity', '?')}/10\n", style="dim")
        text.append(f"Wave: {t.get('wave', '?')}\n", style="dim")
        text.append(f"Model: {t.get('assigned_model', 'unassigned')}\n", style="dim")
        text.append(f"Foundation: {'Yes' if t.get('is_foundation') else 'No'}\n", style="dim")
        text.append(f"Attempts: {t.get('attempts', 0)}\n", style="dim")
        text.append(f"Degraded: {'Yes' if t.get('degraded') else 'No'}\n", style="dim")

        text.append("\n")
        text.append("Description\n", style="bold")
        text.append(f"{t.get('description', 'N/A')}\n", style="")

        deps = t.get("dependencies", [])
        if deps:
            text.append("\n")
            text.append("Dependencies\n", style="bold")
            for d in deps:
                text.append(f"  - {d}\n", style="dim")

        # Worker result data
        output = t.get("output", "")
        if output:
            text.append("\n")
            text.append("Worker Output\n", style="bold")
            text.append(f"{output[:500]}\n", style="")
            if len(output) > 500:
                text.append(f"  ... ({len(output)} chars total)\n", style="dim")

        files_mod = t.get("files_modified") or []
        if files_mod:
            text.append("\n")
            text.append("Files Modified\n", style="bold")
            for f in files_mod[:20]:
                text.append(f"  {f}\n", style="green dim")

        stderr = t.get("stderr", "")
        if stderr:
            text.append("\n")
            text.append("Stderr\n", style="bold red")
            text.append(f"{stderr[:300]}\n", style="red dim")

        session_id = t.get("session_id", "")
        num_turns = t.get("num_turns", 0)
        cost_used = t.get("cost_used", 0.0)
        duration_ms = t.get("duration_ms", 0)

        if session_id or num_turns or cost_used or duration_ms:
            text.append("\n")
            text.append("Execution Details\n", style="bold")
            if session_id:
                text.append(f"  Session: {session_id}\n", style="dim")
            if num_turns:
                text.append(f"  Turns: {num_turns}\n", style="dim")
            if cost_used:
                text.append(f"  Cost: ${cost_used:.4f}\n", style="magenta")
            if duration_ms:
                text.append(f"  Duration: {duration_ms}ms\n", style="dim")

        # Quality gate result
        if self._quality:
            text.append("\n")
            text.append("Quality Gate\n", style="bold")
            score = self._quality.get("score", "?")
            passed = self._quality.get("passed", False)
            score_style = "green" if passed else "red"
            text.append(f"  Score: {score}/5 ", style=score_style)
            text.append("PASSED\n" if passed else "FAILED\n", style=score_style)
            feedback = self._quality.get("feedback", "")
            if feedback:
                text.append(f"  {feedback}\n", style="dim")

        return text

    def inspect_task(
        self,
        task: dict[str, Any],
        quality: dict[str, Any] | None = None,
    ) -> None:
        """Set the task to display."""
        self._task = task
        self._quality = quality
        self.refresh()


class TasksPane(Widget):
    """Left: TaskDetailTable (DataTable), Right: TaskDeepInspector."""

    DEFAULT_CSS = """
    TasksPane {
        height: 1fr;
    }
    TasksPane #tasks-table-container {
        width: 2fr;
    }
    TasksPane #tasks-inspector-container {
        width: 1fr;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tasks: dict[str, dict[str, Any]] = {}
        self._quality_results: dict[str, dict[str, Any]] = {}
        self._task_ids: list[str] = []

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="tasks-table-container"):
                yield DataTable(id="tasks-datatable", cursor_type="row")
            with Vertical(id="tasks-inspector-container"):
                yield TaskDeepInspector(id="task-inspector")

    def on_mount(self) -> None:
        table = self.query_one("#tasks-datatable", DataTable)
        table.add_columns(
            "ID", "Desc", "Status", "Type", "Cplx", "Wave",
            "Model", "Fnd", "Att", "Deg", "FM",
        )

    def update_state(self, state: dict[str, Any]) -> None:
        """Rebuild the table from state."""
        self._tasks = state.get("tasks", {})
        self._quality_results = state.get("quality_results", {})
        self._task_ids = sorted(self._tasks.keys())

        try:
            table = self.query_one("#tasks-datatable", DataTable)
            table.clear()

            for tid in self._task_ids:
                t = self._tasks[tid]
                status = t.get("status", "?")
                style = _STATUS_COLORS.get(status, "white")

                table.add_row(
                    Text(tid[:12], style=style),
                    str(t.get("description", ""))[:40],
                    Text(status, style=style),
                    str(t.get("type", "?"))[:8],
                    str(t.get("complexity", "?")),
                    str(t.get("wave", "?")),
                    (t.get("assigned_model") or "-")[:15],
                    "Y" if t.get("is_foundation") else "",
                    str(t.get("attempts", 0)),
                    "Y" if t.get("degraded") else "",
                    str(t.get("failure_mode", "") or "")[:8],
                    key=tid,
                )
        except Exception:
            pass

    def select_task(self, task_id: str) -> None:
        """Programmatically select a task row and update the inspector."""
        task = self._tasks.get(task_id)
        if not task:
            return
        try:
            table = self.query_one("#tasks-datatable", DataTable)
            # Move cursor to the row with this key
            for idx, row_key in enumerate(table.rows):
                if str(row_key) == task_id:
                    table.move_cursor(row=idx)
                    break
            # Update inspector
            quality = self._quality_results.get(task_id)
            self.query_one("#task-inspector", TaskDeepInspector).inspect_task(
                task, quality
            )
        except Exception:
            pass

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Inspect the selected task."""
        tid = str(event.row_key.value) if event.row_key else ""
        task = self._tasks.get(tid)
        if task:
            quality = self._quality_results.get(tid)
            try:
                self.query_one("#task-inspector", TaskDeepInspector).inspect_task(
                    task, quality
                )
            except Exception:
                pass
