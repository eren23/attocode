"""Shared community detection helpers.

Used by both the MCP tool (analysis_tools.py) and the HTTP service (service.py).
"""

from __future__ import annotations

from collections import deque


def louvain_communities(
    all_files: set[str],
    adj: dict[str, set[str]],
    weights: dict[tuple[str, str], float],
) -> tuple[list[set[str]], float]:
    """Run Louvain community detection using networkx.

    Returns ``([], 0.0)`` for an empty graph (no edges).
    Raises ``ImportError`` if networkx is not installed.
    """
    import networkx as nx
    from networkx.algorithms.community import louvain_communities as _louvain
    from networkx.algorithms.community import modularity

    G = nx.Graph()  # noqa: N806
    G.add_nodes_from(all_files)
    for src, neighbors in adj.items():
        for tgt in neighbors:
            if src < tgt:  # avoid duplicate edges
                w = weights.get((src, tgt), weights.get((tgt, src), 1.0))
                G.add_edge(src, tgt, weight=w)

    if G.number_of_edges() == 0:
        return [{f} for f in all_files], 0.0

    communities = [set(c) for c in _louvain(G, weight="weight", seed=42)]
    mod = modularity(G, communities, weight="weight")
    return communities, mod


def bfs_connected_components(
    all_files: set[str],
    adj: dict[str, set[str]],
) -> tuple[list[set[str]], float]:
    """Fallback: connected components via BFS. Modularity = 0."""
    visited: set[str] = set()
    communities: list[set[str]] = []
    for start in all_files:
        if start in visited:
            continue
        component: set[str] = set()
        bfs_queue: deque[str] = deque([start])
        while bfs_queue:
            node = bfs_queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            for neighbor in adj.get(node, set()):
                if neighbor not in visited:
                    bfs_queue.append(neighbor)
        communities.append(component)
    return communities, 0.0
