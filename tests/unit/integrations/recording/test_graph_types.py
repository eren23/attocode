"""Tests for the unified session graph types.

Covers:
- NodeKind and EdgeKind enum values
- GraphNode creation with various kinds
- GraphEdge creation and defaults
- SessionGraph add_node, add_edge
- get_agent_path returns nodes in order
- get_nodes_by_kind filtering
- to_dict / from_dict round-trip serialization
- to_mermaid output format
- Multiple agents with separate paths
- _node_label helper for all node kinds
- Edge cases: empty graph, content truncation in to_dict
"""

from __future__ import annotations

import time

import pytest

from attocode.integrations.recording.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
    SessionGraph,
    _node_label,
)


# ---------------------------------------------------------------------------
# NodeKind enum
# ---------------------------------------------------------------------------


class TestNodeKind:
    def test_core_execution_kinds(self) -> None:
        assert NodeKind.MESSAGE == "message"
        assert NodeKind.LLM_CALL == "llm_call"
        assert NodeKind.TOOL_CALL == "tool_call"
        assert NodeKind.DECISION == "decision"

    def test_file_exploration_kind(self) -> None:
        assert NodeKind.FILE_VISIT == "file_visit"

    def test_multi_agent_kinds(self) -> None:
        assert NodeKind.SUBAGENT_SPAWN == "subagent_spawn"
        assert NodeKind.SUBAGENT_COMPLETE == "subagent_complete"
        assert NodeKind.SWARM_TASK == "swarm_task"

    def test_system_event_kinds(self) -> None:
        assert NodeKind.BUDGET_EVENT == "budget_event"
        assert NodeKind.COMPACTION_EVENT == "compaction_event"
        assert NodeKind.ERROR == "error"
        assert NodeKind.CHECKPOINT == "checkpoint"

    def test_all_kinds_are_str(self) -> None:
        """StrEnum members should be usable as plain strings."""
        for kind in NodeKind:
            assert isinstance(kind, str)
            assert kind == kind.value


# ---------------------------------------------------------------------------
# EdgeKind enum
# ---------------------------------------------------------------------------


class TestEdgeKind:
    def test_sequential_flow_kinds(self) -> None:
        assert EdgeKind.SEQUENTIAL == "sequential"
        assert EdgeKind.CAUSES == "causes"
        assert EdgeKind.RESPONSE_TO == "response_to"

    def test_file_exploration_kinds(self) -> None:
        assert EdgeKind.IMPORT_FOLLOW == "import_follow"
        assert EdgeKind.SEARCH_RESULT == "search_result"
        assert EdgeKind.EDIT_CHAIN == "edit_chain"

    def test_multi_agent_kinds(self) -> None:
        assert EdgeKind.SPAWNS == "spawns"
        assert EdgeKind.DELEGATES == "delegates"

    def test_context_kind(self) -> None:
        assert EdgeKind.COMPACTS == "compacts"

    def test_all_kinds_are_str(self) -> None:
        for kind in EdgeKind:
            assert isinstance(kind, str)


# ---------------------------------------------------------------------------
# GraphNode creation
# ---------------------------------------------------------------------------


