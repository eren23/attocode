"""Focus Screen — single-agent stream view.

Shows detailed output from a single agent: tool calls, LLM responses,
iteration progress.  Navigate between agents with left/right arrows.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Header, Static


class FocusScreen(Screen):
    """Single-agent focus view."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back", show=True),
        Binding("left", "prev_agent", "Prev Agent", show=True),
        Binding("right", "next_agent", "Next Agent", show=True),
    ]

    DEFAULT_CSS = """
    FocusScreen {
        background: $surface;
    }
    #focus-header {
        height: 3;
        border: solid $accent;
        padding: 0 2;
    }
    #focus-body {
        height: 1fr;
        overflow-y: auto;
        padding: 0 2;
    }
    #focus-status {
        dock: bottom;
        height: 1;
        background: $surface-lighten-1;
        padding: 0 2;
    }
    """

    def __init__(
        self,
        state_fn: Any = None,
        agent_index: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._state_fn = state_fn
        self._agent_index = agent_index
        self._agents: list[dict[str, Any]] = []
        self._poll_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static("", id="focus-header")
            yield Static("", id="focus-body")
        yield Static("", id="focus-status")
        yield Footer()

    def on_mount(self) -> None:
        self._poll_timer = self.set_interval(0.5, self._poll)

    def on_unmount(self) -> None:
        if self._poll_timer:
            self._poll_timer.stop()

    def _poll(self) -> None:
        if not self._state_fn:
            return
        try:
            state = self._state_fn()
        except Exception:
            return

        self._agents = state.get("active_agents", [])
        if not self._agents:
            self.query_one("#focus-header", Static).update(
                Text("No active agents", style="dim italic")
            )
            return

        self._agent_index = max(0, min(self._agent_index, len(self._agents) - 1))
        agent = self._agents[self._agent_index]

        # Header
        header_text = Text()
        header_text.append(f"Focus: {agent.get('agent_id', '?')}", style="bold cyan")
        if agent.get("model"):
            header_text.append(f" ({agent['model']})", style="dim")
        header_text.append("\n")
        header_text.append(f"Task: {agent.get('task_id', 'none')}", style="italic")
        header_text.append(f"  Status: {agent.get('status', '?')}")
        self.query_one("#focus-header", Static).update(header_text)

        # Body: show recent activity
        body = Text()
        events = state.get("events", [])
        agent_events = [
            e for e in events
            if e.get("agent_id") == agent.get("agent_id")
            or e.get("task_id") == agent.get("task_id")
        ]
        for event in agent_events[-20:]:
            etype = event.get("type", "info")
            msg = event.get("message", "")
            body.append(f"  [{etype}] {msg}\n")
        if not agent_events:
            body.append("  (no events for this agent yet)\n", style="dim")
        self.query_one("#focus-body", Static).update(body)

        # Status bar
        status_text = Text()
        status_text.append(
            f"[{self._agent_index + 1}/{len(self._agents)}] ", style="bold"
        )
        status_text.append(
            "[<-/->] prev/next agent  [Esc] dashboard", style="dim"
        )
        self.query_one("#focus-status", Static).update(status_text)

    def action_dismiss(self) -> None:
        self.app.pop_screen()

    def action_prev_agent(self) -> None:
        if self._agents:
            self._agent_index = (self._agent_index - 1) % len(self._agents)

    def action_next_agent(self) -> None:
        if self._agents:
            self._agent_index = (self._agent_index + 1) % len(self._agents)
