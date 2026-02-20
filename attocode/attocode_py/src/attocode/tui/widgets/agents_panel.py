"""Active agents panel widget."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.widgets import Static


@dataclass
class ActiveAgentInfo:
    """Information about an active subagent."""

    agent_id: str
    task: str
    status: str = "running"  # running, completed, error
    tokens: int = 0
    elapsed_s: float = 0.0
    iteration: int = 0


class AgentsPanel(Static):
    """Displays active subagents."""

    DEFAULT_CSS = """
    AgentsPanel {
        height: auto;
        max-height: 8;
        border: round $primary-darken-2;
        padding: 0 1;
        display: none;
    }

    AgentsPanel.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agents: dict[str, ActiveAgentInfo] = {}

    def update_agent(self, info: ActiveAgentInfo) -> None:
        """Add or update an agent."""
        self._agents[info.agent_id] = info
        self._agents = {
            k: v
            for k, v in self._agents.items()
            if v.status == "running" or v.elapsed_s < 30
        }
        self.set_class(len(self._agents) > 0, "visible")
        self.refresh()

    def remove_agent(self, agent_id: str) -> None:
        """Remove an agent."""
        self._agents.pop(agent_id, None)
        self.set_class(len(self._agents) > 0, "visible")
        self.refresh()

    def render(self) -> Text:
        if not self._agents:
            return Text("")

        text = Text()
        text.append("Agents", style="bold")
        text.append(f" ({len(self._agents)} active)\n", style="dim")

        for agent in self._agents.values():
            if agent.status == "running":
                text.append("  \u27f3 ", style="yellow")
            elif agent.status == "completed":
                text.append("  \u2713 ", style="green")
            else:
                text.append("  \u2717 ", style="red")

            style = "bold" if agent.status == "running" else "dim"
            text.append(f"{agent.task[:40]} ", style=style)
            text.append(
                f"| {agent.tokens:,}tok | {agent.elapsed_s:.0f}s", style="dim"
            )
            if agent.iteration > 0:
                text.append(f" | iter {agent.iteration}", style="dim")
            text.append("\n")

        return text