class TestGraphNode:
    def test_basic_creation(self) -> None:
        node = GraphNode(node_id="n-1", kind=NodeKind.MESSAGE, content="Hello")
        assert node.node_id == "n-1"
        assert node.kind == NodeKind.MESSAGE
        assert node.content == "Hello"
        assert node.agent_id == "main"
        assert node.iteration == 0

    def test_timestamp_auto_assigned(self) -> None:
        before = time.time()
        node = GraphNode(node_id="n-2", kind=NodeKind.TOOL_CALL)
        after = time.time()
        assert before <= node.timestamp <= after

    def test_explicit_timestamp_preserved(self) -> None:
        node = GraphNode(node_id="n-3", kind=NodeKind.LLM_CALL, timestamp=123.456)
        assert node.timestamp == 123.456

    def test_tool_call_fields(self) -> None:
        node = GraphNode(
            node_id="t-1",
            kind=NodeKind.TOOL_CALL,
            tool_name="read_file",
            tool_args={"file_path": "main.py"},
        )
        assert node.tool_name == "read_file"
        assert node.tool_args == {"file_path": "main.py"}

    def test_file_visit_fields(self) -> None:
        node = GraphNode(
            node_id="f-1",
            kind=NodeKind.FILE_VISIT,
            file_path="src/main.py",
            action="read",
            outcome="useful",
            symbols=["main", "parse_args"],
        )
        assert node.file_path == "src/main.py"
        assert node.action == "read"
        assert node.outcome == "useful"
        assert node.symbols == ["main", "parse_args"]

    def test_llm_call_fields(self) -> None:
        node = GraphNode(
            node_id="l-1",
            kind=NodeKind.LLM_CALL,
            model="claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=500,
            cost=0.015,
        )
        assert node.model == "claude-sonnet-4-20250514"
        assert node.input_tokens == 1000
        assert node.output_tokens == 500
        assert node.cost == 0.015

    def test_budget_event_fields(self) -> None:
        node = GraphNode(
            node_id="b-1",
            kind=NodeKind.BUDGET_EVENT,
            budget_usage=0.75,
        )
        assert node.budget_usage == 0.75

    def test_compaction_event_fields(self) -> None:
        node = GraphNode(
            node_id="c-1",
            kind=NodeKind.COMPACTION_EVENT,
            tokens_saved=5000,
            messages_removed=12,
        )
        assert node.tokens_saved == 5000
        assert node.messages_removed == 12

    def test_metadata_defaults_to_empty_dict(self) -> None:
        node = GraphNode(node_id="n-x", kind=NodeKind.ERROR)
        assert node.metadata == {}

    def test_metadata_not_shared_between_instances(self) -> None:
        a = GraphNode(node_id="a", kind=NodeKind.MESSAGE)
        b = GraphNode(node_id="b", kind=NodeKind.MESSAGE)
        a.metadata["key"] = "val"
        assert "key" not in b.metadata


# ---------------------------------------------------------------------------
# GraphEdge creation
# ---------------------------------------------------------------------------


class TestGraphEdge:
    def test_basic_creation(self) -> None:
        edge = GraphEdge(source_id="n-1", target_id="n-2")
        assert edge.source_id == "n-1"
        assert edge.target_id == "n-2"
        assert edge.kind == EdgeKind.SEQUENTIAL
        assert edge.agent_id == "main"

    def test_custom_kind(self) -> None:
        edge = GraphEdge(
            source_id="n-1",
            target_id="n-2",
            kind=EdgeKind.CAUSES,
            agent_id="sub-1",
        )
        assert edge.kind == EdgeKind.CAUSES
        assert edge.agent_id == "sub-1"

    def test_timestamp_auto_assigned(self) -> None:
        before = time.time()
        edge = GraphEdge(source_id="a", target_id="b")
        after = time.time()
        assert before <= edge.timestamp <= after

    def test_explicit_timestamp_preserved(self) -> None:
        edge = GraphEdge(source_id="a", target_id="b", timestamp=999.0)
        assert edge.timestamp == 999.0

    def test_metadata_defaults_empty(self) -> None:
        edge = GraphEdge(source_id="a", target_id="b")
        assert edge.metadata == {}


# ---------------------------------------------------------------------------
# SessionGraph: add_node
# ---------------------------------------------------------------------------


