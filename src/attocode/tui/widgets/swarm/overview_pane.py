"""Tab 1: Overview pane — existing layout compressed into a single tab."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget

from attocode.tui.widgets.swarm.agent_grid import AgentGrid
from attocode.tui.widgets.swarm.dag_view import DependencyTree
from attocode.tui.widgets.swarm.event_timeline import EventTimeline
from attocode.tui.widgets.swarm.task_board import TaskBoard


class OverviewPane(Widget):
    """3-row layout: AgentGrid (top strip) + TaskBoard/DAG (flex middle) + EventTimeline (bottom strip)."""

    DEFAULT_CSS = """
    OverviewPane {
        height: 1fr;
    }
    OverviewPane #overview-agents {
        height: auto;
        max-height: 8;
    }
    OverviewPane #overview-main {
        height: 1fr;
    }
    OverviewPane #overview-main-left {
        width: 2fr;
    }
    OverviewPane #overview-main-right {
        width: 1fr;
    }
    OverviewPane #overview-events {
        height: auto;
        max-height: 12;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="overview-agents"):
            yield AgentGrid(id="ov-agent-grid")
        with Horizontal(id="overview-main"):
            with Vertical(id="overview-main-left"):
                yield TaskBoard(id="ov-task-board")
            with Vertical(id="overview-main-right"):
                yield DependencyTree(id="ov-dag-tree")
        with Vertical(id="overview-events"):
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
            # Use interactive DependencyTree with full node data
            agents = state.get("status", {}).get("active_workers", [])
            self.query_one("#ov-dag-tree", DependencyTree).update_dag(
                tasks_list, edges=state.get("edges", []), agents=agents,
            )
        except Exception:
            pass
        try:
            self.query_one("#ov-timeline", EventTimeline).update_events(
                state.get("timeline", [])
            )
        except Exception:
            pass
