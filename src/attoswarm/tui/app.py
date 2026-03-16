"""Textual app for attoswarm dashboard (operations view).

TabbedContent layout with 5 tabs:
  1. Overview  — Dependency tree + last 10 events
  2. Tasks     — DataTable + detail panel
  3. Agents    — DataTable + detail panel
  4. Events    — RichLog with color-coded events
  5. Messages  — Orchestrator-worker inbox/outbox
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Footer,
    Header,
    Input,
    ProgressBar,
    Static,
    TabbedContent,
    TabPane,
)

from attocode.tui.widgets.swarm.agent_grid import AgentCard, AgentsDataTable
from attocode.tui.widgets.swarm.agent_trace_stream import AgentTraceStream
from attocode.tui.widgets.swarm.budget_projection_widget import BudgetProjectionWidget
from attocode.tui.widgets.swarm.conflict_panel import ConflictPanel
from attocode.tui.widgets.swarm.decisions_pane import DecisionsPane
from attocode.tui.widgets.swarm.detail_inspector import DetailInspector
from attocode.tui.widgets.swarm.event_timeline import EventsLog
from attocode.tui.widgets.swarm.failure_chain_widget import FailureChainWidget
from attocode.tui.widgets.swarm.messages_log import MessagesLog
from attocode.tui.widgets.swarm.overview_pane import OverviewPane
from attocode.tui.widgets.swarm.task_board import TaskCard, TasksDataTable
from attoswarm.protocol.io import read_json, write_json_atomic
from attoswarm.protocol.models import utc_now_iso
from attoswarm.tui.stores import StateStore

if TYPE_CHECKING:
    from textual import events
    from textual.widgets import Input, TextArea

    from attocode.tui.widgets.swarm.dag_view import DependencyTree

_CSS_PATH = Path(__file__).resolve().parent / "styles" / "swarm.tcss"


class SwarmSummaryBar(Static):
    """Always-visible 1-line summary: phase, counts, cost, elapsed + live activity."""

    def update_summary(
        self,
        phase: str = "",
        running: int = 0,
        done: int = 0,
        total: int = 0,
        failed: int = 0,
        cost: float = 0.0,
        elapsed: str = "",
        active_agents: int = 0,
        pending: int = 0,
        agent_activities: list[dict[str, str]] | None = None,
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
        # Active agents
        if active_agents:
            suffix = "s" if active_agents != 1 else ""
            text.append(f"{active_agents} agent{suffix} ", style="magenta")
            text.append("\u2502 ", style="dim")
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
        # Live agent activity snapshot
        if agent_activities:
            text.append("\u2502 ", style="dim")
            shown = agent_activities[:3]
            parts = []
            for aa in shown:
                tid = aa.get("task_id", "")
                act = aa.get("activity", "")
                if tid and act:
                    parts.append(f"{tid} ({act})")
                elif tid:
                    parts.append(tid)
            if parts:
                text.append(", ".join(parts), style="italic dim")
            remaining = len(agent_activities) - len(shown)
            if remaining > 0:
                text.append(f" +{remaining} more", style="dim")
        # Abandoned tasks hint
        if phase == "completed" and pending > 0:
            text.append("\u2502 ", style="dim")
            text.append(f"{pending} abandoned ", style="yellow bold")
            text.append("(resume with: attoswarm resume <run_dir>)", style="yellow dim")

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
        Binding("6", "tab_decisions", "Decisions", show=False),
        Binding("p", "pause_resume", "Pause/Resume"),
        Binding("i", "inject_message", "Inject Message"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("f", "focus_agent", "Focus Agent"),
        Binding("g", "show_graph", "Graph"),
        Binding("t", "show_timeline", "Timeline"),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, run_dir: str) -> None:
        super().__init__()
        self._store = StateStore(run_dir)
        self._last_events: list[dict[str, Any]] = []
        self._tab_switching = False
        self._refreshing = False
        self._last_state: dict[str, Any] | None = None
        self._last_seq: int = -1
        self._trace_timer: Any = None
        self._focused_agent_task: str | None = None
        self._completion_shown: bool = False
        self._last_summary_key: tuple[str, int, int, int, int, int, int] | None = None
        self._last_refreshed_tab: str = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="swarm-outer"):
            # Summary bar + budget progress + breakdown
            yield SwarmSummaryBar(id="summary-bar")
            yield ProgressBar(id="budget-progress", total=100, show_eta=False, show_percentage=True)
            yield Static("", id="budget-breakdown")

            # Tabbed content
            with TabbedContent(id="swarm-tabs"):
                # Tab 1: Overview (rich 2x2 grid)
                with TabPane("Overview", id="tab-overview"):
                    yield OverviewPane(id="overview-pane")

                # Tab 2: Tasks
                with TabPane("Tasks", id="tab-tasks"), Horizontal(id="tasks-container"):
                    with Vertical(id="tasks-table-container"):
                        yield TasksDataTable(id="tasks-dt")
                    with Vertical(id="task-detail-container"):
                        yield DetailInspector(id="task-detail")

                # Tab 3: Agents
                with TabPane("Agents", id="tab-agents"), Horizontal(id="agents-container"):
                    with Vertical(id="agents-table-container"):
                        yield AgentsDataTable(id="agents-dt")
                    with Vertical(id="agent-detail-container"):
                        yield DetailInspector(id="agent-detail")
                        yield AgentTraceStream(id="agent-trace")

                # Tab 4: Events
                with TabPane("Events", id="tab-events"):
                    yield Input(placeholder="Filter events...", id="event-filter")
                    yield EventsLog(id="events-full")

                # Tab 5: Messages
                with TabPane("Messages", id="tab-messages"):
                    yield MessagesLog(id="messages-log-widget")

                # Tab 6: Decisions & Analysis
                with TabPane("Decisions", id="tab-decisions"):
                    with Vertical(id="decisions-outer"):
                        yield DecisionsPane(id="decisions-pane")
                        yield BudgetProjectionWidget(id="budget-projection")
                        yield FailureChainWidget(id="failure-chain")
                        yield ConflictPanel(id="conflict-panel")

        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(2.0, self._refresh)
        self._refresh()
        self._apply_responsive_classes()

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        """Suppress refresh during tab transitions to prevent focus stealing."""
        self._tab_switching = True
        self.set_timer(0.3, self._end_tab_switch)
        # Stop trace polling when leaving agents tab
        if event.tab and str(event.tab.id) != "tab-agents" and self._trace_timer is not None:
            self._trace_timer.stop()
            self._trace_timer = None

    def _end_tab_switch(self) -> None:
        self._tab_switching = False
        self._refresh()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_responsive_classes()

    def _apply_responsive_classes(self) -> None:
        w = self.size.width
        self.set_class(w < 100, "narrow")
        self.set_class(w < 80, "very-narrow")

    def _refresh(self) -> None:
        if self._tab_switching or self._refreshing:
            return
        self._refreshing = True
        self.run_worker(self._refresh_io, thread=True, exclusive=True)

    def _refresh_io(self) -> None:
        """Worker thread: all file I/O and data transforms."""
        try:
            state = self._store.read_state()
            if not state:
                state = {}

            seq = state.get("state_seq", 0)
            has_new_events = self._store.has_new_events()

            # Use cached tab value (query_one is NOT thread-safe)
            active_tab = self._last_refreshed_tab or "tab-overview"

            tab_changed = active_tab != self._last_refreshed_tab
            if seq == self._last_seq and not has_new_events and not tab_changed:
                self._refreshing = False
                return

            # Read events (I/O)
            raw_events: list[dict[str, Any]] = []
            try:
                raw_events = self._store.read_events(limit=500)
            except Exception:
                pass
            event_list = self._store.build_event_list(raw_events)

            # Build tab-specific data (I/O + transforms)
            tab_data: dict[str, Any] = {}
            if active_tab == "tab-overview":
                activity = self._store.build_agent_activity(raw_events)
                agents = self._store.build_agent_list(state, activity=activity)
                tasks = self._store.build_task_list(state)
                tab_data = {"activity": activity, "agents": agents, "tasks": tasks}
            elif active_tab == "tab-tasks":
                tab_data = {"tasks": self._store.build_task_list(state)}
            elif active_tab == "tab-agents":
                activity = self._store.build_agent_activity(raw_events)
                sidecars = self._store.read_activity_sidecars()
                tab_data = {"activity": activity, "sidecars": sidecars}
            elif active_tab == "tab-decisions":
                tab_data = {"raw_events": raw_events}

            # Post to main thread for widget updates
            self.call_from_thread(
                self._apply_refresh, seq, active_tab, state, event_list, raw_events, tab_data,
            )
        except Exception:
            self._refreshing = False

    def _apply_refresh(
        self,
        seq: int,
        active_tab: str,
        state: dict[str, Any],
        event_list: list[dict[str, Any]],
        raw_events: list[dict[str, Any]],
        tab_data: dict[str, Any],
    ) -> None:
        """Main thread: widget updates only."""
        self._last_seq = seq
        self._last_state = state
        self._last_events = event_list

        # Determine actual current tab (may have changed since worker started)
        try:
            actual_tab = self.query_one("#swarm-tabs", TabbedContent).active
        except Exception:
            actual_tab = active_tab
        self._last_refreshed_tab = actual_tab

        self._refresh_summary(state)

        # Only apply tab data if tab hasn't changed since worker started
        if actual_tab == active_tab:
            if actual_tab == "tab-overview":
                self._refresh_overview(state, tab_data["agents"], tab_data["tasks"], raw_events)
            elif actual_tab == "tab-tasks":
                self._refresh_tasks_with_data(tab_data["tasks"])
            elif actual_tab == "tab-agents":
                self._refresh_agents_with_data(state, tab_data["activity"], tab_data.get("sidecars", {}))
            elif actual_tab == "tab-events":
                self._refresh_events()
            elif actual_tab == "tab-messages":
                self._refresh_messages()
            elif actual_tab == "tab-decisions":
                self._refresh_decisions(state, tab_data.get("raw_events"))

        self._refreshing = False

    def _refresh_summary(self, state: dict[str, Any]) -> None:
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
        active_agents_list = [
            a for a in state.get("active_agents", [])
            if a.get("status") in ("running", "claiming")
        ]
        active_agents = len(active_agents_list)

        # Fingerprint check — skip widget updates if nothing changed
        cost_cents = int(float(budget.get("cost_used_usd", 0.0)) * 100)
        elapsed_mins = int(elapsed_s) // 60 if isinstance(elapsed_s, (int, float)) else 0
        phase = state.get("phase", "unknown")
        summary_key = (phase, running, done, total_tasks, failed, cost_cents, elapsed_mins)
        if summary_key == self._last_summary_key:
            return
        self._last_summary_key = summary_key

        # Build live activity list for summary bar
        agent_activities: list[dict[str, str]] = []
        for a in active_agents_list:
            activity = a.get("activity", "")
            task_id = a.get("task_id", "")
            if task_id:
                agent_activities.append({"task_id": task_id, "activity": activity})

        pending = dag_summary.get("pending", 0) if isinstance(dag_summary, dict) else 0

        try:
            self.query_one("#summary-bar", SwarmSummaryBar).update_summary(
                phase=state.get("phase", "unknown"),
                running=running,
                done=done,
                total=total_tasks,
                failed=failed,
                cost=float(budget.get("cost_used_usd", 0.0)),
                elapsed=elapsed_str,
                active_agents=active_agents,
                pending=pending,
                agent_activities=agent_activities,
            )
        except Exception:
            pass

        # Completion screen
        phase = state.get("phase", "unknown")
        if phase == "completed" and not self._completion_shown:
            self._completion_shown = True
            try:
                from attocode.tui.screens.completion_screen import CompletionScreen
                self.push_screen(
                    CompletionScreen(
                        done=done,
                        failed=failed,
                        total=total_tasks,
                        cost=float(budget.get("cost_used_usd", 0.0)),
                        elapsed=elapsed_str,
                    ),
                    callback=self._on_completion_dismiss,
                )
            except Exception:
                pass

        # Budget breakdown bar — show per-task cost breakdown
        try:
            max_cost = float(budget.get("cost_max_usd", 1.0)) or 1.0
            cost_used = float(budget.get("cost_used_usd", 0.0))
            pct = min(100, int(cost_used / max_cost * 100))
            bar = self.query_one("#budget-progress", ProgressBar)
            bar.update(progress=pct)

            # Update budget breakdown label
            breakdown = f"Budget: ${cost_used:.2f}/${max_cost:.2f}"
            per_task_costs = self._store.build_per_task_costs(state)
            if per_task_costs:
                parts = []
                shown_cost = 0.0
                for tc in per_task_costs[:4]:
                    parts.append(f"{tc['task_id']}: ${tc['cost_usd']:.2f}")
                    shown_cost += tc["cost_usd"]
                others = len(per_task_costs) - min(4, len(per_task_costs))
                other_cost = cost_used - shown_cost
                if others > 0 and other_cost > 0:
                    parts.append(f"{others} others: ${other_cost:.2f}")
                breakdown += " | " + " | ".join(parts)
            self.query_one("#budget-breakdown", Static).update(breakdown)
        except Exception:
            pass

    def _refresh_overview(
        self,
        state: dict[str, Any],
        agents: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        raw_events: list[dict[str, Any]],
    ) -> None:
        overview_state = self._build_overview_state(state, agents, tasks)
        try:
            self.query_one("#overview-pane", OverviewPane).update_state(overview_state)
        except Exception:
            pass

    def _refresh_tasks(self, state: dict[str, Any]) -> None:
        tasks = self._store.build_task_list(state)
        self._refresh_tasks_with_data(tasks)

    def _refresh_tasks_with_data(self, tasks: list[dict[str, Any]]) -> None:
        """Update tasks tab with pre-built task data (no I/O)."""
        try:
            self.query_one("#tasks-dt", TasksDataTable).update_tasks(tasks)
        except Exception:
            pass

    def _refresh_agents(
        self, state: dict[str, Any], activity: dict[str, str]
    ) -> None:
        sidecars = self._store.read_activity_sidecars()
        self._refresh_agents_with_data(state, activity, sidecars)

    def _refresh_agents_with_data(
        self, state: dict[str, Any], activity: dict[str, str], sidecars: dict[str, str],
    ) -> None:
        """Update agents tab with pre-built data (no I/O)."""
        if sidecars:
            for agent in state.get("active_agents", []):
                task_id = str(agent.get("task_id", ""))
                agent_id = str(agent.get("agent_id", ""))
                if task_id in sidecars and agent_id:
                    activity[agent_id] = sidecars[task_id]
        agents = self._store.build_agent_list(state, activity=activity)
        try:
            self.query_one("#agents-dt", AgentsDataTable).update_agents(agents)
        except Exception:
            pass

    def _refresh_events(self) -> None:
        try:
            self.query_one("#events-full", EventsLog).update_events(self._last_events)
        except Exception:
            pass

    def _refresh_messages(self) -> None:
        try:
            messages = self._store.read_all_messages()
            self.query_one("#messages-log-widget", MessagesLog).update_messages(messages)
        except Exception:
            pass

    def _refresh_decisions(
        self, state: dict[str, Any], raw_events: list[dict[str, Any]] | None = None,
    ) -> None:
        """Refresh the Decisions tab with decisions, budget, failures, conflicts."""
        if raw_events is None:
            raw_events = self._store.read_events(limit=500)

        # Decisions
        try:
            decisions = self._store.build_decision_list(state)
            self.query_one("#decisions-pane", DecisionsPane).update_state({
                "decisions": decisions,
                "errors": state.get("errors", []),
                "transitions": state.get("task_transition_log", []),
            })
        except Exception:
            pass

        # Budget projection from events (reuse already-read events)
        try:
            projection: dict[str, Any] = {}
            for ev in reversed(raw_events[-100:]):
                data = ev.get("data", {}) if isinstance(ev.get("data"), dict) else {}
                if "projection" in data:
                    projection = data["projection"]
                    break

            # Fallback: compute from state budget when no event projection found
            if not projection:
                budget = state.get("budget", {})
                dag_summary = state.get("dag_summary", {})
                cost_used = float(budget.get("cost_used_usd", 0))
                cost_max = float(budget.get("cost_max_usd", 0))
                done = dag_summary.get("done", 0) if isinstance(dag_summary, dict) else 0
                total = sum(dag_summary.values()) if isinstance(dag_summary, dict) else 0
                if cost_max > 0:
                    fraction = cost_used / cost_max
                    avg = cost_used / max(done, 1)
                    remaining = max(total - done, 0)
                    projected = cost_used + avg * remaining
                    level = (
                        "ok" if fraction < 0.6
                        else "caution" if fraction < 0.8
                        else "warning" if fraction < 0.9
                        else "critical"
                    )
                    projection = {
                        "usage_fraction": fraction,
                        "warning_level": level,
                        "avg_cost_per_task": avg,
                        "projected_total_cost": projected,
                        "estimated_completable": int((cost_max - cost_used) / max(avg, 0.001)) if avg > 0 else 0,
                        "will_exceed": projected > cost_max,
                        "message": f"${cost_used:.2f} / ${cost_max:.2f}",
                    }

            self.query_one("#budget-projection", BudgetProjectionWidget).update_projection(projection)
        except Exception:
            pass

        # Failure chain (pass events to avoid re-read)
        try:
            failures = self._store.build_failure_chain(state, events=raw_events)
            self.query_one("#failure-chain", FailureChainWidget).update_failures(failures)
        except Exception:
            pass

        # Conflicts (pass events to avoid re-read)
        try:
            conflicts = self._store.build_conflict_list(state, events=raw_events)
            self.query_one("#conflict-panel", ConflictPanel).update_conflicts(conflicts)
        except Exception:
            pass

    def _build_overview_state(
        self,
        state: dict[str, Any],
        agents: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Adapt attoswarm state into OverviewPane's expected format."""
        # Tasks as dict keyed by task_id (OverviewPane expects this)
        tasks_dict = {t["task_id"]: t for t in tasks}

        # Edges as [{source, target}, ...]
        dag = state.get("dag", {})
        raw_edges = dag.get("edges", [])
        edges = []
        for edge in raw_edges:
            if isinstance(edge, (list, tuple)) and len(edge) >= 2:
                edges.append({"source": str(edge[0]), "target": str(edge[1])})
            elif isinstance(edge, dict):
                edges.append({
                    "source": str(edge.get("source", edge.get("from", ""))),
                    "target": str(edge.get("target", edge.get("to", ""))),
                })

        # Timeline: last 30 events
        timeline = self._last_events[-30:]

        return {
            "status": {"active_workers": agents},
            "tasks": tasks_dict,
            "edges": edges,
            "timeline": timeline,
        }

    # ── Selection handlers ───────────────────────────────────────────

    def on_tasks_data_table_task_selected(
        self, event: TasksDataTable.TaskSelected
    ) -> None:
        state = self._last_state if self._last_state is not None else self._store.read_state()
        detail = self._store.build_task_detail(event.task_id, state=state)
        if detail:
            try:
                self.query_one("#task-detail", DetailInspector).inspect(detail)
            except Exception:
                pass

    def on_agents_data_table_agent_selected(
        self, event: AgentsDataTable.AgentSelected
    ) -> None:
        state = self._last_state if self._last_state is not None else self._store.read_state()
        detail = self._store.build_agent_detail(event.agent_id, state)
        if detail:
            try:
                self.query_one("#agent-detail", DetailInspector).inspect(detail)
            except Exception:
                pass
            # Wire trace stream to selected agent's task
            task_id = detail.get("task_id", "")
            if task_id:
                self._focused_agent_task = task_id
                trace_path = Path(self._store.run_dir) / "agents" / f"agent-{task_id}.trace.jsonl"
                try:
                    widget = self.query_one("#agent-trace", AgentTraceStream)
                    widget.set_trace_path(trace_path)
                except Exception:
                    pass
                # Start polling timer if not already running
                if self._trace_timer is None:
                    self._trace_timer = self.set_interval(0.5, self._poll_trace)

    def on_task_card_selected(self, event: TaskCard.Selected) -> None:
        """When a task card is clicked in OverviewPane, show detail + switch tab."""
        state = self._last_state if self._last_state is not None else self._store.read_state()
        detail = self._store.build_task_detail(event.task_id, state=state)
        if detail:
            try:
                self.query_one("#task-detail", DetailInspector).inspect(detail)
            except Exception:
                pass
            self._switch_tab("tab-tasks")

    def on_agent_card_selected(self, event: AgentCard.Selected) -> None:
        """When an agent card is clicked in OverviewPane, show detail + switch tab."""
        state = self._last_state if self._last_state is not None else self._store.read_state()
        detail = self._store.build_agent_detail(event.agent_id, state)
        if detail:
            try:
                self.query_one("#agent-detail", DetailInspector).inspect(detail)
            except Exception:
                pass
            self._switch_tab("tab-agents")

    def on_dependency_tree_node_selected(
        self, event: DependencyTree.NodeSelected
    ) -> None:
        """When a DAG tree node is clicked, show task detail + switch to Tasks tab."""
        state = self._last_state if self._last_state is not None else self._store.read_state()
        detail = self._store.build_task_detail(event.task_id, state=state)
        if detail:
            try:
                self.query_one("#task-detail", DetailInspector).inspect(detail)
            except Exception:
                pass
            self._switch_tab("tab-tasks")

    # ── Event filter handler ────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "event-filter":
            query = event.value.strip().lower()
            if not query:
                # Show all events
                self._refresh_events()
            else:
                # Filter events by substring match on agent_id, task_id, type, message
                filtered = [
                    e for e in self._last_events
                    if query in str(e.get("agent_id", "")).lower()
                    or query in str(e.get("task_id", "")).lower()
                    or query in str(e.get("type", "")).lower()
                    or query in str(e.get("message", "")).lower()
                ]
                try:
                    self.query_one("#events-full", EventsLog).update_events_filtered(filtered)
                except Exception:
                    pass

    # ── Skip/Retry/Edit control message handlers ──────────────────────

    def on_detail_inspector_skip_task_requested(
        self, event: DetailInspector.SkipTaskRequested
    ) -> None:
        self._write_control_message(event.task_id, "skip")
        self.notify(f"Skip requested: {event.task_id}")

    def on_detail_inspector_retry_task_requested(
        self, event: DetailInspector.RetryTaskRequested
    ) -> None:
        self._write_control_message(event.task_id, "retry")
        self.notify(f"Retry requested: {event.task_id}")

    def on_detail_inspector_edit_task_requested(
        self, event: DetailInspector.EditTaskRequested
    ) -> None:
        self.notify(f"Edit not yet implemented for {event.task_id}", severity="warning")

    def _write_control_message(
        self, task_id: str, action: str, extra: dict[str, Any] | None = None
    ) -> None:
        """Write a control message to control.jsonl for the orchestrator to pick up."""
        control_path = Path(self._store.run_dir) / "control.jsonl"
        msg: dict[str, Any] = {
            "action": action,
            "task_id": task_id,
            "timestamp": utc_now_iso(),
        }
        if extra:
            msg.update(extra)
        try:
            with open(control_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg) + "\n")
        except Exception:
            self.notify("Failed to write control message", severity="error")

    # ── Input focus guard ──────────────────────────────────────────────

    def _input_has_focus(self) -> bool:
        """Return True if a text input widget has focus (suppress hotkeys)."""
        from textual.widgets import Input, TextArea
        return isinstance(self.focused, (Input, TextArea))

    # ── Tab switching actions ─────────────────────────────────────────

    def _switch_tab(self, tab_id: str) -> None:
        try:
            tabs = self.query_one("#swarm-tabs", TabbedContent)
            tabs.active = tab_id
        except Exception:
            pass

    def action_tab_overview(self) -> None:
        if not self._input_has_focus():
            self._switch_tab("tab-overview")

    def action_tab_tasks(self) -> None:
        if not self._input_has_focus():
            self._switch_tab("tab-tasks")

    def action_tab_agents(self) -> None:
        if not self._input_has_focus():
            self._switch_tab("tab-agents")

    def action_tab_events(self) -> None:
        if not self._input_has_focus():
            self._switch_tab("tab-events")

    def action_tab_messages(self) -> None:
        if not self._input_has_focus():
            self._switch_tab("tab-messages")

    def action_tab_decisions(self) -> None:
        if not self._input_has_focus():
            self._switch_tab("tab-decisions")

    # ── Other actions ─────────────────────────────────────────────────

    def action_refresh_now(self) -> None:
        if self._input_has_focus():
            return
        self._refresh()

    def action_pause_resume(self) -> None:
        if self._input_has_focus():
            return
        state_path = Path(self._store.state_path)
        state = read_json(state_path, default={})
        phase = state.get("phase", "executing")
        new_phase = "paused" if phase != "paused" else "executing"
        # Write control message for orchestrator instead of direct state mutation
        self._write_control_message("", new_phase)
        # Also update state for immediate TUI feedback
        state["phase"] = new_phase
        state["updated_at"] = utc_now_iso()
        write_json_atomic(state_path, state)

    def action_inject_message(self) -> None:
        """Inject a control message to a selected agent."""
        if self._input_has_focus():
            return
        state = self._last_state if self._last_state is not None else self._store.read_state()
        agent_rows = [
            a for a in state.get("active_agents", [])
            if a.get("status") in ("running", "claiming")
        ]
        if not agent_rows:
            self.notify("No active agents for message injection", severity="warning")
            return

        if len(agent_rows) == 1:
            # Single agent — inject directly
            self._inject_to_agent(str(agent_rows[0].get("agent_id", "")))
        else:
            # Multiple agents — show selection list
            agent_ids = [str(a.get("agent_id", "")) for a in agent_rows]
            # Use a simple round-robin approach; in a full implementation
            # this would be a SelectionList popup
            # For now, cycle through agents on each press
            last_injected = getattr(self, "_last_inject_idx", -1)
            idx = (last_injected + 1) % len(agent_ids)
            self._last_inject_idx = idx
            self._inject_to_agent(agent_ids[idx])

    def _inject_to_agent(self, agent_id: str) -> None:
        """Send a control message to a specific agent's inbox."""
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
        if self._input_has_focus():
            return
        from attocode.tui.screens.focus_screen import FocusScreen

        self.push_screen(FocusScreen(state_fn=self._state_fn_adapter))

    def action_show_graph(self) -> None:
        """Push GraphScreen for full-screen interactive DAG."""
        if self._input_has_focus():
            return
        from attocode.tui.screens.graph_screen import GraphScreen

        self.push_screen(GraphScreen())

    def action_show_timeline(self) -> None:
        """Push TimelineScreen for full-screen event timeline."""
        if self._input_has_focus():
            return
        from attocode.tui.screens.timeline_screen import TimelineScreen

        self.push_screen(TimelineScreen(
            state_fn=self._state_fn_adapter,
            events=self._last_events,
        ))

    def _on_completion_dismiss(self, result: str | None) -> None:
        """Handle completion screen dismiss."""
        if result == "quit":
            self.action_quit()

    def _poll_trace(self) -> None:
        """Poll the agent trace stream for new entries."""
        try:
            self.query_one("#agent-trace", AgentTraceStream).poll_new_entries()
        except Exception:
            pass

    def action_quit(self) -> None:
        """Override quit to signal shutdown to orchestrator before exiting."""
        self._write_control_message("", "shutdown")
        self.exit()

    # ── Helpers ──────────────────────────────────────────────────────

    def _state_fn_adapter(self) -> dict[str, Any]:
        """Adapter that wraps StateStore for FocusScreen/TimelineScreen."""
        state = dict(self._last_state) if self._last_state is not None else self._store.read_state()
        state["events"] = self._last_events
        return state