class TestSessionGraphAddNode:
    def test_add_single_node(self) -> None:
        graph = SessionGraph(session_id="s1")
        node = graph.add_node(NodeKind.MESSAGE, content="Hello")
        assert node.node_id in graph.nodes
        assert node.kind == NodeKind.MESSAGE
        assert node.content == "Hello"
        assert node.agent_id == "main"

    def test_node_id_auto_generated(self) -> None:
        graph = SessionGraph()
        n1 = graph.add_node(NodeKind.MESSAGE)
        n2 = graph.add_node(NodeKind.LLM_CALL)
        assert n1.node_id != n2.node_id
        # ID prefix is derived from kind value[:3]
        assert n1.node_id.startswith("mes-")
        assert n2.node_id.startswith("llm-")

    def test_add_node_with_agent_id(self) -> None:
        graph = SessionGraph()
        node = graph.add_node(NodeKind.TOOL_CALL, agent_id="worker-1")
        assert node.agent_id == "worker-1"

    def test_add_node_tracks_agent_path(self) -> None:
        graph = SessionGraph()
        n1 = graph.add_node(NodeKind.MESSAGE, agent_id="main")
        n2 = graph.add_node(NodeKind.TOOL_CALL, agent_id="main")

        assert graph.agent_paths["main"] == [n1.node_id, n2.node_id]

    def test_sequential_edge_auto_created(self) -> None:
        graph = SessionGraph()
        n1 = graph.add_node(NodeKind.MESSAGE)
        n2 = graph.add_node(NodeKind.LLM_CALL)

        assert len(graph.edges) == 1
        edge = graph.edges[0]
        assert edge.source_id == n1.node_id
        assert edge.target_id == n2.node_id
        assert edge.kind == EdgeKind.SEQUENTIAL

    def test_first_node_no_auto_edge(self) -> None:
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE)
        assert len(graph.edges) == 0

    def test_counter_increments(self) -> None:
        graph = SessionGraph()
        n1 = graph.add_node(NodeKind.MESSAGE)
        n2 = graph.add_node(NodeKind.MESSAGE)
        n3 = graph.add_node(NodeKind.MESSAGE)
        assert n1.node_id == "mes-1"
        assert n2.node_id == "mes-2"
        assert n3.node_id == "mes-3"

    def test_node_kwargs_passed_through(self) -> None:
        graph = SessionGraph()
        node = graph.add_node(
            NodeKind.LLM_CALL,
            model="gpt-4o",
            input_tokens=500,
            output_tokens=200,
            cost=0.01,
            iteration=3,
        )
        assert node.model == "gpt-4o"
        assert node.input_tokens == 500
        assert node.output_tokens == 200
        assert node.cost == 0.01
        assert node.iteration == 3


# ---------------------------------------------------------------------------
# SessionGraph: add_edge
# ---------------------------------------------------------------------------


class TestSessionGraphAddEdge:
    def test_add_edge(self) -> None:
        graph = SessionGraph()
        n1 = graph.add_node(NodeKind.MESSAGE)
        n2 = graph.add_node(NodeKind.TOOL_CALL)

        edge = graph.add_edge(n1.node_id, n2.node_id, EdgeKind.CAUSES)
        assert edge.source_id == n1.node_id
        assert edge.target_id == n2.node_id
        assert edge.kind == EdgeKind.CAUSES
        # 1 auto edge + 1 manual edge
        assert len(graph.edges) == 2

    def test_add_edge_default_kind(self) -> None:
        graph = SessionGraph()
        edge = graph.add_edge("a", "b")
        assert edge.kind == EdgeKind.SEQUENTIAL

    def test_add_edge_with_agent_id(self) -> None:
        graph = SessionGraph()
        edge = graph.add_edge("a", "b", EdgeKind.SPAWNS, agent_id="orchestrator")
        assert edge.agent_id == "orchestrator"


# ---------------------------------------------------------------------------
# SessionGraph: get_agent_path
# ---------------------------------------------------------------------------


class TestGetAgentPath:
    def test_returns_nodes_in_order(self) -> None:
        graph = SessionGraph()
        n1 = graph.add_node(NodeKind.MESSAGE, content="first")
        n2 = graph.add_node(NodeKind.TOOL_CALL, tool_name="read_file")
        n3 = graph.add_node(NodeKind.LLM_CALL, model="claude")

        path = graph.get_agent_path("main")
        assert len(path) == 3
        assert path[0].node_id == n1.node_id
        assert path[1].node_id == n2.node_id
        assert path[2].node_id == n3.node_id

    def test_returns_empty_for_unknown_agent(self) -> None:
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE)
        assert graph.get_agent_path("nonexistent") == []

    def test_filters_by_agent(self) -> None:
        graph = SessionGraph()
        n1 = graph.add_node(NodeKind.MESSAGE, agent_id="a1", content="from a1")
        graph.add_node(NodeKind.MESSAGE, agent_id="a2", content="from a2")
        n3 = graph.add_node(NodeKind.MESSAGE, agent_id="a1", content="from a1 again")

        path = graph.get_agent_path("a1")
        assert len(path) == 2
        assert path[0].node_id == n1.node_id
        assert path[1].node_id == n3.node_id

    def test_handles_deleted_node_gracefully(self) -> None:
        """If a node_id in agent_paths is missing from nodes dict, skip it."""
        graph = SessionGraph()
        n1 = graph.add_node(NodeKind.MESSAGE)
        n2 = graph.add_node(NodeKind.TOOL_CALL)

        # Manually remove a node (simulating corruption / cleanup)
        del graph.nodes[n1.node_id]

        path = graph.get_agent_path("main")
        assert len(path) == 1
        assert path[0].node_id == n2.node_id


