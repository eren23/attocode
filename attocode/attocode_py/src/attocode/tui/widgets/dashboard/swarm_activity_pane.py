"""Swarm activity pane — multi-agent task monitoring."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Static

from attocode.tui.widgets.dashboard.viz import ASCIITable, PercentBar, SeverityBadge


class SwarmActivityPane(Container):
    """Pane showing swarm orchestrator activity — task grid, worker status, budgets."""

    DEFAULT_CSS = """
    SwarmActivityPane {
        layout: vertical;
        padding: 1 2;
        overflow-y: auto;
    }
    SwarmActivityPane .section-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    SwarmActivityPane .section {
        margin-bottom: 2;
    }
    SwarmActivityPane .no-swarm {
        text-align: center;
        color: $text-muted;
        margin-top: 3;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._swarm_status: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        yield Static(
            "No swarm activity. Start a swarm session to see task monitoring.",
            classes="no-swarm",
            id="swarm-empty-msg",
        )

    def update_status(self, status: Any) -> None:
        """Update with latest swarm status snapshot."""
        if status is None:
            return

        self._swarm_status = status if isinstance(status, dict) else {}
        if hasattr(status, '__dict__'):
            self._swarm_status = status.__dict__

        self._render_status()

    def _render_status(self) -> None:
        """Render swarm status."""
        status = self._swarm_status
        if not status:
            return

        self.remove_children()

        # Phase / overall status
        phase = status.get("phase", "unknown")
        total_tasks = status.get("total_tasks", 0)
        completed = status.get("completed_tasks", 0)
        failed = status.get("failed_tasks", 0)
        active_workers = status.get("active_workers", 0)

        # Overview section
        overview = Container(classes="section")
        self.mount(overview)
        overview.mount(Static("Swarm Overview", classes="section-title"))
        overview.mount(Static(f"Phase: {phase}"))
        overview.mount(Static(f"Tasks: {completed}/{total_tasks} completed, {failed} failed"))
        overview.mount(Static(f"Active workers: {active_workers}"))

        if total_tasks > 0:
            pct = completed / total_tasks
            bar = PercentBar()
            bar.value = pct
            overview.mount(bar)

        # Worker details if available
        workers = status.get("workers", [])
        if workers:
            worker_section = Container(classes="section")
            self.mount(worker_section)
            worker_section.mount(Static("Workers", classes="section-title"))

            rows: list[list[str]] = []
            for w in workers:
                if isinstance(w, dict):
                    wid = str(w.get("id", "?"))[:12]
                    wstatus = str(w.get("status", "?"))
                    wtask = str(w.get("current_task", "-"))[:30]
                    wmodel = str(w.get("model", "?"))[:20]
                    rows.append([wid, wstatus, wmodel, wtask])

            if rows:
                table = ASCIITable()
                table.headers = ["Worker", "Status", "Model", "Task"]
                table.rows = rows
                worker_section.mount(table)

        # Task queue if available
        queue = status.get("task_queue", status.get("pending_tasks", []))
        if queue:
            queue_section = Container(classes="section")
            self.mount(queue_section)
            queue_section.mount(Static("Task Queue", classes="section-title"))

            for i, task in enumerate(queue[:10]):
                if isinstance(task, dict):
                    desc = str(task.get("description", task.get("goal", f"Task {i}")))[:60]
                    priority = str(task.get("priority", "normal"))
                    queue_section.mount(Static(f"  [{priority}] {desc}"))
                elif isinstance(task, str):
                    queue_section.mount(Static(f"  {task[:60]}"))
