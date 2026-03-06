"""Swarm monitor screen - single-instance multi-run fleet view."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.timer import Timer
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


def _safe_tail_jsonl(path: Path, limit: int = 100) -> list[dict[str, Any]]:
    """Read the last *limit* JSON objects from a JSONL file.

    Uses a seek-from-end strategy to avoid reading the entire file.
    """
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        # Read only the tail of the file to avoid slurping huge event logs
        file_size = path.stat().st_size
        read_bytes = min(file_size, limit * 512)  # ~512 bytes per event line
        with open(path, "rb") as f:
            if read_bytes < file_size:
                f.seek(file_size - read_bytes)
                f.readline()  # skip partial first line
            data = f.read().decode("utf-8", errors="replace")
        for line in data.splitlines()[-limit:]:
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                out.append(item)
    except Exception:
        pass
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
        self._poll_timer: Timer | None = None
        self._refresh_count: int = 0

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

        self._poll_timer = self.set_interval(2.0, self._refresh_all)
        self._refresh_all()

    def on_unmount(self) -> None:
        if self._poll_timer:
            self._poll_timer.stop()
            self._poll_timer = None

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
        self._refresh_count += 1
        # Only re-discover run dirs every 5th tick (expensive glob)
        if self._refresh_count % 5 == 1 or not self._run_dirs:
            self._run_dirs = self._discover_run_dirs()
        self._refresh_fleet()
        if self._selected_run is not None:
            self._refresh_run_detail()

    def _discover_run_dirs(self) -> list[Path]:
        out: list[Path] = []
        seen: set[Path] = set()
        # Event bridge writes state.json (not swarm.state.json)
        for pattern in ("**/state.json", "**/swarm.state.json"):
            for state in self._root.glob(pattern):
                run_dir = state.parent
                if run_dir in seen:
                    continue
                seen.add(run_dir)
                out.append(run_dir)
        return sorted(out)

    def _refresh_fleet(self) -> None:
        table = self.query_one("#fleet-table", DataTable)
        table.clear(columns=False)
        for run_dir in self._run_dirs:
            # Try state.json first (event bridge format), fallback to swarm.state.json
            state = _safe_read_json(run_dir / "state.json")
            if not state:
                state = _safe_read_json(run_dir / "swarm.state.json")

            # Handle event bridge schema: status.phase, status.queue, status.active_workers
            status = state.get("status", {}) if isinstance(state.get("status"), dict) else {}
            phase = str(status.get("phase", state.get("phase", "unknown")))
            queue = status.get("queue", {}) if isinstance(status.get("queue"), dict) else {}
            task_text = (
                f"r{queue.get('ready', 0)} "
                f"ru{queue.get('running', 0)} "
                f"d{queue.get('completed', 0)} "
                f"f{queue.get('failed', 0)}"
            )
            agents = status.get("active_workers", []) if isinstance(status.get("active_workers"), list) else []
            err_count = len(state.get("errors", [])) if isinstance(state.get("errors"), list) else 0
            updated = str(state.get("timestamp", ""))[-8:]
            table.add_row(str(run_dir), phase, task_text, str(len(agents)), str(err_count), updated)

    def _refresh_run_detail(self) -> None:
        if self._selected_run is None:
            return
        # Try state.json first, fallback to swarm.state.json
        state = _safe_read_json(self._selected_run / "state.json")
        if not state:
            state = _safe_read_json(self._selected_run / "swarm.state.json")

        # Handle event bridge schema: status.phase, status.budget
        status = state.get("status", {}) if isinstance(state.get("status"), dict) else {}
        phase = str(status.get("phase", state.get("phase", "unknown")))
        budget = status.get("budget", {}) if isinstance(status.get("budget"), dict) else {}
        tokens_used = int(budget.get("tokens_used", 0))
        tokens_total = int(budget.get("tokens_total", 0))
        cost_used = float(budget.get("cost_used", 0.0))
        cost_total = float(budget.get("cost_total", 0.0))
        title_text = f"Run: {self._selected_run} | Phase: {phase}"
        if tokens_total > 0 or cost_total > 0:
            title_text += f" | Budget: {tokens_used:,}/{tokens_total:,} tok (${cost_used:.2f}/${cost_total:.2f})"
        self.query_one("#swarm-monitor-title", Static).update(title_text)

        # --- Tasks table: read from state.tasks dict ---
        tasks_table = self.query_one("#run-tasks", DataTable)
        tasks_table.clear(columns=False)
        tasks_data = state.get("tasks", {})
        if isinstance(tasks_data, dict):
            for task_id, t in tasks_data.items():
                # Also try reading per-task detail file
                safe_id = task_id.replace("/", "_").replace("\\", "_")
                detail = _safe_read_json(self._selected_run / "tasks" / f"{safe_id}.json")
                tasks_table.add_row(
                    task_id,
                    str(t.get("status", "")),
                    str(t.get("type", "")),
                    str(detail.get("role_hint", t.get("assigned_model", ""))),
                    str(t.get("attempts", 0)),
                    str(t.get("description", ""))[:60],
                    str(t.get("failure_mode", "") or "")[:60],
                )

        # --- Events table: read from events.jsonl ---
        events_table = self.query_one("#run-events", DataTable)
        events_table.clear(columns=False)
        all_events = _safe_tail_jsonl(self._selected_run / "events.jsonl", limit=100)
        visible = [ev for ev in all_events if ev.get("type") not in HIDDEN_EVENT_TYPES]
        for ev in visible[-50:]:
            # Event bridge writes {seq, timestamp, type, data}
            data = ev.get("data", {}) if isinstance(ev.get("data"), dict) else {}
            payload = ev.get("payload", data)  # compat: try payload then data
            message = (
                payload.get("message")
                or payload.get("reason")
                or payload.get("event_type")
                or ""
            )
            files = payload.get("files")
            if isinstance(files, list) and files:
                message = ", ".join(files[:5])
                if len(files) > 5:
                    message += f" (+{len(files) - 5} more)"
            events_table.add_row(
                str(ev.get("timestamp", ""))[-8:],
                str(ev.get("type", "")),
                str(payload.get("agent_id", payload.get("worker_name", ""))),
                str(payload.get("task_id", "")),
                str(message)[:80],
            )

        # --- Agents table: read from status.active_workers ---
        agents_table = self.query_one("#run-agents", DataTable)
        agents_table.clear(columns=False)
        active_workers = status.get("active_workers", []) if isinstance(status.get("active_workers"), list) else []
        for agent in active_workers:
            cwd = str(agent.get("cwd", ""))
            agents_table.add_row(
                str(agent.get("worker_name", agent.get("agent_id", ""))),
                str(agent.get("role_id", "")),
                str(agent.get("role_type", "")),
                str(agent.get("model", agent.get("backend", ""))),
                "running" if agent.get("task_id") else "idle",
                str(agent.get("task_id", "")),
                _short_cwd(cwd) if cwd else ".",
                str(agent.get("restart_count", 0)),
            )
