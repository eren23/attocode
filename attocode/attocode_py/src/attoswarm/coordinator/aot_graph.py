"""Atom-of-Thought DAG — task scheduling via level computation.

Replaces wave-based scheduling.  Tasks form a directed acyclic graph;
level computation determines which tasks can run in parallel at each step.

Level definition:
    level[n] = 0                           if n has no dependencies
    level[n] = 1 + max(level[d] for d in deps)  otherwise
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attocode.integrations.context.ast_service import ASTService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AoTNode:
    """A single node in the AoT DAG."""

    task_id: str
    level: int = -1                     # computed by compute_levels()
    depends_on: list[str] = field(default_factory=list)
    depended_by: list[str] = field(default_factory=list)    # reverse edges
    target_files: list[str] = field(default_factory=list)
    symbol_scope: list[str] = field(default_factory=list)
    status: str = "pending"             # pending | running | done | failed | skipped


class AoTGraph:
    """Directed acyclic graph of tasks with level-based batch scheduling.

    Usage::

        g = AoTGraph()
        g.add_task(AoTNode(task_id="a", depends_on=[]))
        g.add_task(AoTNode(task_id="b", depends_on=["a"]))
        g.compute_levels()
        for batch in g.get_execution_order():
            results = await execute_batch(batch)
            for tid in batch:
                g.mark_complete(tid)
    """

    def __init__(self) -> None:
        self._nodes: dict[str, AoTNode] = {}

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def add_task(self, node: AoTNode) -> None:
        """Add a task node.  Updates reverse edges automatically."""
        self._nodes[node.task_id] = node
        for dep_id in node.depends_on:
            dep = self._nodes.get(dep_id)
            if dep and node.task_id not in dep.depended_by:
                dep.depended_by.append(node.task_id)

    def remove_task(self, task_id: str) -> None:
        """Remove a task and its edges."""
        node = self._nodes.pop(task_id, None)
        if node is None:
            return
        for dep_id in node.depends_on:
            dep = self._nodes.get(dep_id)
            if dep:
                dep.depended_by = [t for t in dep.depended_by if t != task_id]
        for child_id in node.depended_by:
            child = self._nodes.get(child_id)
            if child:
                child.depends_on = [d for d in child.depends_on if d != task_id]

    # ------------------------------------------------------------------
    # Level computation
    # ------------------------------------------------------------------

    def compute_levels(self) -> None:
        """Assign a level to each node using topological BFS.

        Raises ``ValueError`` if the graph contains a cycle.
        """
        in_degree: dict[str, int] = {tid: 0 for tid in self._nodes}
        for node in self._nodes.values():
            for dep_id in node.depends_on:
                if dep_id in in_degree:
                    in_degree[node.task_id] = in_degree.get(node.task_id, 0)
                    # (in_degree is already 0 for dep_id, we count *this* node's incoming)

        # Recount properly
        in_degree = {tid: 0 for tid in self._nodes}
        for node in self._nodes.values():
            for dep_id in node.depends_on:
                if dep_id in self._nodes:
                    in_degree[node.task_id] += 1

        # BFS from roots (in_degree == 0)
        queue: deque[str] = deque()
        for tid, deg in in_degree.items():
            if deg == 0:
                self._nodes[tid].level = 0
                queue.append(tid)

        processed = 0
        while queue:
            tid = queue.popleft()
            processed += 1
            node = self._nodes[tid]
            for child_id in node.depended_by:
                child = self._nodes.get(child_id)
                if child is None:
                    continue
                child.level = max(child.level, node.level + 1)
                in_degree[child_id] -= 1
                if in_degree[child_id] == 0:
                    queue.append(child_id)

        if processed != len(self._nodes):
            raise ValueError(
                f"Cycle detected in AoT graph: processed {processed}/{len(self._nodes)} nodes"
            )

    def get_execution_order(self) -> list[list[str]]:
        """Return task IDs grouped by level: ``[[level_0], [level_1], ...]``."""
        if not self._nodes:
            return []

        max_level = max(n.level for n in self._nodes.values())
        levels: list[list[str]] = [[] for _ in range(max_level + 1)]
        for node in self._nodes.values():
            if node.level >= 0:
                levels[node.level].append(node.task_id)
        return levels

    # ------------------------------------------------------------------
    # Runtime scheduling
    # ------------------------------------------------------------------

    def get_ready_batch(self) -> list[str]:
        """Return task IDs whose dependencies are all complete (done)."""
        ready: list[str] = []
        for node in self._nodes.values():
            if node.status != "pending":
                continue
            deps_met = all(
                self._nodes.get(d) is not None and self._nodes[d].status == "done"
                for d in node.depends_on
            )
            if deps_met:
                ready.append(node.task_id)
        return ready

    def check_parallel_safety(
        self,
        batch: list[str],
        ast_service: "ASTService | None" = None,
    ) -> list[dict[str, Any]]:
        """Check whether tasks in *batch* can safely run in parallel.

        Returns a list of conflict descriptors (empty = safe).
        """
        if ast_service is None:
            return []

        conflicts: list[dict[str, Any]] = []
        ids = list(batch)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a = self._nodes.get(ids[i])
                b = self._nodes.get(ids[j])
                if a is None or b is None:
                    continue
                if not a.target_files or not b.target_files:
                    continue
                detected = ast_service.detect_conflicts(a.target_files, b.target_files)
                for c in detected:
                    c["task_a"] = ids[i]
                    c["task_b"] = ids[j]
                    conflicts.append(c)
        return conflicts

    def mark_complete(self, task_id: str) -> None:
        """Mark a task as done."""
        node = self._nodes.get(task_id)
        if node:
            node.status = "done"

    def mark_running(self, task_id: str) -> None:
        """Mark a task as currently running."""
        node = self._nodes.get(task_id)
        if node:
            node.status = "running"

    def mark_failed(self, task_id: str) -> list[str]:
        """Mark a task as failed and cascade-skip dependents.

        Returns a list of task IDs that were skipped.
        """
        node = self._nodes.get(task_id)
        if node is None:
            return []
        node.status = "failed"

        # Cascade: skip all transitive dependents
        skipped: list[str] = []
        queue: deque[str] = deque(node.depended_by)
        visited: set[str] = set()
        while queue:
            child_id = queue.popleft()
            if child_id in visited:
                continue
            visited.add(child_id)
            child = self._nodes.get(child_id)
            if child and child.status == "pending":
                child.status = "skipped"
                skipped.append(child_id)
                queue.extend(child.depended_by)

        return skipped

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def get_critical_path(self) -> list[str]:
        """Return the longest dependency chain (critical path)."""
        if not self._nodes:
            return []

        # Find the node with the highest level
        end_node = max(self._nodes.values(), key=lambda n: n.level)

        # Trace back from end_node through its dependencies
        path: list[str] = [end_node.task_id]
        current = end_node
        while current.depends_on:
            # Pick the dependency with the highest level
            best: AoTNode | None = None
            for dep_id in current.depends_on:
                dep = self._nodes.get(dep_id)
                if dep and (best is None or dep.level > best.level):
                    best = dep
            if best is None:
                break
            path.append(best.task_id)
            current = best

        path.reverse()
        return path

    def get_node(self, task_id: str) -> AoTNode | None:
        return self._nodes.get(task_id)

    @property
    def nodes(self) -> dict[str, AoTNode]:
        return dict(self._nodes)

    def summary(self) -> dict[str, int]:
        """Return status counts."""
        counts: dict[str, int] = defaultdict(int)
        for node in self._nodes.values():
            counts[node.status] += 1
        return dict(counts)
