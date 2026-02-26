"""Swarm Dashboard Screen — full-screen swarm overview.

Layout (120x40):
- Top: Agent Grid (live status cards)
- Middle: Task Board (kanban) | Dependency DAG
- Bottom: Event Timeline
- Footer: Phase, wave, active count, done count, cost, elapsed
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Header, Static

from attocode.tui.widgets.swarm.agent_grid import AgentGrid
from attocode.tui.widgets.swarm.dag_view import DependencyDAGView
from attocode.tui.widgets.swarm.detail_inspector import DetailInspector
from attocode.tui.widgets.swarm.event_timeline import EventTimeline
from attocode.tui.widgets.swarm.file_activity_map import FileActivityMap
from attocode.tui.widgets.swarm.task_board import TaskBoard


class SwarmStatusFooter(Static):
    """Status bar at the bottom of the swarm dashboard."""

    DEFAULT_CSS = """
    SwarmStatusFooter {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 2;
    }
    """

    def update_status(
        self,
        phase: str = "",
        level: str = "",
        active: int = 0,
        done: int = 0,
        total: int = 0,
        cost: float = 0.0,
        elapsed: str = "",
    ) -> None:
        text = Text()
        text.append(f" Phase: {phase} ", style="bold")
        text.append("\u2502 ", style="dim")
        text.append(f"Level {level} ", style="cyan")
        text.append("\u2502 ", style="dim")
        text.append(f"{active} active ", style="yellow")
        text.append("\u2502 ", style="dim")
        text.append(f"{done}/{total} done ", style="green")
        text.append("\u2502 ", style="dim")
        text.append(f"${cost:.2f} ", style="magenta")
        text.append("\u2502 ", style="dim")
        text.append(elapsed, style="dim")
        self.update(text)


class SwarmDashboardScreen(Screen):
    """Full-screen swarm orchestration dashboard."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back", show=True),
        Binding("ctrl+f", "focus_agent", "Focus Agent", show=True),
        Binding("ctrl+t", "fullscreen_timeline", "Timeline", show=True),
        Binding("tab", "cycle_focus", "Cycle Panel", show=True),
        Binding("f", "toggle_filter", "Filter Events", show=True),
    ]

    DEFAULT_CSS = """
    SwarmDashboardScreen {
        background: $surface;
    }
    SwarmDashboardScreen > Vertical {
        height: 100%;
    }
    #swarm-middle {
        height: 1fr;
    }
    #swarm-left {
        width: 2fr;
    }
    #swarm-right {
        width: 1fr;
    }
    """

    def __init__(
        self,
        state_fn: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._state_fn = state_fn  # Callable that returns orchestrator state dict
        self._poll_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            # Top: Agent Grid
            yield AgentGrid(id="swarm-agent-grid")

            # Middle: Task Board + DAG
            with Horizontal(id="swarm-middle"):
                with Vertical(id="swarm-left"):
                    yield TaskBoard(id="swarm-task-board")
                with Vertical(id="swarm-right"):
                    yield DependencyDAGView(id="swarm-dag-view")
                    yield DetailInspector(id="swarm-detail")

            # Bottom: Event Timeline
            yield EventTimeline(id="swarm-timeline")

        yield SwarmStatusFooter(id="swarm-status-footer")
        yield Footer()

    def on_mount(self) -> None:
        self._poll_timer = self.set_interval(0.5, self._poll_state)
        self._apply_responsive_classes()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_responsive_classes()

    def _apply_responsive_classes(self) -> None:
        w = self.size.width
        self.set_class(w < 100, "narrow")
        self.set_class(w < 80, "very-narrow")

    def on_unmount(self) -> None:
        if self._poll_timer:
            self._poll_timer.stop()

    def _poll_state(self) -> None:
        """Poll orchestrator state and update widgets."""
        if not self._state_fn:
            return
        try:
            state = self._state_fn()
        except Exception:
            return

        if not state:
            return

        # Update Agent Grid
        agents = state.get("active_agents", [])
        try:
            self.query_one("#swarm-agent-grid", AgentGrid).update_agents(agents)
        except Exception:
            pass

        # Update Task Board
        tasks = state.get("tasks", {})
        task_list = [
            {"task_id": tid, "title": t.get("title", ""), "status": t.get("status", "pending")}
            for tid, t in tasks.items()
        ]
        try:
            self.query_one("#swarm-task-board", TaskBoard).update_tasks(task_list)
        except Exception:
            pass

        # Update DAG
        dag_nodes = [
            {"task_id": tid, "status": t.get("status", "pending"), "level": 0}
            for tid, t in tasks.items()
        ]
        try:
            self.query_one("#swarm-dag-view", DependencyDAGView).update_dag(dag_nodes)
        except Exception:
            pass

        # Update Timeline
        events = state.get("events", [])
        try:
            self.query_one("#swarm-timeline", EventTimeline).update_events(events)
        except Exception:
            pass

        # Update footer
        summary = state.get("dag_summary", {})
        budget = state.get("budget", {})
        elapsed = state.get("elapsed_s", 0)
        mins = int(elapsed) // 60
        secs = int(elapsed) % 60
        try:
            self.query_one("#swarm-status-footer", SwarmStatusFooter).update_status(
                phase=state.get("phase", "?"),
                level="?",
                active=summary.get("running", 0),
                done=summary.get("done", 0),
                total=sum(summary.values()),
                cost=budget.get("cost_usd", 0),
                elapsed=f"{mins}m{secs:02d}s",
            )
        except Exception:
            pass

    # --- Actions ---

    def action_dismiss(self) -> None:
        self.app.pop_screen()

    def action_focus_agent(self) -> None:
        """Push FocusScreen for the selected agent."""
        from attocode.tui.screens.focus_screen import FocusScreen
        self.app.push_screen(FocusScreen(state_fn=self._state_fn))

    def action_fullscreen_timeline(self) -> None:
        """Push TimelineScreen for full-screen event view."""
        from attocode.tui.screens.timeline_screen import TimelineScreen
        events = []
        if self._state_fn:
            try:
                state = self._state_fn()
                events = state.get("events", [])
            except Exception:
                pass
        self.app.push_screen(TimelineScreen(events=events))

    def action_cycle_focus(self) -> None:
        """Cycle focus between panels."""
        self.focus_next()

    def action_toggle_filter(self) -> None:
        """Toggle event type filter on the timeline."""
        try:
            timeline = self.query_one("#swarm-timeline", EventTimeline)
            if timeline.filter_type:
                timeline.filter_type = ""
            else:
                timeline.filter_type = "spawn"
        except Exception:
            pass
