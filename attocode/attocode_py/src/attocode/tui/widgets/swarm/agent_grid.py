"""Agent Grid — shows live status of each worker agent."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


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

    def update_data(
        self,
        status: str = "idle",
        task_id: str = "",
        model: str = "",
        tokens: int = 0,
        elapsed: str = "",
    ) -> None:
        self._status = status
        self._task_id = task_id
        self._model = model
        self._tokens = tokens
        self._elapsed = elapsed

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
            text.append(f"  {self._task_id[:18]}", style="italic")
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

        for agent in agents:
            card = AgentCard(agent_id=agent.get("agent_id", "?"))
            row.mount(card)
            card.update_data(
                status=agent.get("status", "idle"),
                task_id=agent.get("task_id", ""),
                model=agent.get("model", ""),
                tokens=agent.get("tokens_used", 0),
                elapsed=agent.get("elapsed", ""),
            )
