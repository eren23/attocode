"""Tab 1: Overview pane — existing layout compressed into a single tab."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget

from attocode.tui.widgets.swarm.agent_grid import AgentGrid
from attocode.tui.widgets.swarm.dag_view import DependencyDAGView
from attocode.tui.widgets.swarm.event_timeline import EventTimeline
from attocode.tui.widgets.swarm.task_board import TaskBoard


class OverviewPane(Widget):
    """2x2 grid: AgentGrid + TaskBoard + DAG + EventTimeline."""

    DEFAULT_CSS = """
    OverviewPane {
        height: 1fr;
    }
    OverviewPane #overview-top {
        height: 1fr;
    }
    OverviewPane #overview-bottom {
        height: 1fr;
    }
    OverviewPane #overview-top-left {
        width: 2fr;
    }
    OverviewPane #overview-top-right {
        width: 1fr;
    }
    OverviewPane #overview-bottom-left {
        width: 2fr;
    }
    OverviewPane #overview-bottom-right {
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="overview-top"):
            with Vertical(id="overview-top-left"):
                yield AgentGrid(id="ov-agent-grid")
            with Vertical(id="overview-top-right"):
                yield DependencyDAGView(id="ov-dag")
        with Horizontal(id="overview-bottom"):
            with Vertical(id="overview-bottom-left"):
                yield TaskBoard(id="ov-task-board")
            with Vertical(id="overview-bottom-right"):
                yield EventTimeline(id="ov-timeline")

    def update_state(self, state: dict[str, Any]) -> None:
        """Push state to child widgets."""
        # Convert tasks dict → list for sub-widgets that expect lists
        tasks_raw = state.get("tasks", {})
        if isinstance(tasks_raw, dict):
            tasks_list = list(tasks_raw.values())
        else:
            tasks_list = list(tasks_raw) if tasks_raw else []

        try:
            self.query_one("#ov-agent-grid", AgentGrid).update_agents(
                state.get("status", {}).get("active_workers", [])
            )
        except Exception:
            pass
        try:
            self.query_one("#ov-task-board", TaskBoard).update_tasks(tasks_list)
        except Exception:
            pass
        try:
            # Build DAG nodes with level info from edges
            dag_nodes = _tasks_to_dag_nodes(tasks_list, state.get("edges", []))
            self.query_one("#ov-dag", DependencyDAGView).update_dag(dag_nodes)
        except Exception:
            pass
        try:
            self.query_one("#ov-timeline", EventTimeline).update_events(
                state.get("timeline", [])
            )
        except Exception:
            pass


def _tasks_to_dag_nodes(
    tasks: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Convert flat task list + edges into DAG nodes with level info.

    Each node gets: task_id, status, level, depended_by.
    Level is computed via topological ordering from edges.
    """
    if not tasks:
        return []

    # Build adjacency: parent → children
    children_of: dict[str, list[str]] = {}
    parents_of: dict[str, list[str]] = {}
    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src and tgt:
            children_of.setdefault(src, []).append(tgt)
            parents_of.setdefault(tgt, []).append(src)

    # Compute levels via BFS from roots
    task_ids = {t.get("id", t.get("task_id", "")) for t in tasks}
    levels: dict[str, int] = {}
    roots = [tid for tid in task_ids if tid not in parents_of]
    queue = [(r, 0) for r in roots]
    while queue:
        tid, lvl = queue.pop(0)
        if tid in levels:
            levels[tid] = max(levels[tid], lvl)
        else:
            levels[tid] = lvl
        for child in children_of.get(tid, []):
            queue.append((child, lvl + 1))

    # Assign level 0 to any task not reached
    for t in tasks:
        tid = t.get("id", t.get("task_id", ""))
        if tid not in levels:
            levels[tid] = 0

    # Build node list
    nodes: list[dict[str, Any]] = []
    for t in tasks:
        tid = t.get("id", t.get("task_id", ""))
        nodes.append({
            "task_id": tid,
            "description": t.get("description", t.get("title", "")),
            "status": _normalize_status(t.get("status", "pending")),
            "level": levels.get(tid, 0),
            "depended_by": children_of.get(tid, []),
        })

    return sorted(nodes, key=lambda n: (n["level"], n["task_id"]))


def _normalize_status(status: str) -> str:
    """Map event bridge status values to display bucket names."""
    mapping = {
        "pending": "pending",
        "ready": "pending",
        "dispatched": "running",
        "completed": "done",
        "failed": "failed",
        "skipped": "skipped",
        "decomposed": "skipped",
    }
    return mapping.get(status, "pending")
