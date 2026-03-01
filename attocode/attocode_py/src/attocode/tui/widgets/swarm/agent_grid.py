"""Agent Grid — shows live status of each worker agent."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Static


_STATUS_ICONS = {
    "idle": "\u2501",      # ━
    "claiming": "\u21bb",   # ↻
    "running": "\u21bb",    # ↻
    "done": "\u2713",       # ✓
    "error": "\u2717",      # ✗
}

_STATUS_STYLES = {
    "idle": "dim",
    "claiming": "yellow",
    "running": "cyan bold",
    "done": "green",
    "error": "red bold",
}


class AgentCard(Static):
    """A single agent status card."""

    class Selected(Message):
        """Posted when the agent card is clicked."""

        def __init__(self, agent_id: str) -> None:
            super().__init__()
            self.agent_id = agent_id

    DEFAULT_CSS = """
    AgentCard {
        width: 24;
        height: 5;
        border: solid $surface-lighten-2;
        padding: 0 1;
        margin: 0 1 0 0;
    }
    AgentCard.running {
        border: solid $accent;
    }
    AgentCard.done {
        border: solid $success;
    }
    AgentCard.error {
        border: solid $error;
    }
    """

    def __init__(self, agent_id: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.agent_id = agent_id
        self._task_id = ""
        self._status = "idle"
        self._model = ""
        self._tokens = 0
        self._elapsed = ""
        self._task_title = ""

    def update_data(
        self,
        status: str = "idle",
        task_id: str = "",
        model: str = "",
        tokens: int = 0,
        elapsed: str = "",
        task_title: str = "",
    ) -> None:
        self._status = status
        self._task_id = task_id
        self._model = model
        self._tokens = tokens
        self._elapsed = elapsed
        self._task_title = task_title

        # Update CSS class
        self.remove_class("running", "done", "error")
        if status in ("running", "claiming"):
            self.add_class("running")
        elif status == "done":
            self.add_class("done")
        elif status == "error":
            self.add_class("error")

        self._render_content()

    def _render_content(self) -> None:
        icon = _STATUS_ICONS.get(self._status, "?")
        style = _STATUS_STYLES.get(self._status, "")

        text = Text()
        text.append(f"{icon} ", style=style)
        text.append(self.agent_id, style="bold")
        if self._model:
            text.append(f" ({self._model})", style="dim")
        text.append("\n")
        if self._task_id:
            label = self._task_title[:30] if self._task_title else self._task_id[:18]
            text.append(f"  {label}", style="italic")
        text.append("\n")
        if self._tokens:
            text.append(f"  {self._tokens // 1000}k tok", style="dim")
        if self._elapsed:
            text.append(f" \u00b7 {self._elapsed}", style="dim")

        self.update(text)

    def on_click(self) -> None:
        self.post_message(self.Selected(self.agent_id))


class AgentGrid(Widget):
    """Grid of agent cards showing live status for each worker."""

    DEFAULT_CSS = """
    AgentGrid {
        height: auto;
        max-height: 8;
        padding: 0;
    }
    AgentGrid > Horizontal {
        height: auto;
    }
    """

    agents: reactive[list[dict[str, Any]]] = reactive(list, layout=True)

    def compose(self):
        yield Horizontal(id="agent-grid-row")

    def watch_agents(self, agents: list[dict[str, Any]]) -> None:
        self._rebuild(agents)

    def update_agents(self, agents: list[dict[str, Any]]) -> None:
        """External API to update the grid."""
        self.agents = agents

    def _rebuild(self, agents: list[dict[str, Any]]) -> None:
        try:
            row = self.query_one("#agent-grid-row", Horizontal)
        except Exception:
            return

        # Clear existing cards
        row.remove_children()

        if not agents:
            row.mount(Static(Text("No active agents", style="dim italic")))
            return

        for agent in agents:
            # Event bridge uses "worker_name"; fallback to "agent_id"
            agent_id = agent.get("worker_name") or agent.get("agent_id", "?")
            card = AgentCard(agent_id=agent_id)
            row.mount(card)

            # Compute elapsed string from started_at timestamp
            elapsed_str = agent.get("elapsed", "")
            if not elapsed_str:
                import time as _time
                started_at = agent.get("started_at", 0)
                if started_at:
                    secs = int(_time.time() - started_at)
                    elapsed_str = f"{secs}s" if secs < 60 else f"{secs // 60}m{secs % 60:02d}s"

            card.update_data(
                status=agent.get("status", "running" if agent.get("task_id") else "idle"),
                task_id=agent.get("task_id", ""),
                model=agent.get("model", ""),
                tokens=agent.get("tokens_used", 0),
                elapsed=elapsed_str,
                task_title=agent.get("task_title", ""),
            )


_AGENT_STATUS_ICONS = {
    "running": "\u21bb",   # ↻
    "idle": "\u2501",      # ━
    "exited": "\u2717",    # ✗
}


class AgentsDataTable(Widget):
    """DataTable-based agent list with single-click row selection.

    Posts ``AgentsDataTable.AgentSelected`` when a row is selected.
    """

    class AgentSelected(Message):
        """Posted when an agent row is selected."""

        def __init__(self, agent_id: str) -> None:
            super().__init__()
            self.agent_id = agent_id

    DEFAULT_CSS = """
    AgentsDataTable {
        height: 1fr;
    }
    AgentsDataTable > DataTable {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agent_rows: list[dict[str, Any]] = []

    def compose(self):
        table = DataTable(id="agents-table", cursor_type="row")
        table.add_columns("Status", "Agent", "Backend", "Model", "Task", "Elapsed", "Restarts")
        yield table

    def update_agents(self, agents: list[dict[str, Any]]) -> None:
        """Replace all agent rows."""
        self._agent_rows = agents
        self._rebuild()

    def _rebuild(self) -> None:
        try:
            table = self.query_one("#agents-table", DataTable)
        except Exception:
            return

        table.clear()

        for agent in self._agent_rows:
            agent_id = agent.get("worker_name") or agent.get("agent_id", "?")
            status = agent.get("status", "idle")
            icon = _AGENT_STATUS_ICONS.get(status, "?")

            status_style = {
                "running": "cyan bold",
                "idle": "dim",
                "exited": "red",
            }.get(status, "dim")

            status_text = Text(f"{icon} {status}", style=status_style)
            backend = agent.get("backend", "")
            model = agent.get("model", backend)
            task_id = agent.get("task_id", "")
            elapsed = agent.get("elapsed", "")
            restarts = agent.get("restart_count", 0)
            exit_code = agent.get("exit_code")

            # Show exit code for exited agents
            restarts_str = str(restarts) if restarts else ""
            if exit_code is not None and status == "exited":
                restarts_str = f"{restarts} (exit:{exit_code})"

            table.add_row(
                status_text,
                agent_id,
                backend,
                model,
                task_id or "",
                elapsed,
                restarts_str,
                key=agent_id,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value:
            self.post_message(self.AgentSelected(str(event.row_key.value)))
