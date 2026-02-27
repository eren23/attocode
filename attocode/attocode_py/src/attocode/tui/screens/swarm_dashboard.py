"""Swarm Dashboard Screen — 8-tab full-screen swarm dashboard.

Tabs:
1. Overview — existing layout compressed (AgentGrid, TaskBoard, DAG, Timeline)
2. Workers — deep agent monitoring with detail cards and stream view
3. Tasks — comprehensive inspector with DataTable + deep detail
4. Models — model health dashboard
5. Decisions — decision log and error summary
6. Files — file activity, artifacts, conflicts
7. Quality — quality gates, hollows, wave reviews
8. AST/BB — AST explorer + blackboard inspector
"""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import ContentSwitcher, Footer, Header, Static

from attocode.tui.widgets.swarm.ast_blackboard_pane import ASTBlackboardPane
from attocode.tui.widgets.swarm.decisions_pane import DecisionsPane
from attocode.tui.widgets.swarm.files_pane import FilesPane
from attocode.tui.widgets.swarm.model_health_pane import ModelHealthPane
from attocode.tui.widgets.swarm.overview_pane import OverviewPane
from attocode.tui.widgets.swarm.quality_pane import QualityPane
from attocode.tui.widgets.swarm.agent_grid import AgentCard
from attocode.tui.widgets.swarm.task_board import TaskCard
from attocode.tui.widgets.swarm.tasks_pane import TasksPane
from attocode.tui.widgets.swarm.workers_pane import WorkersPane


_TAB_LABELS = [
    "1:Overview",
    "2:Workers",
    "3:Tasks",
    "4:Models",
    "5:Decisions",
    "6:Files",
    "7:Quality",
    "8:AST/BB",
]

_TAB_IDS = [
    "tab-overview",
    "tab-workers",
    "tab-tasks",
    "tab-models",
    "tab-decisions",
    "tab-files",
    "tab-quality",
    "tab-astbb",
]


