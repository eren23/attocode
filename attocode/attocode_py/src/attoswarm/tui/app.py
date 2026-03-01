"""Textual app for attoswarm dashboard (operations view).

TabbedContent layout with 5 tabs:
  1. Overview  — Dependency tree + last 10 events
  2. Tasks     — DataTable + detail panel
  3. Agents    — DataTable + detail panel
  4. Events    — RichLog with color-coded events
  5. Messages  — Orchestrator-worker inbox/outbox
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Footer,
    Header,
    ProgressBar,
    Static,
    TabbedContent,
    TabPane,
)

from attoswarm.protocol.io import read_json, write_json_atomic
from attoswarm.protocol.models import utc_now_iso
from attoswarm.tui.stores import StateStore

from attocode.tui.widgets.swarm.agent_grid import AgentsDataTable
from attocode.tui.widgets.swarm.dag_view import DependencyTree
from attocode.tui.widgets.swarm.detail_inspector import DetailInspector
from attocode.tui.widgets.swarm.event_timeline import EventsLog
from attocode.tui.widgets.swarm.messages_log import MessagesLog
from attocode.tui.widgets.swarm.task_board import TasksDataTable

_CSS_PATH = Path(__file__).resolve().parent / "styles" / "swarm.tcss"


class SwarmSummaryBar(Static):
    """Always-visible 1-line summary: phase, counts, cost, elapsed."""

    def update_summary(
        self,
        phase: str = "",
        running: int = 0,
        done: int = 0,
        total: int = 0,
        failed: int = 0,
        cost: float = 0.0,
        elapsed: str = "",
    ) -> None:
        text = Text()
        # Phase
        phase_style = {
            "executing": "green bold",
            "completed": "green",
            "failed": "red bold",
            "paused": "yellow",
        }.get(phase, "bold")
        text.append(f" {phase.upper()} ", style=phase_style)
        text.append(" \u2502 ", style="dim")
        # Running
        text.append(f"{running} running ", style="cyan")
        text.append("\u2502 ", style="dim")
        # Done/Total
        text.append(f"{done}/{total} done ", style="green")
        # Failed
        if failed:
            text.append("\u2502 ", style="dim")
            text.append(f"{failed} failed ", style="red")
        text.append("\u2502 ", style="dim")
        # Cost
        text.append(f"${cost:.2f} ", style="yellow")
        # Elapsed
        if elapsed:
            text.append("\u2502 ", style="dim")
            text.append(f"{elapsed} ", style="dim")

        self.update(text)


class AttoswarmApp(App[None]):
    TITLE = "Attoswarm"

    CSS = _CSS_PATH.read_text(encoding="utf-8") if _CSS_PATH.exists() else ""

    BINDINGS = [
        Binding("1", "tab_overview", "Overview", show=False),
        Binding("2", "tab_tasks", "Tasks", show=False),
        Binding("3", "tab_agents", "Agents", show=False),
        Binding("4", "tab_events", "Events", show=False),
        Binding("5", "tab_messages", "Messages", show=False),
        Binding("p", "pause_resume", "Pause/Resume"),
        Binding("i", "inject_message", "Inject Message"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("f", "focus_agent", "Focus Agent"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, run_dir: str) -> None:
        super().__init__()
        self._store = StateStore(run_dir)
        self._last_events: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="swarm-outer"):
            # Summary bar + budget progress
            yield SwarmSummaryBar(id="summary-bar")
            yield ProgressBar(id="budget-progress", total=100, show_eta=False, show_percentage=True)

            # Tabbed content
            with TabbedContent(id="swarm-tabs"):
                # Tab 1: Overview
                with TabPane("Overview", id="tab-overview"):
                    with Horizontal(id="overview-container"):
                        with Vertical(id="overview-left"):
                            yield DependencyTree(id="dep-tree-widget")
                        with Vertical(id="overview-right"):
                            yield EventsLog(id="overview-events")

                # Tab 2: Tasks
                with TabPane("Tasks", id="tab-tasks"):
                    with Horizontal(id="tasks-container"):
                        with Vertical(id="tasks-table-container"):
                            yield TasksDataTable(id="tasks-dt")
                        with Vertical(id="task-detail-container"):
                            yield DetailInspector(id="task-detail")

                # Tab 3: Agents
                with TabPane("Agents", id="tab-agents"):
                    with Horizontal(id="agents-container"):
                        with Vertical(id="agents-table-container"):
                            yield AgentsDataTable(id="agents-dt")
                        with Vertical(id="agent-detail-container"):
                            yield DetailInspector(id="agent-detail")

                # Tab 4: Events
                with TabPane("Events", id="tab-events"):
                    yield EventsLog(id="events-full")

                # Tab 5: Messages
                with TabPane("Messages", id="tab-messages"):
                    yield MessagesLog(id="messages-log-widget")

        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.5, self._refresh)
        self._refresh()
        self._apply_responsive_classes()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_responsive_classes()

    def _apply_responsive_classes(self) -> None:
        w = self.size.width
        self.set_class(w < 100, "narrow")
        self.set_class(w < 80, "very-narrow")

    def _refresh(self) -> None:
        state = self._store.read_state()
        if not state:
            state = {}

        # ── Summary bar ──────────────────────────────────────────────
        dag_summary = state.get("dag_summary", {})
        elapsed_s = state.get("elapsed_s", 0)
        budget = state.get("budget", {})

        if isinstance(elapsed_s, (int, float)) and elapsed_s > 0:
            mins = int(elapsed_s) // 60
            secs = int(elapsed_s) % 60
            elapsed_str = f"{mins}m{secs:02d}s"
        else:
            elapsed_str = ""

        total_tasks = sum(dag_summary.values()) if isinstance(dag_summary, dict) else 0
        running = dag_summary.get("running", 0) if isinstance(dag_summary, dict) else 0
        done = dag_summary.get("done", 0) if isinstance(dag_summary, dict) else 0
        failed = dag_summary.get("failed", 0) if isinstance(dag_summary, dict) else 0

        try:
            self.query_one("#summary-bar", SwarmSummaryBar).update_summary(
                phase=state.get("phase", "unknown"),
                running=running,
                done=done,
                total=total_tasks,
                failed=failed,
                cost=float(budget.get("cost_used_usd", 0.0)),
                elapsed=elapsed_str,
            )
        except Exception:
            pass

        # Budget progress bar
        try:
            max_cost = float(budget.get("max_cost_usd", 1.0)) or 1.0
            cost_used = float(budget.get("cost_used_usd", 0.0))
            pct = min(100, int(cost_used / max_cost * 100))
            bar = self.query_one("#budget-progress", ProgressBar)
            bar.update(progress=pct)
        except Exception:
            pass

        # ── Task list (for Tasks tab + Overview tree) ────────────────
        tasks = self._store.build_task_list(state)
        dag_data = state.get("dag", {})

        try:
            self.query_one("#tasks-dt", TasksDataTable).update_tasks(tasks)
        except Exception:
            pass

        # ── Dependency tree (Overview tab) ───────────────────────────
        try:
            dag_nodes = self._store.build_dag_nodes(state)
            edges = dag_data.get("edges", [])
            self.query_one("#dep-tree-widget", DependencyTree).update_dag(dag_nodes, edges)
        except Exception:
            pass

        # ── Agent list (Agents tab) ──────────────────────────────────
        try:
            agents = self._store.build_agent_list(state)
            self.query_one("#agents-dt", AgentsDataTable).update_agents(agents)
        except Exception:
            pass

        # ── Events ───────────────────────────────────────────────────
        try:
            raw_events = self._store.read_events(limit=500)
            self._last_events = self._store.build_event_list(raw_events)

            # Overview tab: last 10 events
            self.query_one("#overview-events", EventsLog).update_events(
                self._last_events[-10:]
            )
            # Full events tab
            self.query_one("#events-full", EventsLog).update_events(self._last_events)
        except Exception:
            pass

        # ── Messages ─────────────────────────────────────────────────
        try:
            messages = self._store.read_all_messages()
            self.query_one("#messages-log-widget", MessagesLog).update_messages(messages)
        except Exception:
            pass

    # ── Selection handlers ───────────────────────────────────────────

    def on_tasks_data_table_task_selected(
        self, event: TasksDataTable.TaskSelected
    ) -> None:
        state = self._store.read_state()
        detail = self._store.build_task_detail(event.task_id, state=state)
        if detail:
            try:
                self.query_one("#task-detail", DetailInspector).inspect(detail)
            except Exception:
                pass

    def on_agents_data_table_agent_selected(
        self, event: AgentsDataTable.AgentSelected
    ) -> None:
        state = self._store.read_state()
        detail = self._store.build_agent_detail(event.agent_id, state)
        if detail:
            try:
                self.query_one("#agent-detail", DetailInspector).inspect(detail)
            except Exception:
                pass

    def on_dependency_tree_node_selected(
        self, event: DependencyTree.NodeSelected
    ) -> None:
        """When a tree node is selected, show task detail and switch to Tasks tab."""
        state = self._store.read_state()
        detail = self._store.build_task_detail(event.task_id, state=state)
        if detail:
            try:
                self.query_one("#task-detail", DetailInspector).inspect(detail)
            except Exception:
                pass

    # ── Tab switching actions ─────────────────────────────────────────

    def _switch_tab(self, tab_id: str) -> None:
        try:
            tabs = self.query_one("#swarm-tabs", TabbedContent)
            tabs.active = tab_id
        except Exception:
            pass

    def action_tab_overview(self) -> None:
        self._switch_tab("tab-overview")

    def action_tab_tasks(self) -> None:
        self._switch_tab("tab-tasks")

    def action_tab_agents(self) -> None:
        self._switch_tab("tab-agents")

    def action_tab_events(self) -> None:
        self._switch_tab("tab-events")

    def action_tab_messages(self) -> None:
        self._switch_tab("tab-messages")

    # ── Other actions ─────────────────────────────────────────────────

    def action_refresh_now(self) -> None:
        self._refresh()

    def action_pause_resume(self) -> None:
        state_path = Path(self._store.state_path)
        state = read_json(state_path, default={})
        phase = state.get("phase", "executing")
        state["phase"] = "paused" if phase != "paused" else "executing"
        state["updated_at"] = utc_now_iso()
        write_json_atomic(state_path, state)

    def action_inject_message(self) -> None:
        state = self._store.read_state()
        agent_rows = state.get("active_agents", [])
        if not agent_rows:
            self.notify("No agents available for message injection", severity="warning")
            return
        agent_id = str(agent_rows[0].get("agent_id", ""))
        inbox_path = Path(self._store.run_dir) / "agents" / f"agent-{agent_id}.inbox.json"
        inbox = read_json(
            inbox_path,
            default={"schema_version": "1.0", "agent_id": agent_id, "next_seq": 1, "messages": []},
        )
        next_seq = int(inbox.get("next_seq", 1))
        inbox.setdefault("messages", []).append(
            {
                "seq": next_seq,
                "message_id": f"manual-{next_seq}",
                "timestamp": utc_now_iso(),
                "kind": "control",
                "task_id": None,
                "payload": {"message": "Manual intervention from TUI"},
                "requires_ack": False,
            }
        )
        inbox["next_seq"] = next_seq + 1
        write_json_atomic(inbox_path, inbox)
        self.notify(f"Injected control message to {agent_id}")

    def action_focus_agent(self) -> None:
        """Push FocusScreen for single-agent stream view."""
        from attocode.tui.screens.focus_screen import FocusScreen

        self.push_screen(FocusScreen(state_fn=self._state_fn_adapter))

    # ── Helpers ──────────────────────────────────────────────────────

    def _state_fn_adapter(self) -> dict[str, Any]:
        """Adapter that wraps StateStore for FocusScreen/TimelineScreen."""
        state = self._store.read_state()
        state["events"] = self._last_events
        return state
