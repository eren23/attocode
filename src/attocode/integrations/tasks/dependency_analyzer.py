"""Dependency analyzer: build and query a task dependency DAG.

Provides topological sorting into execution waves, cycle detection,
and critical-path analysis for a set of :class:`SubTask` objects.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from attocode.integrations.tasks.task_splitter import SubTask


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DependencyGraph:
    """Directed acyclic graph of subtask dependencies.

    *nodes* maps subtask IDs to subtask objects.
    *edges* is a list of ``(source_id, target_id)`` tuples where
    *source* must complete before *target* can start.
    """

    nodes: dict[str, SubTask] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DependencyAnalyzer
# ---------------------------------------------------------------------------


class DependencyAnalyzer:
    """Builds and queries a dependency graph over subtasks."""

    # -- Graph construction ------------------------------------------------

    @staticmethod
    def analyze(tasks: list[SubTask]) -> DependencyGraph:
        """Build a :class:`DependencyGraph` from a list of subtasks.

        Edges are derived from each subtask's ``dependencies`` field.
        """
        nodes: dict[str, SubTask] = {t.id: t for t in tasks}
        edges: list[tuple[str, str]] = []

        for task in tasks:
            for dep_id in task.dependencies:
                if dep_id in nodes:
                    edges.append((dep_id, task.id))

        return DependencyGraph(nodes=nodes, edges=edges)

    # -- Topological sort into waves (BFS / Kahn's algorithm) ---------------

    @staticmethod
    def get_execution_order(graph: DependencyGraph) -> list[list[SubTask]]:
        """Return subtasks grouped into execution waves.

        Each wave contains subtasks whose dependencies are all satisfied
        by previous waves.  Tasks within a wave can run in parallel.
        """
        if not graph.nodes:
            return []

        # Build adjacency + in-degree
        in_degree: dict[str, int] = {nid: 0 for nid in graph.nodes}
        children: dict[str, list[str]] = defaultdict(list)

        for src, tgt in graph.edges:
            in_degree[tgt] = in_degree.get(tgt, 0) + 1
            children[src].append(tgt)

        # Seed with zero-degree nodes
        queue: deque[str] = deque(
            nid for nid, deg in in_degree.items() if deg == 0
        )

        waves: list[list[SubTask]] = []
        visited = 0

        while queue:
            wave_ids: list[str] = list(queue)
            queue.clear()

            wave: list[SubTask] = []
            for nid in wave_ids:
                node = graph.nodes.get(nid)
                if node is not None:
                    wave.append(node)
                visited += 1

                for child in children.get(nid, []):
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        queue.append(child)

            if wave:
                waves.append(wave)

        # If we didn't visit all nodes, there are cycles
        if visited < len(graph.nodes):
            # Include remaining nodes in a final wave so nothing is lost
            visited_ids = {
                t.id for wave in waves for t in wave
            }
            remaining = [
                graph.nodes[nid]
                for nid in graph.nodes
                if nid not in visited_ids
            ]
            if remaining:
                waves.append(remaining)

        return waves

    # -- Cycle detection (DFS) ---------------------------------------------

    @staticmethod
    def detect_cycles(graph: DependencyGraph) -> list[list[str]]:
        """Return all elementary cycles in the dependency graph.

        Uses iterative DFS with colouring:
          - WHITE (0): unvisited
          - GREY  (1): on current path
          - BLACK (2): fully explored
        """
        WHITE, GREY, BLACK = 0, 1, 2

        children: dict[str, list[str]] = defaultdict(list)
        for src, tgt in graph.edges:
            children[src].append(tgt)

        colour: dict[str, int] = {nid: WHITE for nid in graph.nodes}
        parent: dict[str, str | None] = {nid: None for nid in graph.nodes}
        cycles: list[list[str]] = []

        for start in graph.nodes:
            if colour[start] != WHITE:
                continue
            stack: list[str] = [start]
            while stack:
                node = stack[-1]
                if colour[node] == WHITE:
                    colour[node] = GREY
                    for child in children.get(node, []):
                        if colour[child] == WHITE:
                            parent[child] = node
                            stack.append(child)
                        elif colour[child] == GREY:
                            # Back edge -> cycle found
                            cycle: list[str] = [child]
                            cur = node
                            while cur != child:
                                cycle.append(cur)
                                cur = parent.get(cur, child)  # type: ignore[assignment]
                            cycle.append(child)
                            cycle.reverse()
                            cycles.append(cycle)
                else:
                    colour[node] = BLACK
                    stack.pop()

        return cycles

    # -- Critical path (longest path through DAG) --------------------------

    @staticmethod
    def get_critical_path(graph: DependencyGraph) -> list[SubTask]:
        """Compute the critical path (longest chain) through the DAG.

        Uses dynamic programming on a topological ordering.
        Complexity weights: simple=1, medium=2, complex=3.
        """
        if not graph.nodes:
            return []

        # Complexity weights
        _WEIGHT = {"simple": 1, "medium": 2, "complex": 3}

        children: dict[str, list[str]] = defaultdict(list)
        for src, tgt in graph.edges:
            children[src].append(tgt)

        # Get topological order via Kahn's algorithm
        in_degree: dict[str, int] = {nid: 0 for nid in graph.nodes}
        for _, tgt in graph.edges:
            in_degree[tgt] = in_degree.get(tgt, 0) + 1

        queue: deque[str] = deque(
            nid for nid, deg in in_degree.items() if deg == 0
        )
        topo_order: list[str] = []
        while queue:
            nid = queue.popleft()
            topo_order.append(nid)
            for child in children.get(nid, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        # DP: longest path to each node
        dist: dict[str, int] = {nid: 0 for nid in graph.nodes}
        predecessor: dict[str, str | None] = {nid: None for nid in graph.nodes}

        for nid in topo_order:
            node = graph.nodes[nid]
            weight = _WEIGHT.get(node.estimated_complexity.value, 1)
            for child in children.get(nid, []):
                new_dist = dist[nid] + weight
                if new_dist > dist[child]:
                    dist[child] = new_dist
                    predecessor[child] = nid

        # Find the endpoint with the longest distance
        if not dist:
            return []

        end_id = max(dist, key=lambda k: dist[k])

        # Trace back
        path_ids: list[str] = []
        cur: str | None = end_id
        while cur is not None:
            path_ids.append(cur)
            cur = predecessor.get(cur)
        path_ids.reverse()

        return [graph.nodes[nid] for nid in path_ids if nid in graph.nodes]
