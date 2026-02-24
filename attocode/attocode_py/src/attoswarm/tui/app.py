"""Textual app for attoswarm dashboard (operations view)."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

from attoswarm.protocol.io import read_json, write_json_atomic
from attoswarm.protocol.models import utc_now_iso
from attoswarm.tui.stores import StateStore


class AttoswarmApp(App[None]):
    TITLE = "Attoswarm"
    BINDINGS = [
        Binding("p", "pause_resume", "Pause/Resume"),
        Binding("i", "inject_message", "Inject Message"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("l", "toggle_logs", "Toggle Logs"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, run_dir: str) -> None:
        super().__init__()
        self._store = StateStore(run_dir)
        self._show_logs = True

        self._phase = Static("Phase: init", id="phase")
        self._budget = Static("Budget: 0/0", id="budget")

        self._agents = DataTable(id="agents")
        self._tasks = DataTable(id="tasks")
        self._timeline = DataTable(id="timeline")

        self._task_detail = Static("", id="task-detail")
        self._agent_detail = Static("", id="agent-detail")
        self._errors = Static("", id="errors")
        self._status_log = Static("", id="status-log")
        self._selected_task_id: str | None = None
        self._selected_agent_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="overview-tabs") as tabs:
            with TabPane("Overview", id="overview-tabs"):
                yield Horizontal(self._agents, self._tasks, id="overview")
            with TabPane("Timeline", id="timeline-tab"):
                yield self._timeline
            with TabPane("Task Detail", id="task-detail-tab"):
                yield self._task_detail
            with TabPane("Agent Detail", id="agent-detail-tab"):
                yield self._agent_detail
            with TabPane("Errors", id="errors-tab"):
                yield self._errors
        yield Vertical(
            self._phase,
            self._budget,
            tabs,
            self._status_log,
        )
        yield Footer()

    def on_mount(self) -> None:
        self._agents.add_columns("Agent", "Role", "Type", "Backend", "Status", "Task")
        self._tasks.add_columns("Task", "State", "Kind", "Role", "Attempts", "Title")
        self._timeline.add_columns("Time", "Type", "Agent", "Task", "Message")
        self.set_interval(0.5, self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        state = self._store.read_state()
        phase = state.get("phase", "unknown")
        self._phase.update(f"Phase: {phase}")

        budget = state.get("budget", {})
        merge = state.get("merge_queue", {})
        self._budget.update(
            "Budget: "
            f"{budget.get('tokens_used', 0)}/{budget.get('tokens_max', 0)} tokens, "
            f"${budget.get('cost_used_usd', 0.0)}/${budget.get('cost_max_usd', 0.0)} | "
            f"Merge: pending={merge.get('pending', 0)} review={merge.get('in_review', 0)} merged={merge.get('merged', 0)}"
        )

        self._agents.clear(columns=False)
        active = state.get("active_agents", [])
        for row in active:
            self._agents.add_row(
                str(row.get("agent_id", "")),
                str(row.get("role_id", "")),
                str(row.get("role_type", "")),
                str(row.get("backend", "")),
                str(row.get("status", "")),
                str(row.get("task_id", "")),
            )

        self._tasks.clear(columns=False)
        attempts = state.get("attempts", {}).get("by_task", {}) if isinstance(state.get("attempts"), dict) else {}
        nodes = state.get("dag", {}).get("nodes", [])
        task_ids: list[str] = []
        for node in nodes:
            task_id = str(node.get("task_id", ""))
            task_ids.append(task_id)
            detail = self._store.read_task(task_id)
            self._tasks.add_row(
                task_id,
                str(node.get("status", "")),
                str(detail.get("task_kind", "")),
                str(detail.get("role_hint", "")),
                str(attempts.get(task_id, detail.get("attempts", 0))),
                str(node.get("title", "")),
            )

        self._timeline.clear(columns=False)
        events = self._store.read_events(limit=200)
        for ev in events[-60:]:
            payload = ev.get("payload", {}) if isinstance(ev.get("payload"), dict) else {}
            msg = (
                payload.get("message")
                or payload.get("debug_detail")
                or payload.get("debug_marker")
                or payload.get("reason")
                or payload.get("event_type")
                or ""
            )
            self._timeline.add_row(
                str(ev.get("timestamp", ""))[-8:],
                str(ev.get("type", "")),
                str(payload.get("agent_id", "")),
                str(payload.get("task_id", payload.get("task", ""))),
                str(msg)[:90],
            )

        if task_ids and (not self._selected_task_id or self._selected_task_id not in task_ids):
            self._selected_task_id = task_ids[0]
        if active and (not self._selected_agent_id or self._selected_agent_id not in {str(a.get("agent_id", "")) for a in active}):
            self._selected_agent_id = str(active[0].get("agent_id", ""))

        self._render_task_detail(state)
        self._render_agent_detail(state)

        errs = state.get("errors", []) if isinstance(state.get("errors"), list) else []
        self._errors.update("\n".join(str(e) for e in errs[-20:]) or "No errors")

        if self._show_logs:
            self._status_log.update(
                f"run_dir={self._store.run_dir} | events={len(events)} | state_seq={state.get('state_seq', 0)}"
            )
        else:
            self._status_log.update("")

    def _render_task_detail(self, state: dict) -> None:
        if not self._selected_task_id:
            self._task_detail.update("No task selected")
            return
        task = self._store.read_task(self._selected_task_id)
        transitions = task.get("transitions", []) if isinstance(task.get("transitions"), list) else []
        transition_lines = [
            f"{t.get('timestamp', '')} {t.get('from_state', '')}->{t.get('to_state', '')} by {t.get('actor', '')} ({t.get('reason', '')})"
            for t in transitions[-8:]
            if isinstance(t, dict)
        ]
        self._task_detail.update(
            f"task={self._selected_task_id}\n"
            f"title={task.get('title', '')}\n"
            f"status={task.get('status', '')} kind={task.get('task_kind', '')} role={task.get('role_hint', '')}\n"
            f"attempts={task.get('attempts', 0)} assigned_agent={task.get('assigned_agent_id', '')}\n"
            f"last_error={task.get('last_error', '')}\n"
            f"description={task.get('description', '')}\n"
            "recent_transitions:\n"
            + ("\n".join(transition_lines) if transition_lines else "(none)")
        )

    def _render_agent_detail(self, state: dict) -> None:
        if not self._selected_agent_id:
            self._agent_detail.update("No agent selected")
            return
        agent_rows = state.get("active_agents", [])
        row = next((a for a in agent_rows if str(a.get("agent_id", "")) == self._selected_agent_id), None)
        if not isinstance(row, dict):
            self._agent_detail.update("No agent selected")
            return
        inbox = self._store.read_agent_box(self._selected_agent_id, "inbox")
        outbox = self._store.read_agent_box(self._selected_agent_id, "outbox")
        out_events = outbox.get("events", []) if isinstance(outbox.get("events"), list) else []
        last = out_events[-1] if out_events else {}
        recent = [
            f"{ev.get('timestamp', '')} {ev.get('type', '')} {str(ev.get('payload', {})).replace(chr(10), ' ')[:120]}"
            for ev in out_events[-6:]
            if isinstance(ev, dict)
        ]
        self._agent_detail.update(
            f"agent={self._selected_agent_id} role={row.get('role_id', '')} type={row.get('role_type', '')}\n"
            f"backend={row.get('backend', '')} status={row.get('status', '')} task={row.get('task_id', '')}\n"
            f"cwd={row.get('cwd', '')}\n"
            f"command={row.get('command', '')}\n"
            f"exit_code={row.get('exit_code', '')} restart_count={row.get('restart_count', 0)}\n"
            f"stderr_tail={row.get('stderr_tail', '')}\n"
            f"inbox_messages={len(inbox.get('messages', []))} outbox_events={len(out_events)}\n"
            f"last_outbox={last}\n"
            "recent_outbox:\n"
            + ("\n".join(recent) if recent else "(none)")
        )

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
            self._status_log.update("No agents available for message injection")
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
        self._status_log.update(f"Injected control message to {agent_id}")

    def action_toggle_logs(self) -> None:
        self._show_logs = not self._show_logs
        self._refresh()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        try:
            if event.data_table.id == "tasks":
                cell = event.data_table.get_cell(event.cursor_row, 0)
                self._selected_task_id = str(cell)
                self._render_task_detail(self._store.read_state())
            elif event.data_table.id == "agents":
                cell = event.data_table.get_cell(event.cursor_row, 0)
                self._selected_agent_id = str(cell)
                self._render_agent_detail(self._store.read_state())
        except Exception:
            # Keep monitor stable across Textual minor API differences.
            return
