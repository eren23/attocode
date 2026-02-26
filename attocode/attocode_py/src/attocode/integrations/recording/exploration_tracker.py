"""Exploration tracker — directed graph of agent navigation through codebase.

Tracks which files each agent visits, what action was taken, and
builds a navigable DAG that can be exported as Mermaid or ASCII art.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ExplorationNode:
    """A single file visit in the exploration graph."""

    node_id: str
    file_path: str
    symbols: list[str] = field(default_factory=list)
    agent_id: str = ""
    action: str = "read"   # read | search | edit | define | reference | overview
    outcome: str = ""      # useful | dead_end | key_finding
    timestamp: float = 0.0
    iteration: int = 0
    tool_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExplorationEdge:
    """A directed edge between two exploration nodes."""

    source_id: str
    target_id: str
    agent_id: str = ""
    edge_kind: str = "sequential"  # sequential | import_follow | search_result | edit_chain
    timestamp: float = 0.0


@dataclass(slots=True)
class ExplorationSnapshot:
    """Point-in-time snapshot of the exploration graph for a given agent."""

    agent_id: str
    nodes: list[ExplorationNode]
    edges: list[ExplorationEdge]
    current_file: str = ""
    depth: int = 0
    dead_ends: int = 0
    key_findings: int = 0


# Tool name -> action mapping
_TOOL_ACTION_MAP: dict[str, str] = {
    "read_file": "read",
    "grep": "search",
    "glob": "search",
    "edit_file": "edit",
    "write_file": "edit",
    "get_repo_map": "overview",
    "get_tree_view": "overview",
    "bash": "search",  # often used for grep/find
}


class ExplorationGraph:
    """Directed graph tracking agent navigation through codebase.

    Each node represents a file visit (read, search, edit), edges
    connect sequential visits within the same agent.  Multi-agent
    graphs are overlaid — use ``get_agent_path()`` to isolate one.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, ExplorationNode] = {}
        self.edges: list[ExplorationEdge] = []
        # Per-agent ordered list of node IDs
        self.agent_paths: dict[str, list[str]] = {}
        self._node_counter: int = 0

    def add_visit(
        self,
        file_path: str,
        agent_id: str = "main",
        action: str = "read",
        tool_name: str = "",
        symbols: list[str] | None = None,
        iteration: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> ExplorationNode:
        """Record a file visit and link it to the previous visit.

        Returns the newly created node.
        """
        self._node_counter += 1
        node_id = f"exp-{self._node_counter:04d}"

        node = ExplorationNode(
            node_id=node_id,
            file_path=file_path,
            symbols=symbols or [],
            agent_id=agent_id,
            action=action,
            timestamp=time.time(),
            iteration=iteration,
            tool_name=tool_name,
            metadata=metadata or {},
        )
        self.nodes[node_id] = node

        # Link to previous node for this agent
        path = self.agent_paths.setdefault(agent_id, [])
        if path:
            prev_id = path[-1]
            edge = ExplorationEdge(
                source_id=prev_id,
                target_id=node_id,
                agent_id=agent_id,
                edge_kind="sequential",
                timestamp=node.timestamp,
            )
            self.edges.append(edge)
        path.append(node_id)

        return node

    def mark_outcome(self, node_id: str, outcome: str) -> None:
        """Mark a node as useful, dead_end, or key_finding."""
        if node_id in self.nodes:
            self.nodes[node_id].outcome = outcome

    def get_agent_path(self, agent_id: str) -> list[ExplorationNode]:
        """Get the ordered list of nodes visited by an agent."""
        ids = self.agent_paths.get(agent_id, [])
        return [self.nodes[nid] for nid in ids if nid in self.nodes]

    def get_snapshot(self, agent_id: str | None = None) -> ExplorationSnapshot:
        """Get a point-in-time snapshot of the exploration state.

        Args:
            agent_id: If set, scope to a single agent.  ``None`` includes all.
        """
        if agent_id:
            path = self.get_agent_path(agent_id)
            edges = [e for e in self.edges if e.agent_id == agent_id]
        else:
            path = list(self.nodes.values())
            edges = list(self.edges)

        dead_ends = sum(1 for n in path if n.outcome == "dead_end")
        key_findings = sum(1 for n in path if n.outcome == "key_finding")
        current_file = path[-1].file_path if path else ""

        return ExplorationSnapshot(
            agent_id=agent_id or "all",
            nodes=path,
            edges=edges,
            current_file=current_file,
            depth=len(path),
            dead_ends=dead_ends,
            key_findings=key_findings,
        )

    def to_mermaid(self, agent_id: str | None = None) -> str:
        """Export the graph as a Mermaid diagram.

        Args:
            agent_id: Scope to a single agent, or ``None`` for all.
        """
        lines = ["graph LR"]

        if agent_id:
            nodes = {n.node_id: n for n in self.get_agent_path(agent_id)}
            edges = [e for e in self.edges if e.agent_id == agent_id]
        else:
            nodes = self.nodes
            edges = self.edges

        # Define nodes
        for nid, node in nodes.items():
            label = node.file_path.replace("/", "/\\n") if "/" in node.file_path else node.file_path
            style = ""
            if node.outcome == "key_finding":
                style = ":::key"
            elif node.outcome == "dead_end":
                style = ":::dead"
            elif node.action == "edit":
                style = ":::edit"
            lines.append(f'    {nid}["{label}\\n({node.action})"]' + style)

        # Define edges
        for edge in edges:
            if edge.source_id in nodes and edge.target_id in nodes:
                label = edge.edge_kind if edge.edge_kind != "sequential" else ""
                if label:
                    lines.append(f"    {edge.source_id} -->|{label}| {edge.target_id}")
                else:
                    lines.append(f"    {edge.source_id} --> {edge.target_id}")

        # Style definitions
        lines.append("    classDef key fill:#2d6,stroke:#fff,color:#fff")
        lines.append("    classDef dead fill:#d44,stroke:#fff,color:#fff")
        lines.append("    classDef edit fill:#46d,stroke:#fff,color:#fff")

        return "\n".join(lines)

    def to_ascii_dag(self, agent_id: str | None = None) -> str:
        """Render a simple ASCII representation of the exploration path."""
        if agent_id:
            path = self.get_agent_path(agent_id)
        else:
            path = list(self.nodes.values())

        if not path:
            return "(no exploration recorded)"

        lines: list[str] = []
        for i, node in enumerate(path):
            prefix = "  " if i > 0 else ""
            arrow = "└─> " if i > 0 else "    "
            outcome_badge = ""
            if node.outcome == "key_finding":
                outcome_badge = " [KEY]"
            elif node.outcome == "dead_end":
                outcome_badge = " [DEAD END]"

            lines.append(f"{prefix}{arrow}{node.file_path} ({node.action}){outcome_badge}")
            if i < len(path) - 1:
                lines.append(f"    │")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full graph to a JSON-compatible dict."""
        return {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "file_path": n.file_path,
                    "symbols": n.symbols,
                    "agent_id": n.agent_id,
                    "action": n.action,
                    "outcome": n.outcome,
                    "timestamp": n.timestamp,
                    "iteration": n.iteration,
                    "tool_name": n.tool_name,
                }
                for n in self.nodes.values()
            ],
            "edges": [
                {
                    "source_id": e.source_id,
                    "target_id": e.target_id,
                    "agent_id": e.agent_id,
                    "edge_kind": e.edge_kind,
                    "timestamp": e.timestamp,
                }
                for e in self.edges
            ],
            "agent_paths": {
                aid: list(path) for aid, path in self.agent_paths.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExplorationGraph:
        """Deserialize a graph from a dict (e.g. loaded from JSON)."""
        graph = cls()
        for nd in data.get("nodes", []):
            node = ExplorationNode(
                node_id=nd["node_id"],
                file_path=nd["file_path"],
                symbols=nd.get("symbols", []),
                agent_id=nd.get("agent_id", ""),
                action=nd.get("action", "read"),
                outcome=nd.get("outcome", ""),
                timestamp=nd.get("timestamp", 0.0),
                iteration=nd.get("iteration", 0),
                tool_name=nd.get("tool_name", ""),
            )
            graph.nodes[node.node_id] = node
        for ed in data.get("edges", []):
            edge = ExplorationEdge(
                source_id=ed["source_id"],
                target_id=ed["target_id"],
                agent_id=ed.get("agent_id", ""),
                edge_kind=ed.get("edge_kind", "sequential"),
                timestamp=ed.get("timestamp", 0.0),
            )
            graph.edges.append(edge)
        graph.agent_paths = {
            k: list(v) for k, v in data.get("agent_paths", {}).items()
        }
        if graph.nodes:
            graph._node_counter = max(
                int(nid.split("-")[1]) for nid in graph.nodes
            )
        return graph


def tool_to_action(tool_name: str) -> str:
    """Map a tool name to an exploration action."""
    return _TOOL_ACTION_MAP.get(tool_name, "read")
