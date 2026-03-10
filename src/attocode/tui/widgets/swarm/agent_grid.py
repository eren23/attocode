"""Agent Grid — shows live status of each worker agent."""

from __future__ import annotations

import contextlib
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

        if not agents:
            row.remove_children()
            row.mount(Static(Text("No active agents", style="dim italic")))
            return

        # Build lookup of existing cards by agent_id
        existing: dict[str, AgentCard] = {
            c.agent_id: c for c in row.query(AgentCard)
        }
        new_ids: set[str] = set()

        for agent in agents:
            agent_id = agent.get("worker_name") or agent.get("agent_id", "?")
            new_ids.add(agent_id)

            # Compute elapsed string from started_at timestamp
            elapsed_str = agent.get("elapsed", "")
            if not elapsed_str:
                import time as _time
                started_at = agent.get("started_at", 0)
                if started_at:
                    secs = int(_time.time() - started_at)
                    elapsed_str = f"{secs}s" if secs < 60 else f"{secs // 60}m{secs % 60:02d}s"

            status = agent.get("status", "running" if agent.get("task_id") else "idle")
            task_id = agent.get("task_id", "")
            model = agent.get("model", "")
            tokens = agent.get("tokens_used", 0)
            task_title = agent.get("task_title", "")

            if agent_id in existing:
                # Update in-place (no DOM ops)
                existing[agent_id].update_data(
                    status=status, task_id=task_id, model=model,
                    tokens=tokens, elapsed=elapsed_str, task_title=task_title,
                )
            else:
                # Mount new card
                # Remove "no agents" placeholder if present (exact type, not isinstance,
                # because AgentCard is a subclass of Static)
                for child in list(row.children):
                    if type(child) is Static:
                        child.remove()
                card = AgentCard(agent_id=agent_id)
                row.mount(card)
                card.update_data(
                    status=status, task_id=task_id, model=model,
                    tokens=tokens, elapsed=elapsed_str, task_title=task_title,
                )

        # Remove departed agent cards
        for aid, card in existing.items():
            if aid not in new_ids:
                card.remove()


_AGENT_STATUS_ICONS = {
    "running": "\u21bb",   # ↻
    "idle": "\u2501",      # ━
    "exited": "\u2717",    # ✗
}


class AgentsDataTable(Widget):
    """DataTable-based agent list with single-click row selection.

    Posts ``AgentsDataTable.AgentSelected`` when a row is highlighted or selected.
    Uses differential updates to preserve cursor position across refreshes.
    """

    class AgentSelected(Message):
        """Posted when an agent row is selected or highlighted."""

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
        self._prev_agent_map: dict[str, dict[str, str]] = {}
        self._selected_key: str | None = None
        self._prev_order: list[str] = []
        self._restoring_cursor: bool = False

    def compose(self):
        table = DataTable(id="agents-table", cursor_type="row")
        table.add_columns("Status", "Agent", "Task", "Activity", "Model", "Elapsed", "Tokens")
        yield table

    def update_agents(self, agents: list[dict[str, Any]]) -> None:
        """Replace all agent rows with differential updates."""
        self._agent_rows = agents
        self._rebuild()

    @staticmethod
    def _make_row_data(agent: dict[str, Any]) -> dict[str, str]:
        """Extract display values from an agent dict."""
        agent_id = agent.get("worker_name") or agent.get("agent_id", "?")
        status = agent.get("status", "idle")
        model = agent.get("model", agent.get("backend", ""))
        task_id = agent.get("task_id", "")
        elapsed = agent.get("elapsed", "")
        activity = agent.get("activity", "")
        tokens = agent.get("tokens_used", 0)
        if tokens and tokens >= 1000:
            tokens_str = f"{tokens // 1000}k"
        elif tokens:
            tokens_str = str(tokens)
        else:
            tokens_str = ""
        return {
            "agent_id": agent_id,
            "status": status,
            "task_id": task_id,
            "activity": activity,
            "model": model,
            "elapsed": elapsed,
            "tokens": tokens_str,
        }

    @staticmethod
    def _status_text(status: str) -> Text:
        icon = _AGENT_STATUS_ICONS.get(status, "?")
        style = {
            "running": "cyan bold",
            "idle": "dim",
            "exited": "red",
        }.get(status, "dim")
        return Text(f"{icon} {status}", style=style)

    def _rebuild(self) -> None:
        try:
            table = self.query_one("#agents-table", DataTable)
        except Exception:
            return

        new_map: dict[str, dict[str, str]] = {}
        new_order: list[str] = []
        for agent in self._agent_rows:
            rd = self._make_row_data(agent)
            aid = rd["agent_id"]
            new_map[aid] = rd
            new_order.append(aid)

        old_keys = set(self._prev_agent_map)
        new_keys = set(new_map)

        # Detect if order changed (requires full rebuild)
        order_changed = new_order != self._prev_order

        if order_changed or not self._prev_agent_map:
            # First build — full populate
            table.clear()
            for aid in new_order:
                rd = new_map[aid]
                table.add_row(
                    self._status_text(rd["status"]),
                    rd["agent_id"],
                    rd["task_id"],
                    rd["activity"],
                    rd["model"],
                    rd["elapsed"],
                    rd["tokens"],
                    key=aid,
                )
        else:
            # Differential update
            for removed_key in old_keys - new_keys:
                with contextlib.suppress(Exception):
                    table.remove_row(removed_key)

            for added_key in new_keys - old_keys:
                rd = new_map[added_key]
                table.add_row(
                    self._status_text(rd["status"]),
                    rd["agent_id"],
                    rd["task_id"],
                    rd["activity"],
                    rd["model"],
                    rd["elapsed"],
                    rd["tokens"],
                    key=added_key,
                )

            col_keys = list(table.columns.keys())
            for aid in old_keys & new_keys:
                old_rd = self._prev_agent_map[aid]
                new_rd = new_map[aid]
                field_to_col = [
                    ("status", 0),
                    ("agent_id", 1),
                    ("task_id", 2),
                    ("activity", 3),
                    ("model", 4),
                    ("elapsed", 5),
                    ("tokens", 6),
                ]
                for field, col_idx in field_to_col:
                    if old_rd.get(field) != new_rd.get(field):
                        try:
                            if col_idx < len(col_keys):
                                value: Any = new_rd[field]
                                if field == "status":
                                    value = self._status_text(new_rd["status"])
                                table.update_cell(aid, col_keys[col_idx], value)
                        except Exception:
                            pass

        self._prev_agent_map = new_map
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
            self.post_message(self.AgentSelected(self._selected_key))
