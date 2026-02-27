"""Dependency DAG View — ASCII DAG with status colors per node."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


_STATUS_SYMBOLS = {
    "pending": "\u25cb",    # ○
    "running": "\u21bb",    # ↻
    "done": "\u2713",       # ✓
    "failed": "\u2717",     # ✗
    "skipped": "\u2212",    # −
}

_STATUS_COLORS = {
    "pending": "dim",
    "running": "cyan bold",
    "done": "green",
    "failed": "red bold",
    "skipped": "yellow dim",
}


class DependencyDAGView(Static):
    """Renders an AoT DAG as colored ASCII text.

    Input format: list of node dicts with keys:
        task_id, status, depends_on, level
    """

    DEFAULT_CSS = """
    DependencyDAGView {
        height: auto;
        min-height: 4;
        max-height: 20;
        overflow-y: auto;
        padding: 0 1;
    }
    """

    dag_data: reactive[list[dict[str, Any]]] = reactive(list)

    def watch_dag_data(self, data: list[dict[str, Any]]) -> None:
        self._render_dag(data)

    def update_dag(self, nodes: list[dict[str, Any]]) -> None:
        """External API."""
        self.dag_data = nodes

    def _render_dag(self, nodes: list[dict[str, Any]]) -> None:
        if not nodes:
            self.update(Text("(no DAG data)", style="dim"))
            return

        # Group by level
        by_level: dict[int, list[dict[str, Any]]] = {}
        for n in nodes:
            lvl = n.get("level", 0)
            by_level.setdefault(lvl, []).append(n)

        text = Text()
        max_level = max(by_level.keys()) if by_level else 0

        for level in range(max_level + 1):
            level_nodes = by_level.get(level, [])
            if level > 0:
                # Draw connection lines
                text.append("  " + "  |  " * len(level_nodes) + "\n", style="dim")

            for i, node in enumerate(level_nodes):
                tid = node.get("task_id", "?")
                status = node.get("status", "pending")
                symbol = _STATUS_SYMBOLS.get(status, "?")
                color = _STATUS_COLORS.get(status, "")

                if i > 0:
                    text.append("  ", style="dim")

                desc = node.get("description", "")[:40]
                text.append("[", style="dim")
                text.append(f"{symbol}", style=color)
                text.append(f" {tid[:12]}", style=color)
                if desc:
                    text.append(f" {desc}", style="dim")
                text.append("]", style="dim")

                # Draw horizontal edge to next sibling
                deps = node.get("depended_by", [])
                if deps and i < len(level_nodes) - 1:
                    text.append("\u2500\u2500", style="dim")

            text.append("\n")

        self.update(text)
