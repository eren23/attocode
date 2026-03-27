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
import time
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

from attoswarm.protocol.io import read_json, write_json_atomic
from attoswarm.protocol.models import utc_now_iso
from attoswarm.run_summary import collect_modified_files
from attoswarm.tui.screens import (
    AddTaskScreen,
    CompletionScreen,
    ConfirmStopScreen,
    EditTaskScreen,
    FocusScreen,
    GraphScreen,
    TimelineScreen,
)
from attoswarm.tui.stores import ResearchStateStore, StateStore
from attoswarm.tui.widgets import (
    AgentCard,
    AgentTraceStream,
    AgentsDataTable,
    BudgetProjectionWidget,
    ConflictPanel,
    DecisionsPane,
    DetailInspector,
    EventsLog,
    FailureChainWidget,
    MessagesLog,
    OverviewPane,
    TaskCard,
    TasksDataTable,
)

if TYPE_CHECKING:
    from textual import events
    from textual.widgets import Input, TextArea

    from attoswarm.tui.widgets import DependencyTree

_CSS_PATH = Path(__file__).resolve().parent / "styles" / "swarm.tcss"


class ResearchOverview(Static):
    """Research campaign overview widget."""

    def update_research(self, data: dict[str, Any]) -> None:
        if not data:
            self.update("Waiting for research data...")
            return
        state = data.get("state", {})
        experiments = data.get("experiments", [])
        findings = data.get("findings", [])

        lines: list[str] = []
        lines.append(f"[bold]Research Run:[/bold] {state.get('run_id', '?')}")
        lines.append(f"[bold]Goal:[/bold] {state.get('goal', '?')[:80]}")
        status = state.get("status", "?")
        status_color = {"running": "yellow", "completed": "green", "error": "red"}.get(
            status, "white"
        )
        lines.append(f"[bold]Status:[/bold] [{status_color}]{status}[/{status_color}]")
        if state.get("error"):
            lines.append(f"[bold red]Error:[/bold red] {state['error']}")
        lines.append("")
        lines.append(f"[bold]Baseline:[/bold] {state.get('baseline_value', 'N/A')}")
        lines.append(
            f"[bold]Best:[/bold] {state.get('best_value', 'N/A')} "
            f"(exp {state.get('best_experiment_id', 'n/a')})"
        )
        lines.append(
            f"[bold]Experiments:[/bold] {state.get('total_experiments', 0)} "
            f"({state.get('accepted_count', 0)} accepted, "
            f"{state.get('rejected_count', 0)} rejected, "
            f"{state.get('invalid_count', 0)} invalid)"
        )
        lines.append(
            f"[bold]Cost:[/bold] ${state.get('total_cost_usd', 0):.4f} "
            f"| Tokens: {state.get('total_tokens', 0):,}"
        )
        lines.append(
            f"[bold]Wall time:[/bold] {state.get('wall_seconds', 0):.0f}s "
            f"| Active: {state.get('active_experiments', 0)}"
        )
        lines.append("")

        # Experiment table
        baseline_val = state.get("baseline_value")
        if experiments:
            lines.append("[bold underline]Recent Experiments[/bold underline]")
            lines.append(
                f"{'#':>3} {'Status':<10} {'Strategy':<10} {'Metric':>8} {'Delta':>8} {'Hypothesis'}"
            )
            lines.append("-" * 80)
            for exp in experiments[-15:]:
                metric_val = exp.get("metric_value")
                metric = f"{metric_val}" if metric_val is not None else "-"

                # Delta from baseline
                if metric_val is not None and baseline_val is not None:
                    try:
                        delta_num = float(metric_val) - float(baseline_val)
                        delta = f"{delta_num:+.4f}"
                    except (TypeError, ValueError):
                        delta = "-"
                else:
                    delta = "-"

                # Color-coded status
                exp_status = exp.get("status", "?")
                status_colors = {
                    "accepted": "green",
                    "rejected": "red",
                    "error": "red",
                    "invalid": "red",
                    "running": "yellow",
                    "candidate": "yellow",
                    "pending": "yellow",
                }
                sc = status_colors.get(exp_status, "white")
                status_str = f"[{sc}]{exp_status:<10}[/{sc}]"

                hyp = (exp.get("hypothesis") or "")[:35]
                reject = exp.get("reject_reason") or ""
                suffix = f" [dim red]({reject[:30]})[/dim red]" if reject and exp_status in ("rejected", "invalid") else ""

                lines.append(
                    f"{exp.get('iteration', '?'):>3} "
                    f"{status_str} "
                    f"{exp.get('strategy', '?'):<10} "
                    f"{metric:>8} "
                    f"{delta:>8} "
                    f"{hyp}{suffix}"
                )

        # Findings
        if findings:
            lines.append("")
            lines.append("[bold underline]Findings[/bold underline]")
            for f in findings[-5:]:
                lines.append(
                    f"  [{f.get('scope', '?')}] {f.get('claim', '?')[:60]}"
                )

        # Recent events from event log
        try:
            events_path = Path(self.app._store.run_dir) / "research.events.jsonl"
            if events_path.exists():
                event_lines = events_path.read_text().strip().splitlines()[-10:]
                lines.append("")
                lines.append("[bold underline]Recent Events[/bold underline]")
                for el in event_lines:
                    ev = json.loads(el)
                    ts = time.strftime("%H:%M:%S", time.localtime(ev.get("ts", 0)))
                    lines.append(f"  {ts} {ev.get('type', '?')}: {ev.get('message', '')[:60]}")
        except Exception:
            pass

        self.update("\n".join(lines))


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
        resume_command: str = "",
    ) -> None:
        text = Text()
        # Phase
        phase_style = {
            "initializing": "cyan italic",
            "decomposing": "cyan bold",
            "awaiting_approval": "yellow bold",
            "executing": "green bold",
            "completed": "green",
            "failed": "red bold",
            "planning_failed": "red bold",
            "paused": "yellow",
            "rejected": "red dim",
            "shutdown": "red",
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
        if phase in ("completed", "shutdown") and pending > 0:
            text.append("\u2502 ", style="dim")
            text.append(f"{pending} pending ", style="yellow bold")
            if resume_command:
                text.append(f"(resume: {resume_command})", style="yellow dim")

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
        Binding("s", "stop_swarm", "Stop"),
        Binding("i", "inject_message", "Inject Message"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("f", "focus_agent", "Focus Agent"),
        Binding("g", "show_graph", "Graph"),
        Binding("t", "show_timeline", "Timeline"),
        Binding("a", "approve_plan", "Approve", show=False),
        Binding("x", "reject_plan", "Reject", show=False),
        Binding("n", "add_task", "New Task"),
        Binding("ctrl+c", "quit", "Detach", show=False),
        Binding("q", "quit", "Detach"),
    ]

    def __init__(
        self,
        run_dir: str,
        coordinator_pid: int | None = None,
        research_mode: bool = False,
    ) -> None:
        super().__init__()
        self._store = StateStore(run_dir)
        self._research_mode = research_mode
        self._research_store: ResearchStateStore | None = (
            ResearchStateStore(run_dir) if research_mode else None
        )
        self._last_events: list[dict[str, Any]] = []
        self._tab_switching = False
        self._refreshing = False
        self._last_state: dict[str, Any] | None = None
        self._last_seq: int = -1
        self._trace_timer: Any = None
        self._focused_agent_task: str | None = None
        self._completion_shown: bool = False
        self._approval_shown: bool = False
        self._last_summary_key: tuple[str, int, int, int, int, int, int, int] | None = None
        self._last_refreshed_tab: str = ""
        self._coordinator_pid: int | None = coordinator_pid
        self._exit_intent = "detach"
        # Track whether coordinator has written fresh state.
        # When launched with a coordinator_pid, the first state read may be
        # stale from a previous run.  We record the initial state_seq on
        # first read; until the seq changes (coordinator wrote fresh state),
        # we suppress completion/approval triggers.
        self._initial_state_seq: int | None = None
        self._coordinator_started: bool = coordinator_pid is None  # standalone TUI is always "started"

    def _completion_files_modified(self, state: dict[str, Any]) -> int:
        return len(collect_modified_files(self._store.run_dir, state))

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        if self._research_mode:
            with Vertical(id="research-outer"):
                yield ResearchOverview(id="research-overview")
            yield Footer()
            return

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
        self.set_timer(0.05, self._end_tab_switch)
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
            # Research mode: only read research state
            if self._research_mode and self._research_store is not None:
                data = self._research_store.read_state()
                if data is None:
                    data = self._research_store.last_state
                self.call_from_thread(self._apply_research_refresh, data)
                return

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
                agents = self._store.build_agent_list(state, activity=activity, enrich_trace=False)
                tasks = self._store.build_task_list(state)
                tab_data = {"activity": activity, "agents": agents, "tasks": tasks}
            elif active_tab == "tab-tasks":
                tab_data = {"tasks": self._store.build_task_list(state)}
            elif active_tab == "tab-agents":
                activity = self._store.build_agent_activity(raw_events)
                sidecars = self._store.read_activity_sidecars()
                tab_data = {"activity": activity, "sidecars": sidecars}
            elif active_tab == "tab-messages":
                tab_data = {"messages": self._store.read_all_messages()}
            elif active_tab == "tab-decisions":
                decisions = self._store.build_decision_list(state)
                failures = self._store.build_failure_chain(state, events=raw_events)
                conflicts = self._store.build_conflict_list(state, events=raw_events)
                tab_data = {
                    "raw_events": raw_events,
                    "decisions": decisions,
                    "failures": failures,
                    "conflicts": conflicts,
                }

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

        # Check if coordinator has written fresh state — block ALL widget
        # updates (tabs, summary, completion) until it does.
        if not self._coordinator_started:
            seq_val = state.get("state_seq", 0)
            if self._initial_state_seq is None:
                self._initial_state_seq = seq_val
            elif seq_val != self._initial_state_seq:
                self._coordinator_started = True

            if not self._coordinator_started and self._coordinator_pid is not None:
                try:
                    self.query_one("#summary-bar", SwarmSummaryBar).update_summary(
                        phase="initializing",
                        running=0, done=0, total=0, failed=0,
                        cost=0.0, elapsed="", active_agents=0, pending=0,
                    )
                except Exception:
                    pass
                self._refreshing = False
                return

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
                self._refresh_messages_with_data(tab_data.get("messages", []))
            elif actual_tab == "tab-decisions":
                self._refresh_decisions_with_data(
                    state, tab_data.get("raw_events", []),
                    tab_data.get("decisions", []),
                    tab_data.get("failures", []),
                    tab_data.get("conflicts", []),
                )

        self._refreshing = False

    def _apply_research_refresh(self, data: dict[str, Any] | None) -> None:
        """Main thread: update research overview widget."""
        try:
            widget = self.query_one("#research-overview", ResearchOverview)
            widget.update_research(data or {})
        except Exception:
            pass
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
        pending = dag_summary.get("pending", 0) if isinstance(dag_summary, dict) else 0

        # Fingerprint check — skip widget updates if nothing changed
        cost_cents = int(float(budget.get("cost_used_usd", 0.0)) * 100)
        elapsed_mins = int(elapsed_s) // 60 if isinstance(elapsed_s, (int, float)) else 0
        phase = state.get("phase", "unknown")
        summary_key = (phase, running, done, total_tasks, failed, pending, cost_cents, elapsed_mins)
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
        resume_command = self._resume_command() if phase in ("completed", "shutdown") and pending > 0 else ""

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
                resume_command=resume_command,
            )
        except Exception:
            pass

        # Subprocess death detection
        if self._coordinator_pid is not None:
            import os as _os
            try:
                _os.kill(self._coordinator_pid, 0)
            except ProcessLookupError:
                if not self._completion_shown:
                    if phase not in ("completed", "shutdown", "planning_failed"):
                        self.notify(
                            "Coordinator process exited unexpectedly — check coordinator.log",
                            severity="error",
                        )

        # Approval banner
        if phase == "awaiting_approval" and not self._approval_shown:
            self._approval_shown = True
            self.notify(
                "Task plan ready for review — press [a] to approve, [x] to reject",
                severity="information",
                timeout=0,
            )

        # Completion screen
        phase = state.get("phase", "unknown")
        if phase in ("completed", "shutdown", "planning_failed") and not self._completion_shown:
            self._completion_shown = True
            try:
                # Read git branch from state or git_safety.json
                git_branch = state.get("git_branch", "")
                if not git_branch:
                    gs_path = Path(self._store.run_dir) / "git_safety.json"
                    gs = read_json(gs_path, default={})
                    git_branch = gs.get("swarm_branch", "")

                self.push_screen(
                    CompletionScreen(
                        done=done,
                        failed=failed,
                        total=total_tasks,
                        cost=float(budget.get("cost_used_usd", 0.0)),
                        elapsed=elapsed_str,
                        files_modified=self._completion_files_modified(state),
                        git_branch=git_branch,
                        phase=phase,
                        pending=pending,
                        resume_command=resume_command,
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

    def _refresh_messages_with_data(self, messages: list[dict[str, Any]]) -> None:
        """Update messages tab with pre-built data (no I/O)."""
        try:
            self.query_one("#messages-log-widget", MessagesLog).update_messages(messages)
        except Exception:
            pass

    def _refresh_decisions(
        self, state: dict[str, Any], raw_events: list[dict[str, Any]] | None = None,
    ) -> None:
        """Refresh the Decisions tab with decisions, budget, failures, conflicts."""
        if raw_events is None:
            raw_events = self._store.read_events(limit=500)
        decisions = self._store.build_decision_list(state)
        failures = self._store.build_failure_chain(state, events=raw_events)
        conflicts = self._store.build_conflict_list(state, events=raw_events)
        self._refresh_decisions_with_data(state, raw_events, decisions, failures, conflicts)

    def _refresh_decisions_with_data(
        self,
        state: dict[str, Any],
        raw_events: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        failures: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
    ) -> None:
        """Update decisions tab with pre-built data (no I/O)."""
        # Decisions
        try:
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

        # Failure chain
        try:
            self.query_one("#failure-chain", FailureChainWidget).update_failures(failures)
        except Exception:
            pass

        # Conflicts
        try:
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

        # Past runs from history/
        history = self._store.list_history()

        return {
            "status": {"active_workers": agents},
            "tasks": tasks_dict,
            "edges": edges,
            "timeline": timeline,
            "history": history,
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
                    self._trace_timer = self.set_interval(1.5, self._poll_trace)

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
        # Get current description from state
        state = self._last_state or self._store.read_state()
        dag_nodes = state.get("dag", {}).get("nodes", [])
        task_data = next((n for n in dag_nodes if n.get("task_id") == event.task_id), {})
        desc = task_data.get("description", "")
        # If description is truncated (200 chars in state), read full from per-task JSON
        if len(desc) >= 199:
            detail = self._store.read_task(event.task_id)
            desc = detail.get("description", desc) if detail else desc

        self.push_screen(
            EditTaskScreen(task_id=event.task_id, description=desc),
            callback=self._on_edit_task_dismiss,
        )

    def _on_edit_task_dismiss(self, result: tuple[str, str] | None) -> None:
        if result is not None:
            task_id, new_desc = result
            self._write_control_message(task_id, "edit_task", {"description": new_desc})
            self.notify(f"Task {task_id} description updated")

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
                f.flush()
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

    def action_stop_swarm(self) -> None:
        if self._input_has_focus():
            return
        state = self._last_state if self._last_state is not None else self._store.read_state()
        if state.get("phase") in ("completed", "shutdown", "failed", "planning_failed", "rejected"):
            self.notify("Run is no longer active", severity="warning")
            return
        self.push_screen(ConfirmStopScreen(), callback=self._on_stop_swarm_dismiss)

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
        self.push_screen(FocusScreen(state_fn=self._state_fn_adapter))

    def action_show_graph(self) -> None:
        """Push GraphScreen for full-screen interactive DAG."""
        if self._input_has_focus():
            return
        # Derive working_dir from state or cwd
        working_dir = ""
        if self._last_state:
            agents = self._last_state.get("active_agents", [])
            if agents:
                working_dir = agents[0].get("cwd", "")
        if not working_dir:
            import os
            working_dir = os.getcwd()

        self.push_screen(GraphScreen(working_dir=working_dir))

    def action_show_timeline(self) -> None:
        """Push TimelineScreen for full-screen event timeline."""
        if self._input_has_focus():
            return
        self.push_screen(TimelineScreen(
            state_fn=self._state_fn_adapter,
            events=self._last_events,
        ))

    def _on_completion_dismiss(self, result: str | None) -> None:
        """Handle completion screen dismiss."""
        if result == "quit":
            self.action_quit()
        elif result in ("merge", "keep"):
            self._git_finalize(result)

    def _on_stop_swarm_dismiss(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        self._exit_intent = "stop"
        self._write_control_message("", "shutdown")
        self.notify("Stop requested — waiting for coordinator shutdown", severity="warning")
        self.exit()

    def _git_finalize(self, mode: str) -> None:
        """Run git finalization from TUI."""
        import asyncio as _asyncio
        import os as _os

        from attoswarm.workspace.git_safety import GitSafetyNet

        run_dir = Path(self._store.run_dir)
        gs_path = Path(self._store.run_dir) / "git_safety.json"
        gs = read_json(gs_path, default={})
        state = read_json(run_dir / "swarm.state.json", default={})
        swarm_branch = gs.get("swarm_branch", "")
        if not swarm_branch:
            self.notify("No git safety state found", severity="warning")
            return

        working_dir = str(state.get("working_dir", "")) if isinstance(state, dict) else ""
        if not working_dir:
            working_dir = str(run_dir.resolve().parent.parent)
        elif not _os.path.isabs(working_dir):
            working_dir = str((run_dir.resolve().parent.parent / working_dir).resolve())

        try:
            git_safety = GitSafetyNet(working_dir, str(gs.get("run_id", "")), str(run_dir))
            git_safety.load_state()
            _asyncio.run(git_safety.finalize(mode))
            if mode == "merge":
                self.notify(
                    f"Merged {git_safety.state.swarm_branch} into {git_safety.state.original_branch}",
                    severity="information",
                )
            else:
                self.notify(f"Kept branch {git_safety.state.swarm_branch}", severity="information")
        except Exception as exc:
            self.notify(f"Git finalization failed: {str(exc)[:200]}", severity="error")

    def action_approve_plan(self) -> None:
        if self._input_has_focus():
            return
        state = self._last_state or self._store.read_state()
        if state.get("phase") != "awaiting_approval":
            return
        self._write_control_message("", "approve")
        self.notify("Plan approved — execution starting", severity="information")

    def action_reject_plan(self) -> None:
        if self._input_has_focus():
            return
        state = self._last_state or self._store.read_state()
        if state.get("phase") != "awaiting_approval":
            return
        self._write_control_message("", "reject")
        self.notify("Plan rejected — shutting down", severity="warning")

    def action_add_task(self) -> None:
        if self._input_has_focus():
            return
        self.push_screen(AddTaskScreen(), callback=self._on_add_task_dismiss)

    def _on_add_task_dismiss(self, result: dict[str, Any] | None) -> None:
        if result is not None:
            self._write_control_message("", "add_task", result)
            self.notify(f"Task added: {result.get('title', '')}")

    def _poll_trace(self) -> None:
        """Poll the agent trace stream for new entries."""
        try:
            self.query_one("#agent-trace", AgentTraceStream).poll_new_entries()
        except Exception:
            pass

    def action_quit(self) -> None:
        """Exit the dashboard without stopping the coordinator."""
        self._exit_intent = "detach"
        self.exit()

    # ── Helpers ──────────────────────────────────────────────────────

    @property
    def exit_intent(self) -> str:
        return self._exit_intent

    def _state_fn_adapter(self) -> dict[str, Any]:
        """Adapter that wraps StateStore for FocusScreen/TimelineScreen."""
        state = dict(self._last_state) if self._last_state is not None else self._store.read_state()
        state["events"] = self._last_events
        return state

    def _resume_command(self) -> str:
        return f"attoswarm resume {self._store.run_dir}"