# ---------------------------------------------------------------------------
# SessionGraph: get_nodes_by_kind
# ---------------------------------------------------------------------------


class TestGetNodesByKind:
    def test_filters_correct_kind(self) -> None:
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE, content="msg1")
        graph.add_node(NodeKind.TOOL_CALL, tool_name="read_file")
        graph.add_node(NodeKind.MESSAGE, content="msg2")
        graph.add_node(NodeKind.LLM_CALL, model="gpt-4o")

        messages = graph.get_nodes_by_kind(NodeKind.MESSAGE)
        assert len(messages) == 2
        assert all(n.kind == NodeKind.MESSAGE for n in messages)

    def test_returns_empty_for_unused_kind(self) -> None:
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE)
        assert graph.get_nodes_by_kind(NodeKind.ERROR) == []

    def test_returns_empty_for_empty_graph(self) -> None:
        graph = SessionGraph()
        assert graph.get_nodes_by_kind(NodeKind.MESSAGE) == []


# ---------------------------------------------------------------------------
# SessionGraph: to_dict / from_dict round-trip
# ---------------------------------------------------------------------------


class TestSessionGraphSerialization:
    def test_to_dict_structure(self) -> None:
        graph = SessionGraph(session_id="test-session")
        graph.add_node(NodeKind.MESSAGE, content="Hello")
        graph.add_node(NodeKind.LLM_CALL, model="claude", input_tokens=100, output_tokens=50, cost=0.005)

        d = graph.to_dict()
        assert d["session_id"] == "test-session"
        assert d["node_count"] == 2
        assert d["edge_count"] == 1  # auto sequential edge
        assert "main" in d["agent_ids"]
        assert len(d["nodes"]) == 2
        assert len(d["edges"]) == 1

    def test_content_truncated_in_to_dict(self) -> None:
        graph = SessionGraph()
        long_content = "x" * 500
        graph.add_node(NodeKind.MESSAGE, content=long_content)

        d = graph.to_dict()
        node_data = list(d["nodes"].values())[0]
        assert len(node_data["content"]) == 200

    def test_empty_content_in_to_dict(self) -> None:
        graph = SessionGraph()
        graph.add_node(NodeKind.TOOL_CALL)
        d = graph.to_dict()
        node_data = list(d["nodes"].values())[0]
        assert node_data["content"] == ""

    def test_round_trip(self) -> None:
        graph = SessionGraph(session_id="roundtrip")
        graph.add_node(
            NodeKind.MESSAGE,
            content="Hello world",
            agent_id="main",
            iteration=1,
            timestamp=1000.0,
        )
        graph.add_node(
            NodeKind.LLM_CALL,
            model="claude",
            input_tokens=100,
            output_tokens=50,
            cost=0.005,
            agent_id="main",
            iteration=2,
            timestamp=1001.0,
        )
        graph.add_node(
            NodeKind.TOOL_CALL,
            tool_name="read_file",
            agent_id="main",
            iteration=3,
            timestamp=1002.0,
        )

        d = graph.to_dict()
        restored = SessionGraph.from_dict(d)

        assert restored.session_id == "roundtrip"
        assert len(restored.nodes) == 3
        assert len(restored.edges) == 2
        assert restored.agent_paths == graph.agent_paths

        # Check node contents survived
        for nid, node in graph.nodes.items():
            rnode = restored.nodes[nid]
            assert rnode.kind == node.kind
            assert rnode.agent_id == node.agent_id
            assert rnode.iteration == node.iteration
            assert rnode.model == node.model
            assert rnode.input_tokens == node.input_tokens

    def test_round_trip_preserves_edge_kinds(self) -> None:
        graph = SessionGraph()
        n1 = graph.add_node(NodeKind.MESSAGE)
        n2 = graph.add_node(NodeKind.TOOL_CALL)
        graph.add_edge(n1.node_id, n2.node_id, EdgeKind.CAUSES)

        d = graph.to_dict()
        restored = SessionGraph.from_dict(d)

        edge_kinds = [e.kind for e in restored.edges]
        assert EdgeKind.SEQUENTIAL in edge_kinds
        assert EdgeKind.CAUSES in edge_kinds

    def test_from_dict_with_missing_fields(self) -> None:
        """from_dict should handle missing optional fields gracefully."""
        data = {
            "session_id": "minimal",
            "nodes": {
                "n-1": {
                    "kind": "message",
                },
            },
            "edges": [],
            "agent_paths": {},
        }
        graph = SessionGraph.from_dict(data)
        assert len(graph.nodes) == 1
        node = graph.nodes["n-1"]
        assert node.kind == NodeKind.MESSAGE
        assert node.agent_id == "main"
        assert node.content == ""
        assert node.iteration == 0

    def test_from_dict_empty(self) -> None:
        data: dict = {"session_id": "", "nodes": {}, "edges": [], "agent_paths": {}}
        graph = SessionGraph.from_dict(data)
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_round_trip_file_visit(self) -> None:
        graph = SessionGraph()
        graph.add_node(
            NodeKind.FILE_VISIT,
            file_path="src/main.py",
            action="read",
            outcome="useful",
            timestamp=500.0,
        )

        d = graph.to_dict()
        restored = SessionGraph.from_dict(d)
        rnode = list(restored.nodes.values())[0]
        assert rnode.kind == NodeKind.FILE_VISIT
        assert rnode.file_path == "src/main.py"
        assert rnode.action == "read"
        assert rnode.outcome == "useful"

    def test_round_trip_compaction_event(self) -> None:
        graph = SessionGraph()
        graph.add_node(
            NodeKind.COMPACTION_EVENT,
            tokens_saved=8000,
            timestamp=999.0,
        )

        d = graph.to_dict()
        restored = SessionGraph.from_dict(d)
        rnode = list(restored.nodes.values())[0]
        assert rnode.tokens_saved == 8000


