"""Focus Screen — single-agent stream view with composed widgets.

Shows detailed output from a single agent:
- WorkerDetailCard header
- Left: EventTimeline filtered to this agent's task_id
- Right: Token usage sparkline over time
Navigate between agents with left/right arrows.
"""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Header, Static

from attocode.tui.widgets.swarm.event_timeline import EventTimeline
from attocode.tui.widgets.swarm.workers_pane import WorkerDetailCard


class FocusScreen(Screen):
    """Enhanced single-agent focus view with composed widgets."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back", show=True),
        Binding("left", "prev_agent", "Prev Agent", show=True),
        Binding("right", "next_agent", "Next Agent", show=True),
    ]

    DEFAULT_CSS = """
    FocusScreen {
        background: $surface;
    }
    #focus-header-card {
        height: auto;
        min-height: 4;
    }
    #focus-middle {
        height: 1fr;
    }
    #focus-events {
        width: 2fr;
    }
    #focus-detail {
        width: 1fr;
        overflow-y: auto;
        padding: 0 1;
        border-left: solid $accent;
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
        self._token_history: list[int] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static("", id="focus-header-card")
            with Horizontal(id="focus-middle"):
                yield EventTimeline(id="focus-events")
                yield Static("", id="focus-detail")
        yield Static("", id="focus-status")
        yield Footer()

    def on_mount(self) -> None:
        self._poll_timer = self.set_interval(1.0, self._poll)

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

        # Get workers list from event bridge state or swarm state
        workers = state.get("status", {}).get("active_workers", [])
        if not workers:
            workers = state.get("active_agents", [])
        self._agents = workers

        if not self._agents:
            try:
                self.query_one("#focus-header-card", Static).update(
                    Text("No active agents", style="dim italic")
                )
            except Exception:
                pass
            return

        self._agent_index = max(0, min(self._agent_index, len(self._agents) - 1))
        agent = self._agents[self._agent_index]

        # Header card
        try:
            header_text = Text()
            worker_name = agent.get("worker_name", agent.get("agent_id", "?"))
            header_text.append(f"Focus: {worker_name}", style="bold cyan")
            model = agent.get("model", "")
            if model:
                header_text.append(f" ({model})", style="dim")
            header_text.append("\n")
            task_id = agent.get("task_id", "none")
            header_text.append(f"Task: {task_id}", style="italic")
            desc = agent.get("task_description", "")
            if desc:
                header_text.append(f" — {desc[:60]}", style="dim")
            header_text.append("\n")
            started = agent.get("started_at", 0)
            if started:
                elapsed = int(time.time() - started)
                header_text.append(f"Running: {elapsed}s", style="dim")
            self.query_one("#focus-header-card", Static).update(header_text)
        except Exception:
            pass

        # Event timeline filtered to this agent's task_id
        task_id = agent.get("task_id", "")
        timeline = state.get("timeline", state.get("events", []))
        filtered = [
            e for e in timeline
            if e.get("task_id") == task_id
        ] if task_id else timeline[-30:]

        try:
            self.query_one("#focus-events", EventTimeline).update_events(filtered)
        except Exception:
            pass

        # Detail panel — show token/cost stats
        try:
            detail_text = Text()
            detail_text.append("Agent Stats\n", style="bold underline")
            detail_text.append("\n")

            # Count events
            event_count = len(filtered)
            detail_text.append(f"Events: {event_count}\n", style="dim")

            # Token sparkline (simple text representation)
            if self._token_history:
                detail_text.append("\nToken History:\n", style="bold")
                max_val = max(self._token_history) if self._token_history else 1
                for val in self._token_history[-10:]:
                    bar_len = int((val / max(1, max_val)) * 20)
                    detail_text.append(f"  {'█' * bar_len} {val:,}\n", style="cyan dim")

            self.query_one("#focus-detail", Static).update(detail_text)
        except Exception:
            pass

        # Status bar
        try:
            status_text = Text()
            status_text.append(
                f"[{self._agent_index + 1}/{len(self._agents)}] ", style="bold"
            )
            status_text.append(
                "[←/→] prev/next agent  [Esc] back", style="dim"
            )
            self.query_one("#focus-status", Static).update(status_text)
        except Exception:
            pass

    def action_dismiss(self) -> None:
        self.app.pop_screen()

    def action_prev_agent(self) -> None:
        if self._agents:
            self._agent_index = (self._agent_index - 1) % len(self._agents)

    def action_next_agent(self) -> None:
        if self._agents:
            self._agent_index = (self._agent_index + 1) % len(self._agents)