class TabBar(Static):
    """Horizontal tab bar with numbered labels."""

    DEFAULT_CSS = """
    TabBar {
        height: 1;
        background: $boost;
        padding: 0 1;
    }
    """

    active_tab: reactive[int] = reactive(0)

    def render(self) -> Text:
        text = Text()
        for i, label in enumerate(_TAB_LABELS):
            if i == self.active_tab:
                text.append(f" [{label}] ", style="bold reverse")
            else:
                text.append(f" {label} ", style="dim")
            if i < len(_TAB_LABELS) - 1:
                text.append("\u2502", style="dim")
        return text

    def watch_active_tab(self) -> None:
        self.refresh()


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
    """Full-screen 8-tab swarm orchestration dashboard."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back", show=True),
        Binding("1", "tab_1", "Overview", show=False),
        Binding("2", "tab_2", "Workers", show=False),
        Binding("3", "tab_3", "Tasks", show=False),
        Binding("4", "tab_4", "Models", show=False),
        Binding("5", "tab_5", "Decisions", show=False),
        Binding("6", "tab_6", "Files", show=False),
        Binding("7", "tab_7", "Quality", show=False),
        Binding("8", "tab_8", "AST/BB", show=False),
        Binding("ctrl+f", "focus_agent", "Focus Agent", show=True),
        Binding("tab", "next_tab", "Next Tab", show=True),
    ]

    DEFAULT_CSS = """
    SwarmDashboardScreen {
        background: $surface;
    }
    SwarmDashboardScreen #swarm-content {
        height: 1fr;
    }
    """

    active_tab: reactive[int] = reactive(0)

    def __init__(
        self,
        state_fn: Any = None,
        event_bridge: Any = None,
        blackboard: Any = None,
        ast_service: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._state_fn = state_fn
        self._event_bridge = event_bridge
        self._blackboard = blackboard
        self._ast_service = ast_service
        self._poll_timer: Timer | None = None
        self._swarm_start_ts: float = 0.0

    def compose(self) -> ComposeResult:
        yield Header()
        yield TabBar(id="swarm-tab-bar")
        with ContentSwitcher(id="swarm-content", initial="tab-overview"):
            yield OverviewPane(id="tab-overview")
            yield WorkersPane(id="tab-workers")
            yield TasksPane(id="tab-tasks")
            yield ModelHealthPane(id="tab-models")
            yield DecisionsPane(id="tab-decisions")
            yield FilesPane(id="tab-files")
            yield QualityPane(id="tab-quality")
            yield ASTBlackboardPane(
                ast_service=self._ast_service,
                blackboard=self._blackboard,
                id="tab-astbb",
            )
        yield SwarmStatusFooter(id="swarm-status-footer")
        yield Footer()

    def on_mount(self) -> None:
        self._poll_timer = self.set_interval(1.0, self._poll_state)

    def on_unmount(self) -> None:
        if self._poll_timer:
            self._poll_timer.stop()

    def _switch_tab(self, index: int) -> None:
        """Switch to the given tab index (0-7)."""
        if 0 <= index < len(_TAB_IDS):
            self.active_tab = index
            try:
                self.query_one("#swarm-tab-bar", TabBar).active_tab = index
                self.query_one("#swarm-content", ContentSwitcher).current = _TAB_IDS[index]
            except Exception:
                pass

    def watch_active_tab(self, value: int) -> None:
        pass

    def _poll_state(self) -> None:
        """Poll orchestrator state and update the active pane."""
        state = self._get_state()
        if not state:
            return

        # Update footer
        self._update_footer(state)

        # Only update the active pane for efficiency
        tab_id = _TAB_IDS[self.active_tab] if 0 <= self.active_tab < len(_TAB_IDS) else "tab-overview"

        try:
            if tab_id == "tab-overview":
                self.query_one("#tab-overview", OverviewPane).update_state(state)
            elif tab_id == "tab-workers":
                self.query_one("#tab-workers", WorkersPane).update_state(state)
            elif tab_id == "tab-tasks":
                self.query_one("#tab-tasks", TasksPane).update_state(state)
            elif tab_id == "tab-models":
                self.query_one("#tab-models", ModelHealthPane).update_state(state)
            elif tab_id == "tab-decisions":
                self.query_one("#tab-decisions", DecisionsPane).update_state(state)
            elif tab_id == "tab-files":
                self.query_one("#tab-files", FilesPane).update_state(state)
            elif tab_id == "tab-quality":
                self.query_one("#tab-quality", QualityPane).update_state(state)
            elif tab_id == "tab-astbb":
                output_dir = ""
                if self._event_bridge and hasattr(self._event_bridge, "_output_dir"):
                    output_dir = self._event_bridge._output_dir
                self.query_one("#tab-astbb", ASTBlackboardPane).update_state(
                    state, output_dir=output_dir
                )
        except Exception:
            pass

    def _get_state(self) -> dict[str, Any] | None:
        """Get state from event bridge (preferred) or state_fn."""
        if self._event_bridge and hasattr(self._event_bridge, "get_live_state"):
            try:
                return self._event_bridge.get_live_state()
            except Exception:
                pass
        if self._state_fn:
            try:
                return self._state_fn()
            except Exception:
                pass
        return None

    def _update_footer(self, state: dict[str, Any]) -> None:
        """Update the status footer from state."""
        status = state.get("status", {})
        queue = status.get("queue", {})
        budget = status.get("budget", {})

        active = len(status.get("active_workers", []))
        done = queue.get("completed", 0)
        total = queue.get("total", 0)
        cost = budget.get("cost_used", 0.0)
        phase = status.get("phase", "?")

        # Compute elapsed from swarm start time (first event timestamp or mount time)
        elapsed_str = ""
        if self._swarm_start_ts > 0:
            elapsed_s = int(time.time() - self._swarm_start_ts)
            if elapsed_s < 60:
                elapsed_str = f"{elapsed_s}s"
            elif elapsed_s < 3600:
                elapsed_str = f"{elapsed_s // 60}m{elapsed_s % 60:02d}s"
            else:
                h, rem = divmod(elapsed_s, 3600)
                elapsed_str = f"{h}h{rem // 60:02d}m"
        else:
            # Initialize from state timeline or current time
            timeline = state.get("timeline", [])
            if timeline:
                first_ts = timeline[0].get("timestamp", 0)
                if first_ts:
                    self._swarm_start_ts = first_ts

        try:
            self.query_one("#swarm-status-footer", SwarmStatusFooter).update_status(
                phase=phase,
                level=str(status.get("current_wave", "?")),
                active=active,
                done=done,
                total=total,
                cost=cost,
                elapsed=elapsed_str,
            )
        except Exception:
            pass

    # --- Message handlers ---

    def on_task_card_selected(self, message: TaskCard.Selected) -> None:
        """Handle TaskCard click — switch to Tasks tab and select that task."""
        self._switch_tab(2)  # tab index 2 = Tasks
        try:
            tasks_pane = self.query_one("#tab-tasks", TasksPane)
            tasks_pane.select_task(message.task_id)
        except Exception:
            pass

    def on_agent_card_selected(self, message: AgentCard.Selected) -> None:
        """Handle AgentCard click — switch to Workers tab and filter events."""
        self._switch_tab(1)  # tab index 1 = Workers
        # Look up the task_id from the agent_id in active workers
        agent_id = message.agent_id
        state = self._get_state()
        if state:
            workers = state.get("status", {}).get("active_workers", [])
            for w in workers:
                if w.get("worker_name", "") == agent_id:
                    task_id = w.get("task_id", "")
                    if task_id:
                        try:
                            workers_pane = self.query_one("#tab-workers", WorkersPane)
                            workers_pane.filter_for_task(task_id)
                        except Exception:
                            pass
                    break

    # --- Tab actions ---

    def action_tab_1(self) -> None:
        self._switch_tab(0)

    def action_tab_2(self) -> None:
        self._switch_tab(1)

    def action_tab_3(self) -> None:
        self._switch_tab(2)

    def action_tab_4(self) -> None:
        self._switch_tab(3)

    def action_tab_5(self) -> None:
        self._switch_tab(4)

    def action_tab_6(self) -> None:
        self._switch_tab(5)

    def action_tab_7(self) -> None:
        self._switch_tab(6)

    def action_tab_8(self) -> None:
        self._switch_tab(7)

    def action_next_tab(self) -> None:
        self._switch_tab((self.active_tab + 1) % len(_TAB_IDS))

    def action_dismiss(self) -> None:
        self.app.pop_screen()

    def action_focus_agent(self) -> None:
        """Push FocusScreen for the selected agent."""
        from attocode.tui.screens.focus_screen import FocusScreen
        self.app.push_screen(FocusScreen(state_fn=self._state_fn))