# ---------------------------------------------------------------------------
# SessionGraph: to_mermaid
# ---------------------------------------------------------------------------


class TestToMermaid:
    def test_basic_mermaid_output(self) -> None:
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE, content="Hello", timestamp=1.0)
        graph.add_node(NodeKind.LLM_CALL, model="claude", output_tokens=100, timestamp=2.0)

        mermaid = graph.to_mermaid()
        assert mermaid.startswith("graph TD")
        # Style definitions
        assert "classDef msg" in mermaid
        assert "classDef llm" in mermaid
        # Node labels
        assert "msg: Hello" in mermaid
        assert "llm: claude (100t)" in mermaid
        # Sequential edge (no label)
        assert " --> " in mermaid

    def test_mermaid_non_sequential_edge_has_label(self) -> None:
        graph = SessionGraph()
        n1 = graph.add_node(NodeKind.MESSAGE, timestamp=1.0)
        n2 = graph.add_node(NodeKind.TOOL_CALL, tool_name="edit_file", timestamp=2.0)
        graph.add_edge(n1.node_id, n2.node_id, EdgeKind.CAUSES)

        mermaid = graph.to_mermaid()
        assert "-->|causes|" in mermaid

    def test_mermaid_max_nodes_limit(self) -> None:
        graph = SessionGraph()
        for i in range(100):
            graph.add_node(NodeKind.MESSAGE, content=f"msg{i}", timestamp=float(i))

        mermaid = graph.to_mermaid(max_nodes=5)
        # Only first 5 nodes should appear
        assert "msg0" in mermaid
        assert "msg4" in mermaid
        # Nodes beyond limit should not appear
        assert "msg50" not in mermaid

    def test_mermaid_empty_graph(self) -> None:
        graph = SessionGraph()
        mermaid = graph.to_mermaid()
        assert mermaid.startswith("graph TD")
        # Only style definitions, no node or edge lines (besides classDef)
        lines = mermaid.strip().split("\n")
        non_style_lines = [l for l in lines[1:] if "classDef" not in l]
        assert len(non_style_lines) == 0

    def test_mermaid_edges_filtered_to_visible_nodes(self) -> None:
        """Edges referencing nodes outside the max_nodes window are omitted."""
        graph = SessionGraph()
        for i in range(10):
            graph.add_node(NodeKind.MESSAGE, content=f"msg{i}", timestamp=float(i))

        mermaid = graph.to_mermaid(max_nodes=3)
        # The auto-generated sequential edges for nodes 4..9 should not appear
        assert "mes-4" not in mermaid
        assert "mes-10" not in mermaid

    def test_mermaid_quotes_escaped(self) -> None:
        """Double quotes in content should be replaced with single quotes."""
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE, content='He said "hello"', timestamp=1.0)

        mermaid = graph.to_mermaid()
        assert '"hello"' not in mermaid.split("\n", 1)[1]  # skip "graph TD"
        assert "'hello'" in mermaid


