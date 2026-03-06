"""Plan panel widget showing task progress."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from attocode.types.agent import AgentPlan, TaskStatus


class PlanPanel(Static):
    """Displays the current plan with task progress."""

    DEFAULT_CSS = """
    PlanPanel {
        height: auto;
        max-height: 12;
        border: round $primary-darken-2;
        padding: 0 1;
        display: none;
    }

    PlanPanel.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._plan: AgentPlan | None = None

    def set_plan(self, plan: AgentPlan | None) -> None:
        """Update the displayed plan."""
        self._plan = plan
        self.set_class(plan is not None and len(plan.tasks) > 0, "visible")
        self.refresh()

    def render(self) -> Text:
        if self._plan is None:
            return Text("")

        text = Text()
        text.append("Plan: ", style="bold")
        text.append(self._plan.goal[:60], style="dim")

        completed = sum(
            1 for t in self._plan.tasks if t.status == TaskStatus.COMPLETED
        )
        total = len(self._plan.tasks)
        text.append(f"  [{completed}/{total}]", style="bold cyan")
        text.append("\n")

        for task in self._plan.tasks[-8:]:
            icon = _STATUS_ICONS.get(task.status, "?")
            text.append(f"  {icon} ", style=_STATUS_STYLES.get(task.status, "dim"))
            text.append(f"{task.description[:60]}\n")

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
