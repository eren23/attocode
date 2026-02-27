"""Textual app for attoswarm dashboard (operations view).

Replaces the original DataTable-based layout with rich widgets:
AgentGrid, TaskBoard, DependencyDAGView, EventTimeline,
DetailInspector, FileActivityMap, and SwarmStatusFooter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from attoswarm.protocol.io import read_json, write_json_atomic
from attoswarm.protocol.models import utc_now_iso
from attoswarm.tui.stores import StateStore

from attocode.tui.widgets.swarm.agent_grid import AgentCard, AgentGrid
from attocode.tui.widgets.swarm.task_board import TaskBoard, TaskCard
from attocode.tui.widgets.swarm.dag_view import DependencyDAGView
from attocode.tui.widgets.swarm.event_timeline import EventTimeline
from attocode.tui.widgets.swarm.detail_inspector import DetailInspector
from attocode.tui.widgets.swarm.file_activity_map import FileActivityMap
from attocode.tui.screens.swarm_dashboard import SwarmStatusFooter

_CSS_PATH = Path(__file__).resolve().parent / "styles" / "swarm.tcss"


class AttoswarmApp(App[None]):
    TITLE = "Attoswarm"

    CSS = _CSS_PATH.read_text(encoding="utf-8") if _CSS_PATH.exists() else ""

    BINDINGS = [
        Binding("p", "pause_resume", "Pause/Resume"),
        Binding("i", "inject_message", "Inject Message"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("f", "focus_agent", "Focus Agent"),
        Binding("t", "fullscreen_timeline", "Timeline"),
        Binding("tab", "cycle_focus", "Cycle Panel"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, run_dir: str) -> None:
        super().__init__()
        self._store = StateStore(run_dir)
        self._last_events: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="swarm-outer"):
            # Top: Agent Grid
            yield AgentGrid(id="swarm-agent-grid")

            # Middle: Task Board + DAG / Detail Inspector
            with Horizontal(id="swarm-middle"):
                with Vertical(id="swarm-left"):
                    yield TaskBoard(id="swarm-task-board")
                with Vertical(id="swarm-right"):
                    yield DependencyDAGView(id="swarm-dag-view")
                    yield DetailInspector(id="swarm-detail")

            # Bottom: Event Timeline + File Activity
            yield EventTimeline(id="swarm-timeline")
            yield FileActivityMap(id="swarm-file-activity")

        yield SwarmStatusFooter(id="swarm-status-footer")
        yield Static("", id="status-log")
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

        # Agent Grid
        try:
            agents = self._store.build_agent_list(state)
            self.query_one("#swarm-agent-grid", AgentGrid).update_agents(agents)
        except Exception:
            pass

        # Task Board
        try:
            tasks = self._store.build_task_list(state)
            self.query_one("#swarm-task-board", TaskBoard).update_tasks(tasks)
        except Exception:
            pass

        # DAG View
        try:
            dag_nodes = self._store.build_dag_nodes(state)
            self.query_one("#swarm-dag-view", DependencyDAGView).update_dag(dag_nodes)
        except Exception:
            pass

        # Event Timeline
        try:
            raw_events = self._store.read_events(limit=200)
            self._last_events = self._store.build_event_list(raw_events)
            self.query_one("#swarm-timeline", EventTimeline).update_events(
                self._last_events[-60:]
            )
        except Exception:
            pass

        # File Activity Map
        try:
            activity = self._store.read_file_activity()
            self.query_one("#swarm-file-activity", FileActivityMap).update_activity(
                activity
            )
        except Exception:
            pass

        # Status Footer
        budget = state.get("budget", {})
        merge = state.get("merge_queue", {})
        dag_summary = state.get("dag_summary", {})
        elapsed_s = state.get("elapsed_s", 0)
        if isinstance(elapsed_s, (int, float)):
            mins = int(elapsed_s) // 60
            secs = int(elapsed_s) % 60
            elapsed_str = f"{mins}m{secs:02d}s"
        else:
            elapsed_str = ""

        total_tasks = sum(dag_summary.values()) if isinstance(dag_summary, dict) else 0
        try:
            self.query_one("#swarm-status-footer", SwarmStatusFooter).update_status(
                phase=state.get("phase", "unknown"),
                level=str(state.get("current_level", "?")),
                active=dag_summary.get("running", 0) if isinstance(dag_summary, dict) else 0,
                done=dag_summary.get("done", 0) if isinstance(dag_summary, dict) else 0,
                total=total_tasks,
                cost=float(budget.get("cost_used_usd", 0.0)),
                elapsed=elapsed_str,
            )
        except Exception:
            pass

        # Status log line
        try:
            raw_events_count = len(self._last_events)
            self.query_one("#status-log", Static).update(
                f"run_dir={self._store.run_dir} | events={raw_events_count} "
                f"| seq={state.get('state_seq', 0)} "
                f"| merge: pending={merge.get('pending', 0)} "
                f"review={merge.get('in_review', 0)} merged={merge.get('merged', 0)}"
            )
        except Exception:
            pass

    # ── Selection handlers ───────────────────────────────────────────

    def on_agent_card_selected(self, event: AgentCard.Selected) -> None:
        state = self._store.read_state()
        detail = self._store.build_agent_detail(event.agent_id, state)
        if detail:
            try:
                self.query_one("#swarm-detail", DetailInspector).inspect(detail)
            except Exception:
                pass

    def on_task_card_selected(self, event: TaskCard.Selected) -> None:
        detail = self._store.build_task_detail(event.task_id)
        if detail:
            try:
                self.query_one("#swarm-detail", DetailInspector).inspect(detail)
            except Exception:
                pass

    # ── Actions ──────────────────────────────────────────────────────

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
            try:
                self.query_one("#status-log", Static).update(
                    "No agents available for message injection"
                )
            except Exception:
                pass
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
        try:
            self.query_one("#status-log", Static).update(
                f"Injected control message to {agent_id}"
            )
        except Exception:
            pass

    def action_focus_agent(self) -> None:
        """Push FocusScreen for single-agent stream view."""
        from attocode.tui.screens.focus_screen import FocusScreen

        self.push_screen(FocusScreen(state_fn=self._state_fn_adapter))

    def action_fullscreen_timeline(self) -> None:
        """Push TimelineScreen for full-screen event view."""
        from attocode.tui.screens.timeline_screen import TimelineScreen

        self.push_screen(TimelineScreen(state_fn=self._state_fn_adapter))

    def action_cycle_focus(self) -> None:
        """Cycle keyboard focus between panels."""
        self.focus_next()

    # ── Helpers ──────────────────────────────────────────────────────

    def _state_fn_adapter(self) -> dict[str, Any]:
        """Adapter that wraps StateStore for FocusScreen/TimelineScreen.

        These screens expect a ``state_fn()`` callable returning a state dict
        with ``active_agents`` and ``events`` keys.
        """
        state = self._store.read_state()
        state["events"] = self._last_events
        return state