# ---------------------------------------------------------------------------
# Multiple agents with separate paths
# ---------------------------------------------------------------------------


class TestMultipleAgents:
    def test_separate_agent_paths(self) -> None:
        graph = SessionGraph()
        a1 = graph.add_node(NodeKind.MESSAGE, agent_id="agent-1", content="a1 msg", timestamp=1.0)
        b1 = graph.add_node(NodeKind.MESSAGE, agent_id="agent-2", content="a2 msg", timestamp=2.0)
        a2 = graph.add_node(NodeKind.TOOL_CALL, agent_id="agent-1", tool_name="read", timestamp=3.0)

        assert len(graph.agent_paths) == 2
        assert graph.agent_paths["agent-1"] == [a1.node_id, a2.node_id]
        assert graph.agent_paths["agent-2"] == [b1.node_id]

    def test_separate_agent_paths_get_agent_path(self) -> None:
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE, agent_id="a1", content="first", timestamp=1.0)
        graph.add_node(NodeKind.MESSAGE, agent_id="a2", content="second", timestamp=2.0)
        graph.add_node(NodeKind.LLM_CALL, agent_id="a1", model="claude", timestamp=3.0)

        a1_path = graph.get_agent_path("a1")
        a2_path = graph.get_agent_path("a2")

        assert len(a1_path) == 2
        assert len(a2_path) == 1
        assert a1_path[0].content == "first"
        assert a1_path[1].model == "claude"
        assert a2_path[0].content == "second"

    def test_auto_edges_within_same_agent_only(self) -> None:
        """Sequential edges should only connect nodes of the same agent."""
        graph = SessionGraph()
        a1 = graph.add_node(NodeKind.MESSAGE, agent_id="a1", timestamp=1.0)
        b1 = graph.add_node(NodeKind.MESSAGE, agent_id="a2", timestamp=2.0)
        a2 = graph.add_node(NodeKind.MESSAGE, agent_id="a1", timestamp=3.0)
        b2 = graph.add_node(NodeKind.MESSAGE, agent_id="a2", timestamp=4.0)

        # Should have 2 auto-sequential edges:
        # a1 first -> a1 second (within agent a1)
        # a2 first -> a2 second (within agent a2)
        assert len(graph.edges) == 2
        for edge in graph.edges:
            # Each edge should connect nodes of the same agent
            source_node = graph.nodes[edge.source_id]
            target_node = graph.nodes[edge.target_id]
            assert source_node.agent_id == target_node.agent_id

    def test_many_agents(self) -> None:
        graph = SessionGraph()
        for i in range(10):
            graph.add_node(NodeKind.MESSAGE, agent_id=f"agent-{i}")

        assert len(graph.agent_paths) == 10
        for i in range(10):
            assert len(graph.get_agent_path(f"agent-{i}")) == 1


# ---------------------------------------------------------------------------
# _node_label helper
# ---------------------------------------------------------------------------


