"""Dependency DAG View — ASCII DAG with status colors per node."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, Tree

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


class DependencyTree(Widget):
    """Tree widget showing task dependency hierarchy.

    Roots = tasks with no deps.  Children = tasks that depend on parent.
    Posts ``DependencyTree.NodeSelected`` on tree node selection.
    """

    class NodeSelected(Message):
        """Posted when a tree node is selected."""

        def __init__(self, task_id: str) -> None:
            super().__init__()
            self.task_id = task_id

    DEFAULT_CSS = """
    DependencyTree {
        height: 1fr;
    }
    DependencyTree > Tree {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._dag_nodes: list[dict[str, Any]] = []
        self._agent_map: dict[str, dict[str, str]] = {}
        self._prev_structure_hash: str = ""
        self._node_map: dict[str, Any] = {}  # task_id -> TreeNode
        self._prev_statuses: dict[str, str] = {}  # task_id -> status

    def compose(self):
        tree: Tree[str] = Tree("Tasks", id="dep-tree")
        tree.show_root = False
        yield tree

    def update_dag(
        self,
        nodes: list[dict[str, Any]],
        edges: list[Any] | None = None,
        agents: list[dict[str, Any]] | None = None,
    ) -> None:
        """Rebuild the tree from nodes and edges.

        Args:
            agents: Optional agent list (from build_agent_list) to annotate
                    tree nodes with agent assignment and activity.
        """
        self._dag_nodes = nodes
        # Build task_id -> agent info lookup
        self._agent_map = {}
        if agents:
            for ag in agents:
                task_id = ag.get("task_id", "")
                if task_id:
                    self._agent_map[task_id] = {
                        "agent_id": ag.get("agent_id", ""),
                        "activity": ag.get("activity", ""),
                    }
        self._rebuild(edges)

    @staticmethod
    def _make_label(
        task_id: str,
        status: str,
        title: str,
        agent_info: dict[str, str] | None = None,
    ) -> Text:
        icon = _STATUS_SYMBOLS.get(status, "?")
        color = _STATUS_COLORS.get(status, "")
        label = Text()
        label.append(f"{icon} ", style=color)
        label.append(task_id, style="bold")
        label.append(f" \u2014 {title[:40]}", style="dim")
        label.append(f" [{status}]", style=color)
        if agent_info:
            aid = agent_info.get("agent_id", "")
            act = agent_info.get("activity", "")
            if aid:
                label.append(f" @{aid}", style="cyan")
            if act:
                label.append(f" ({act})", style="italic dim")
        return label

    def _rebuild(self, edges: list[Any] | None = None) -> None:
        try:
            tree = self.query_one("#dep-tree", Tree)
        except Exception:
            return

        if not self._dag_nodes:
            tree.clear()
            self._prev_structure_hash = ""
            self._node_map.clear()
            self._prev_statuses.clear()
            return

        # Build dependency map: task_id -> [dep task_ids]
        deps_map: dict[str, list[str]] = {}
        for n in self._dag_nodes:
            tid = str(n.get("task_id", ""))
            deps = n.get("depends_on", [])
            if isinstance(deps, list):
                deps_map[tid] = [str(d) for d in deps]
            else:
                deps_map[tid] = []

        # Also parse edges if provided
        if edges:
            for edge in edges:
                if isinstance(edge, (list, tuple)) and len(edge) >= 2:
                    src, tgt = str(edge[0]), str(edge[1])
                elif isinstance(edge, dict):
                    src = str(edge.get("source", edge.get("from", "")))
                    tgt = str(edge.get("target", edge.get("to", "")))
                else:
                    continue
                if tgt:
                    deps_map.setdefault(tgt, []).append(src)

        # Compute structure hash from task IDs + edges
        node_map = {str(n.get("task_id", "")): n for n in self._dag_nodes}
        sorted_ids = sorted(node_map.keys())
        edge_strs = sorted(
            f"{tid}:{','.join(sorted(ds))}" for tid, ds in deps_map.items() if ds
        )
        structure_hash = f"{','.join(sorted_ids)}|{'|'.join(edge_strs)}"

        if structure_hash == self._prev_structure_hash and self._node_map:
            # Structure unchanged — only update labels for changed statuses
            for tid, node in node_map.items():
                status = node.get("status", "pending")
                if status != self._prev_statuses.get(tid):
                    tree_node = self._node_map.get(tid)
                    if tree_node is not None:
                        title = node.get("title", "")
                        tree_node.set_label(
                            self._make_label(tid, status, title, self._agent_map.get(tid))
                        )
                    self._prev_statuses[tid] = status
            return

        # Full rebuild (structure changed or first time)
        tree.clear()
        self._node_map.clear()
        self._prev_statuses.clear()

        # Build reverse map: parent -> [children who depend on parent]
        children_map: dict[str, list[str]] = {}
        for tid, deps in deps_map.items():
            for dep in deps:
                children_map.setdefault(dep, []).append(tid)

        # Roots = nodes with no deps
        roots = [tid for tid in node_map if not deps_map.get(tid)]
        if not roots:
            roots = list(node_map.keys())

        added: set[str] = set()

        def _add_node(parent_branch: Any, task_id: str, depth: int = 0) -> None:
            if task_id in added or depth > 20:
                return
            added.add(task_id)

            node = node_map.get(task_id, {})
            status = node.get("status", "pending")
            title = node.get("title", "")

            label = self._make_label(task_id, status, title, self._agent_map.get(task_id))
            self._prev_statuses[task_id] = status

            kids = children_map.get(task_id, [])
            if kids:
                branch = parent_branch.add(label, data=task_id, expand=True)
                self._node_map[task_id] = branch
                for child_id in kids:
                    _add_node(branch, child_id, depth + 1)
            else:
                leaf = parent_branch.add_leaf(label, data=task_id)
                self._node_map[task_id] = leaf

        for root_id in roots:
            _add_node(tree.root, root_id)

        self._prev_structure_hash = structure_hash

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.node.data:
            self.post_message(self.NodeSelected(str(event.node.data)))
