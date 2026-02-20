"""Tasks panel widget."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from attocode.types.agent import PlanTask, TaskStatus


class TasksPanel(Static):
    """Displays active tasks with dependencies."""

    DEFAULT_CSS = """
    TasksPanel {
        height: auto;
        max-height: 10;
        border: round $primary-darken-2;
        padding: 0 1;
        display: none;
    }

    TasksPanel.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tasks: list[PlanTask] = []

    def set_tasks(self, tasks: list[PlanTask]) -> None:
        """Update the displayed tasks."""
        self._tasks = tasks
        self.set_class(len(tasks) > 0, "visible")
        self.refresh()

    def render(self) -> Text:
        if not self._tasks:
            return Text("")

        text = Text()
        text.append("Tasks", style="bold")

        active = sum(
            1
            for t in self._tasks
            if t.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)
        )
        done = sum(1 for t in self._tasks if t.status == TaskStatus.COMPLETED)
        text.append(f" ({done}\u2713 {active} active)\n", style="dim")

        for task in self._tasks[-5:]:
            icon = _STATUS_ICONS.get(task.status, "?")
            style = _STATUS_STYLES.get(task.status, "dim")
            text.append(f"  {icon} ", style=style)
            text.append(f"{task.description[:55]}")
            if task.dependencies:
                deps = ", ".join(task.dependencies[:2])
                text.append(f" [blocked by: {deps}]", style="dim")
            text.append("\n")

        return text


_STATUS_ICONS = {
    TaskStatus.PENDING: "\u25cb",
    TaskStatus.IN_PROGRESS: "\u25c9",
    TaskStatus.COMPLETED: "\u2713",
    TaskStatus.FAILED: "\u2717",
    TaskStatus.BLOCKED: "\u2298",
    TaskStatus.SKIPPED: "\u2296",
}

_STATUS_STYLES = {
    TaskStatus.PENDING: "dim",
    TaskStatus.IN_PROGRESS: "bold yellow",
    TaskStatus.COMPLETED: "green",
    TaskStatus.FAILED: "red",
    TaskStatus.BLOCKED: "dim red",
    TaskStatus.SKIPPED: "dim",
}