class TestNodeLabel:
    def test_message_short(self) -> None:
        node = GraphNode(node_id="n", kind=NodeKind.MESSAGE, content="Short msg")
        assert _node_label(node) == "msg: Short msg"

    def test_message_long_truncated(self) -> None:
        node = GraphNode(node_id="n", kind=NodeKind.MESSAGE, content="A" * 50)
        label = _node_label(node)
        assert label.startswith("msg: ")
        assert label.endswith("...")
        assert len(label) <= len("msg: ") + 33  # 30 chars + "..."

    def test_llm_call(self) -> None:
        node = GraphNode(node_id="n", kind=NodeKind.LLM_CALL, model="gpt-4o", output_tokens=200)
        assert _node_label(node) == "llm: gpt-4o (200t)"

    def test_llm_call_no_model(self) -> None:
        node = GraphNode(node_id="n", kind=NodeKind.LLM_CALL, output_tokens=50)
        assert _node_label(node) == "llm: ? (50t)"

    def test_tool_call(self) -> None:
        node = GraphNode(node_id="n", kind=NodeKind.TOOL_CALL, tool_name="bash")
        assert _node_label(node) == "tool: bash"

    def test_file_visit_with_path(self) -> None:
        node = GraphNode(
            node_id="n",
            kind=NodeKind.FILE_VISIT,
            file_path="src/utils/helpers.py",
            action="read",
        )
        assert _node_label(node) == "file: helpers.py [read]"

    def test_file_visit_no_slash(self) -> None:
        node = GraphNode(
            node_id="n",
            kind=NodeKind.FILE_VISIT,
            file_path="main.py",
            action="edit",
        )
        assert _node_label(node) == "file: main.py [edit]"

    def test_subagent_spawn(self) -> None:
        node = GraphNode(node_id="n", kind=NodeKind.SUBAGENT_SPAWN, agent_id="worker-1")
        assert _node_label(node) == "spawn: worker-1"

    def test_swarm_task_short(self) -> None:
        node = GraphNode(node_id="n", kind=NodeKind.SWARM_TASK, content="Refactor auth")
        assert _node_label(node) == "swarm: Refactor auth"

    def test_swarm_task_long_truncated(self) -> None:
        node = GraphNode(node_id="n", kind=NodeKind.SWARM_TASK, content="A" * 50)
        label = _node_label(node)
        assert label.endswith("...")

    def test_budget_event(self) -> None:
        node = GraphNode(node_id="n", kind=NodeKind.BUDGET_EVENT, budget_usage=0.75)
        assert _node_label(node) == "budget: 75%"

    def test_compaction_event(self) -> None:
        node = GraphNode(node_id="n", kind=NodeKind.COMPACTION_EVENT, tokens_saved=3000)
        assert _node_label(node) == "compact: -3000t"

    def test_error_short(self) -> None:
        node = GraphNode(node_id="n", kind=NodeKind.ERROR, content="Something failed")
        assert _node_label(node) == "error: Something failed"

    def test_error_long_truncated(self) -> None:
        node = GraphNode(node_id="n", kind=NodeKind.ERROR, content="E" * 50)
        label = _node_label(node)
        assert label.endswith("...")

    def test_fallback_for_decision(self) -> None:
        node = GraphNode(node_id="dec-1", kind=NodeKind.DECISION)
        assert _node_label(node) == "decision: dec-1"

    def test_fallback_for_checkpoint(self) -> None:
        node = GraphNode(node_id="chk-1", kind=NodeKind.CHECKPOINT)
        assert _node_label(node) == "checkpoint: chk-1"

    def test_fallback_for_subagent_complete(self) -> None:
        node = GraphNode(node_id="sc-1", kind=NodeKind.SUBAGENT_COMPLETE)
        assert _node_label(node) == "subagent_complete: sc-1"


# ---------------------------------------------------------------------------
# Empty graph edge cases
# ---------------------------------------------------------------------------


class TestEmptyGraph:
    def test_empty_graph_properties(self) -> None:
        graph = SessionGraph()
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0
        assert len(graph.agent_paths) == 0

    def test_empty_to_dict(self) -> None:
        graph = SessionGraph(session_id="empty")
        d = graph.to_dict()
        assert d["node_count"] == 0
        assert d["edge_count"] == 0
        assert d["agent_ids"] == []
        assert d["nodes"] == {}
        assert d["edges"] == []

    def test_empty_from_dict_round_trip(self) -> None:
        graph = SessionGraph(session_id="empty")
        d = graph.to_dict()
        restored = SessionGraph.from_dict(d)
        assert restored.session_id == "empty"
        assert len(restored.nodes) == 0
