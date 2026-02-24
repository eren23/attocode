"""Swarm monitor screen - single-instance multi-run fleet view."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import ContentSwitcher, DataTable, Footer, Static


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _short_cwd(cwd: str) -> str:
    """Shorten a CWD path to its last 2 components (e.g. 'worktrees/impl-1')."""
    parts = Path(cwd).parts
    if len(parts) <= 2:
        return cwd
    return str(Path(*parts[-2:]))


HIDDEN_EVENT_TYPES = {"heartbeat", "stderr"}


def _safe_tail_jsonl(path: Path, limit: int = 300) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    for line in lines[-max(limit, 1):]:
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


class SwarmMonitorScreen(Screen):
    """Fleet monitor for all swarm run directories under a workspace."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=True, priority=True),
        Binding("tab", "next_view", "Next", show=False),
        Binding("shift+tab", "prev_view", "Prev", show=False),
        Binding("enter", "open_selected", "Open", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    def __init__(self, root: str | Path = ".", **kwargs) -> None:
        super().__init__(**kwargs)
        self._root = Path(root)
        self._run_dirs: list[Path] = []
        self._selected_run: Path | None = None
        self._active_view = "fleet"

    def compose(self) -> ComposeResult:
        with Vertical(id="swarm-monitor"):
            yield Static("Swarm Monitor", id="swarm-monitor-title")
            with ContentSwitcher(id="swarm-monitor-switcher", initial="fleet"):
                with Vertical(id="fleet"):
                    yield DataTable(id="fleet-table")
                with Horizontal(id="run-detail"):
                    yield DataTable(id="run-tasks")
                    yield DataTable(id="run-events")
                    yield DataTable(id="run-agents")
            yield Static("[Enter] open run  [Tab] switch view  [r] refresh  [Esc] close", id="swarm-monitor-hint")
        yield Footer()

    def on_mount(self) -> None:
        fleet = self.query_one("#fleet-table", DataTable)
        fleet.add_columns("Run Dir", "Phase", "Tasks", "Agents", "Errors", "Updated")

        tasks = self.query_one("#run-tasks", DataTable)
        tasks.add_columns("Task", "State", "Kind", "Role", "Attempts", "Title", "Error")

        events = self.query_one("#run-events", DataTable)
        events.add_columns("Time", "Type", "Agent", "Task", "Message")

        agents = self.query_one("#run-agents", DataTable)
        agents.add_columns("Agent", "Role", "Type", "Backend", "Status", "Task", "CWD", "Restarts")

        self.set_interval(1.0, self._refresh_all)
        self._refresh_all()

    def action_close(self) -> None:
        self.dismiss()

    def action_refresh(self) -> None:
        self._refresh_all()

    def action_next_view(self) -> None:
        self._active_view = "run-detail" if self._active_view == "fleet" else "fleet"
        self.query_one("#swarm-monitor-switcher", ContentSwitcher).current = self._active_view

    def action_prev_view(self) -> None:
        self.action_next_view()

    def action_open_selected(self) -> None:
        if self._active_view == "fleet":
            table = self.query_one("#fleet-table", DataTable)
            if table.cursor_row is None or table.cursor_row < 0:
                return
            if table.cursor_row >= len(self._run_dirs):
                return
            self._selected_run = self._run_dirs[table.cursor_row]
            self._active_view = "run-detail"
            self.query_one("#swarm-monitor-switcher", ContentSwitcher).current = self._active_view
            self._refresh_run_detail()

    def _refresh_all(self) -> None:
        self._refresh_fleet()
        if self._selected_run is not None:
            self._refresh_run_detail()

    def _discover_run_dirs(self) -> list[Path]:
        roots = [self._root]
        # Prefer workspace-local .agent but also allow deeper scans from root.
        out: list[Path] = []
        seen: set[Path] = set()
        for root in roots:
            for state in root.glob("**/swarm.state.json"):
                run_dir = state.parent
                if run_dir in seen:
                    continue
                seen.add(run_dir)
                out.append(run_dir)
        return sorted(out)

    def _refresh_fleet(self) -> None:
        table = self.query_one("#fleet-table", DataTable)
        table.clear(columns=False)
        self._run_dirs = self._discover_run_dirs()
        for run_dir in self._run_dirs:
            state = _safe_read_json(run_dir / "swarm.state.json")
            phase = str(state.get("phase", "unknown"))
            tasks = state.get("tasks", {}) if isinstance(state.get("tasks"), dict) else {}
            task_text = f"r{tasks.get('ready', 0)} ru{tasks.get('running', 0)} d{tasks.get('done', 0)} f{tasks.get('failed', 0)}"
            agents = state.get("active_agents", []) if isinstance(state.get("active_agents"), list) else []
            err_count = len(state.get("errors", [])) if isinstance(state.get("errors"), list) else 0
            updated = str(state.get("updated_at", ""))[-8:]
            table.add_row(str(run_dir), phase, task_text, str(len(agents)), str(err_count), updated)

    def _refresh_run_detail(self) -> None:
        if self._selected_run is None:
            return
        state = _safe_read_json(self._selected_run / "swarm.state.json")

        # --- Title bar: phase + budget ---
        phase = str(state.get("phase", "unknown"))
        budget = state.get("budget", {}) if isinstance(state.get("budget"), dict) else {}
        tokens_used = int(budget.get("tokens_used", 0))
        max_tokens = int(budget.get("max_tokens", 0))
        cost_used = float(budget.get("cost_used_usd", 0.0))
        max_cost = float(budget.get("max_cost_usd", 0.0))
        title_text = f"Run: {self._selected_run} | Phase: {phase}"
        if max_tokens > 0 or max_cost > 0:
            title_text += f" | Budget: {tokens_used:,}/{max_tokens:,} tok (${cost_used:.2f}/${max_cost:.2f})"
        self.query_one("#swarm-monitor-title", Static).update(title_text)

        # --- Tasks table ---
        tasks_table = self.query_one("#run-tasks", DataTable)
        tasks_table.clear(columns=False)
        attempts = state.get("attempts", {}).get("by_task", {}) if isinstance(state.get("attempts"), dict) else {}
        nodes = state.get("dag", {}).get("nodes", []) if isinstance(state.get("dag"), dict) else []
        for n in nodes:
            task_id = str(n.get("task_id", ""))
            detail = _safe_read_json(self._selected_run / "tasks" / f"task-{task_id}.json")
            tasks_table.add_row(
                task_id,
                str(n.get("status", "")),
                str(detail.get("task_kind", "")),
                str(detail.get("role_hint", "")),
                str(attempts.get(task_id, detail.get("attempts", 0))),
                str(detail.get("title", ""))[:60],
                str(detail.get("last_error", "") or "")[:60],
            )

        # --- Events table: filter heartbeat/stderr noise ---
        events_table = self.query_one("#run-events", DataTable)
        events_table.clear(columns=False)
        all_events = _safe_tail_jsonl(self._selected_run / "swarm.events.jsonl", limit=300)
        heartbeat_count = sum(1 for ev in all_events if ev.get("type") in HIDDEN_EVENT_TYPES)
        visible = [ev for ev in all_events if ev.get("type") not in HIDDEN_EVENT_TYPES]
        for ev in visible[-80:]:
            payload = ev.get("payload", {}) if isinstance(ev.get("payload"), dict) else {}
            message = payload.get("message") or payload.get("reason") or payload.get("event_type") or ""
            # Show file changes inline
            files = payload.get("files")
            if isinstance(files, list) and files:
                message = ", ".join(files[:5])
                if len(files) > 5:
                    message += f" (+{len(files) - 5} more)"
            events_table.add_row(
                str(ev.get("timestamp", ""))[-8:],
                str(ev.get("type", "")),
                str(payload.get("agent_id", "")),
                str(payload.get("task_id", "")),
                str(message)[:80],
            )

        # --- Agents table: add CWD + Restarts ---
        agents_table = self.query_one("#run-agents", DataTable)
        agents_table.clear(columns=False)
        for agent in state.get("active_agents", []) if isinstance(state.get("active_agents"), list) else []:
            cwd = str(agent.get("cwd", ""))
            agents_table.add_row(
                str(agent.get("agent_id", "")),
                str(agent.get("role_id", "")),
                str(agent.get("role_type", "")),
                str(agent.get("backend", "")),
                str(agent.get("status", "")),
                str(agent.get("task_id", "")),
                _short_cwd(cwd) if cwd else ".",
                str(agent.get("restart_count", 0)),
            )
