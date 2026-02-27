"""Unified node and edge types for the full session recording graph.

Extends beyond file exploration to capture the complete agent execution
lifecycle: messages, LLM calls, decisions, tool executions, subagent
spawns, swarm tasks, budget events, and compaction events.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class NodeKind(StrEnum):
    """Types of nodes in the session graph."""

    # Core execution
    MESSAGE = "message"             # User or assistant message
    LLM_CALL = "llm_call"          # LLM provider call
    TOOL_CALL = "tool_call"        # Tool execution
    DECISION = "decision"          # Agent decision point (plan, mode change)

    # File exploration (legacy compat with ExplorationNode)
    FILE_VISIT = "file_visit"

    # Multi-agent
    SUBAGENT_SPAWN = "subagent_spawn"
    SUBAGENT_COMPLETE = "subagent_complete"
    SWARM_TASK = "swarm_task"

    # System events
    BUDGET_EVENT = "budget_event"
    COMPACTION_EVENT = "compaction_event"
    ERROR = "error"
    CHECKPOINT = "checkpoint"


class EdgeKind(StrEnum):
    """Types of edges in the session graph."""

    # Sequential flow
    SEQUENTIAL = "sequential"       # Default temporal ordering
    CAUSES = "causes"               # A caused B (tool → file change)
    RESPONSE_TO = "response_to"     # LLM response to message

    # File exploration
    IMPORT_FOLLOW = "import_follow"
    SEARCH_RESULT = "search_result"
    EDIT_CHAIN = "edit_chain"

    # Multi-agent
    SPAWNS = "spawns"               # Agent spawns subagent
    DELEGATES = "delegates"         # Swarm delegation

    # Context
    COMPACTS = "compacts"           # Compaction removes/summarizes


@dataclass(slots=True)
class GraphNode:
    """A node in the unified session graph.

    Generalizes ExplorationNode to support all event types.
    """

    node_id: str
    kind: NodeKind
    timestamp: float = 0.0
    agent_id: str = "main"
    iteration: int = 0

    # Content varies by kind
    content: str = ""               # Message text, tool result, etc.
    tool_name: str = ""             # For TOOL_CALL nodes
    tool_args: dict[str, Any] = field(default_factory=dict)

    # File exploration fields (FILE_VISIT kind)
    file_path: str = ""
    symbols: list[str] = field(default_factory=list)
    action: str = ""                # read | search | edit | etc.
    outcome: str = ""               # useful | dead_end | key_finding

    # LLM call fields
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0

    # Budget event fields
    budget_usage: float = 0.0       # 0.0-1.0 fraction

    # Compaction fields
    tokens_saved: int = 0
    messages_removed: int = 0

    # Generic metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass(slots=True)
class GraphEdge:
    """A directed edge in the session graph."""

    source_id: str
    target_id: str
    kind: EdgeKind = EdgeKind.SEQUENTIAL
    agent_id: str = "main"
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class SessionGraph:
    """Full session recording graph with all event types.

    Extends ExplorationGraph to capture the entire agent execution
    lifecycle as a directed acyclic graph.
    """

    session_id: str = ""
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)
    agent_paths: dict[str, list[str]] = field(default_factory=dict)
    _node_counter: int = field(default=0, repr=False)

    def _next_id(self, prefix: str = "n") -> str:
        self._node_counter += 1
        return f"{prefix}-{self._node_counter}"

    def add_node(
        self,
        kind: NodeKind,
        *,
        agent_id: str = "main",
        iteration: int = 0,
        **kwargs: Any,
    ) -> GraphNode:
        """Add a node to the graph and return it."""
        node_id = self._next_id(kind.value[:3])
        node = GraphNode(
            node_id=node_id,
            kind=kind,
            agent_id=agent_id,
            iteration=iteration,
            **kwargs,
        )
        self.nodes[node_id] = node

        # Track agent path
        path = self.agent_paths.setdefault(agent_id, [])
        if path:
            # Auto-create sequential edge from last node
            last_id = path[-1]
            self.add_edge(last_id, node_id, EdgeKind.SEQUENTIAL, agent_id=agent_id)
        path.append(node_id)

        return node

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        kind: EdgeKind = EdgeKind.SEQUENTIAL,
        *,
        agent_id: str = "main",
        **kwargs: Any,
    ) -> GraphEdge:
        """Add a directed edge between two nodes."""
        edge = GraphEdge(
            source_id=source_id,
            target_id=target_id,
            kind=kind,
            agent_id=agent_id,
            **kwargs,
        )
        self.edges.append(edge)
        return edge

    def get_agent_path(self, agent_id: str = "main") -> list[GraphNode]:
        """Get ordered list of nodes visited by an agent."""
        node_ids = self.agent_paths.get(agent_id, [])
        return [self.nodes[nid] for nid in node_ids if nid in self.nodes]

    def get_nodes_by_kind(self, kind: NodeKind) -> list[GraphNode]:
        """Get all nodes of a specific kind."""
        return [n for n in self.nodes.values() if n.kind == kind]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "session_id": self.session_id,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "agent_ids": list(self.agent_paths.keys()),
            "nodes": {
                nid: {
                    "node_id": n.node_id,
                    "kind": n.kind.value,
                    "timestamp": n.timestamp,
                    "agent_id": n.agent_id,
                    "iteration": n.iteration,
                    "content": n.content[:200] if n.content else "",
                    "tool_name": n.tool_name,
                    "file_path": n.file_path,
                    "action": n.action,
                    "outcome": n.outcome,
                    "model": n.model,
                    "input_tokens": n.input_tokens,
                    "output_tokens": n.output_tokens,
                    "cost": n.cost,
                    "tokens_saved": n.tokens_saved,
                    "metadata": n.metadata,
                }
                for nid, n in self.nodes.items()
            },
            "edges": [
                {
                    "source_id": e.source_id,
                    "target_id": e.target_id,
                    "kind": e.kind.value,
                    "agent_id": e.agent_id,
                    "timestamp": e.timestamp,
                }
                for e in self.edges
            ],
            "agent_paths": self.agent_paths,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionGraph:
        """Deserialize from a dict."""
        graph = cls(session_id=data.get("session_id", ""))
        for nid, nd in data.get("nodes", {}).items():
            node = GraphNode(
                node_id=nid,
                kind=NodeKind(nd["kind"]),
                timestamp=nd.get("timestamp", 0.0),
                agent_id=nd.get("agent_id", "main"),
                iteration=nd.get("iteration", 0),
                content=nd.get("content", ""),
                tool_name=nd.get("tool_name", ""),
                file_path=nd.get("file_path", ""),
                action=nd.get("action", ""),
                outcome=nd.get("outcome", ""),
                model=nd.get("model", ""),
                input_tokens=nd.get("input_tokens", 0),
                output_tokens=nd.get("output_tokens", 0),
                cost=nd.get("cost", 0.0),
                tokens_saved=nd.get("tokens_saved", 0),
                metadata=nd.get("metadata", {}),
            )
            graph.nodes[nid] = node
        for ed in data.get("edges", []):
            edge = GraphEdge(
                source_id=ed["source_id"],
                target_id=ed["target_id"],
                kind=EdgeKind(ed["kind"]),
                agent_id=ed.get("agent_id", "main"),
                timestamp=ed.get("timestamp", 0.0),
            )
            graph.edges.append(edge)
        graph.agent_paths = data.get("agent_paths", {})
        return graph

    def to_mermaid(self, max_nodes: int = 50) -> str:
        """Export the graph as a Mermaid diagram."""
        lines = ["graph TD"]
        nodes = list(self.nodes.values())[:max_nodes]

        # Style definitions
        lines.append("    classDef msg fill:#4CAF50,color:#fff")
        lines.append("    classDef llm fill:#2196F3,color:#fff")
        lines.append("    classDef tool fill:#FF9800,color:#fff")
        lines.append("    classDef file fill:#9C27B0,color:#fff")
        lines.append("    classDef agent fill:#E91E63,color:#fff")
        lines.append("    classDef budget fill:#795548,color:#fff")
        lines.append("    classDef error fill:#F44336,color:#fff")

        kind_class = {
            NodeKind.MESSAGE: "msg",
            NodeKind.LLM_CALL: "llm",
            NodeKind.TOOL_CALL: "tool",
            NodeKind.FILE_VISIT: "file",
            NodeKind.SUBAGENT_SPAWN: "agent",
            NodeKind.SUBAGENT_COMPLETE: "agent",
            NodeKind.SWARM_TASK: "agent",
            NodeKind.BUDGET_EVENT: "budget",
            NodeKind.COMPACTION_EVENT: "budget",
            NodeKind.ERROR: "error",
        }

        for node in nodes:
            label = _node_label(node)
            safe_label = label.replace('"', "'")
            lines.append(f'    {node.node_id}["{safe_label}"]')
            cls = kind_class.get(node.kind, "")
            if cls:
                lines.append(f"    class {node.node_id} {cls}")

        node_ids = {n.node_id for n in nodes}
        for edge in self.edges:
            if edge.source_id in node_ids and edge.target_id in node_ids:
                label = edge.kind.value if edge.kind != EdgeKind.SEQUENTIAL else ""
                if label:
                    lines.append(f"    {edge.source_id} -->|{label}| {edge.target_id}")
                else:
                    lines.append(f"    {edge.source_id} --> {edge.target_id}")

        return "\n".join(lines)


def _node_label(node: GraphNode) -> str:
    """Create a short label for a graph node."""
    if node.kind == NodeKind.MESSAGE:
        preview = (node.content[:30] + "...") if len(node.content) > 30 else node.content
        return f"msg: {preview}"
    if node.kind == NodeKind.LLM_CALL:
        return f"llm: {node.model or '?'} ({node.output_tokens}t)"
    if node.kind == NodeKind.TOOL_CALL:
        return f"tool: {node.tool_name}"
    if node.kind == NodeKind.FILE_VISIT:
        fname = node.file_path.rsplit("/", 1)[-1] if "/" in node.file_path else node.file_path
        return f"file: {fname} [{node.action}]"
    if node.kind == NodeKind.SUBAGENT_SPAWN:
        return f"spawn: {node.agent_id}"
    if node.kind == NodeKind.SWARM_TASK:
        preview = (node.content[:25] + "...") if len(node.content) > 25 else node.content
        return f"swarm: {preview}"
    if node.kind == NodeKind.BUDGET_EVENT:
        return f"budget: {node.budget_usage:.0%}"
    if node.kind == NodeKind.COMPACTION_EVENT:
        return f"compact: -{node.tokens_saved}t"
    if node.kind == NodeKind.ERROR:
        preview = (node.content[:30] + "...") if len(node.content) > 30 else node.content
        return f"error: {preview}"
    return f"{node.kind.value}: {node.node_id}"
