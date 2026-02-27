"""Tests for the playback engine.

Covers:
- PlaybackEngine initialization with a SessionGraph
- total_frames, current_index, current_node properties
- step_forward / step_backward navigation
- jump_to, jump_to_start, jump_to_end
- jump_to_timestamp
- set_filter by agent_id
- set_filter by single NodeKind and list of NodeKinds
- clear_filters
- get_state returns cumulative stats (tokens, cost, tool_calls, etc.)
- get_summary stats
- Edge cases: empty graph, single node, backward at start, forward at end
"""

from __future__ import annotations

import pytest

from attocode.integrations.recording.graph_types import (
    GraphNode,
    NodeKind,
    SessionGraph,
)
from attocode.integrations.recording.playback import PlaybackEngine, PlaybackState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_graph(
    nodes: list[tuple[NodeKind, dict]],
    *,
    session_id: str = "test",
) -> SessionGraph:
    """Build a SessionGraph from a list of (kind, kwargs) tuples."""
    graph = SessionGraph(session_id=session_id)
    for kind, kwargs in nodes:
        graph.add_node(kind, **kwargs)
    return graph


def _simple_graph() -> SessionGraph:
    """Build a basic 5-node graph for common tests."""
    return _build_graph([
        (NodeKind.MESSAGE, {"content": "Hello", "timestamp": 100.0, "iteration": 1}),
        (NodeKind.LLM_CALL, {"model": "claude", "input_tokens": 500, "output_tokens": 200, "cost": 0.01, "timestamp": 101.0, "iteration": 2}),
        (NodeKind.TOOL_CALL, {"tool_name": "read_file", "timestamp": 102.0, "iteration": 3}),
        (NodeKind.FILE_VISIT, {"file_path": "src/main.py", "action": "read", "timestamp": 103.0, "iteration": 4}),
        (NodeKind.ERROR, {"content": "Something broke", "timestamp": 104.0, "iteration": 5}),
    ])


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestPlaybackEngineInit:
    def test_init_with_graph(self) -> None:
        graph = _simple_graph()
        engine = PlaybackEngine(graph)
        assert engine.total_frames == 5
        assert engine.current_index == 0

    def test_init_empty_graph(self) -> None:
        graph = SessionGraph()
        engine = PlaybackEngine(graph)
        assert engine.total_frames == 0
        assert engine.current_index == 0
        assert engine.current_node is None

    def test_timeline_sorted_by_timestamp(self) -> None:
        """Nodes added out of order should be sorted by timestamp."""
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE, content="third", timestamp=300.0)
        graph.add_node(NodeKind.MESSAGE, content="first", timestamp=100.0)
        graph.add_node(NodeKind.MESSAGE, content="second", timestamp=200.0)

        engine = PlaybackEngine(graph)
        assert engine.current_node is not None
        assert engine.current_node.content == "first"

    def test_timeline_sorted_by_iteration_as_tiebreaker(self) -> None:
        """Nodes with the same timestamp sort by iteration."""
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE, content="b", timestamp=100.0, iteration=2)
        graph.add_node(NodeKind.MESSAGE, content="a", timestamp=100.0, iteration=1)

        engine = PlaybackEngine(graph)
        assert engine.current_node is not None
        assert engine.current_node.content == "a"


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestPlaybackProperties:
    def test_total_frames(self) -> None:
        graph = _simple_graph()
        engine = PlaybackEngine(graph)
        assert engine.total_frames == 5

    def test_current_index_starts_at_zero(self) -> None:
        graph = _simple_graph()
        engine = PlaybackEngine(graph)
        assert engine.current_index == 0

    def test_current_node_at_start(self) -> None:
        graph = _simple_graph()
        engine = PlaybackEngine(graph)
        node = engine.current_node
        assert node is not None
        assert node.kind == NodeKind.MESSAGE
        assert node.content == "Hello"

    def test_current_node_none_for_empty(self) -> None:
        engine = PlaybackEngine(SessionGraph())
        assert engine.current_node is None


# ---------------------------------------------------------------------------
# step_forward / step_backward
# ---------------------------------------------------------------------------


class TestStepNavigation:
    def test_step_forward(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        state = engine.step_forward()
        assert engine.current_index == 1
        assert state.frame_index == 1
        assert state.current_node is not None
        assert state.current_node.kind == NodeKind.LLM_CALL

    def test_step_forward_multiple(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        for _ in range(3):
            engine.step_forward()
        assert engine.current_index == 3
        assert engine.current_node is not None
        assert engine.current_node.kind == NodeKind.FILE_VISIT

    def test_step_forward_at_end_stays(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        # Move to end
        for _ in range(10):
            engine.step_forward()
        assert engine.current_index == 4  # 5 frames, 0-indexed max = 4
        # One more step should stay at end
        engine.step_forward()
        assert engine.current_index == 4

    def test_step_backward(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        engine.step_forward()
        engine.step_forward()
        state = engine.step_backward()
        assert engine.current_index == 1
        assert state.frame_index == 1

    def test_step_backward_at_start_stays(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        state = engine.step_backward()
        assert engine.current_index == 0
        assert state.frame_index == 0

    def test_step_forward_empty_graph(self) -> None:
        engine = PlaybackEngine(SessionGraph())
        state = engine.step_forward()
        assert state.current_node is None
        assert state.total_frames == 0

    def test_step_backward_empty_graph(self) -> None:
        engine = PlaybackEngine(SessionGraph())
        state = engine.step_backward()
        assert state.current_node is None
        assert state.total_frames == 0


# ---------------------------------------------------------------------------
# jump_to, jump_to_start, jump_to_end
# ---------------------------------------------------------------------------


class TestJumpNavigation:
    def test_jump_to_specific_frame(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        state = engine.jump_to(3)
        assert engine.current_index == 3
        assert state.current_node is not None
        assert state.current_node.kind == NodeKind.FILE_VISIT

    def test_jump_to_clamps_negative(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        state = engine.jump_to(-5)
        assert engine.current_index == 0

    def test_jump_to_clamps_beyond_end(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        state = engine.jump_to(100)
        assert engine.current_index == 4

    def test_jump_to_start(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        engine.jump_to(3)
        state = engine.jump_to_start()
        assert engine.current_index == 0
        assert state.frame_index == 0

    def test_jump_to_end(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        state = engine.jump_to_end()
        assert engine.current_index == 4
        assert state.current_node is not None
        assert state.current_node.kind == NodeKind.ERROR

    def test_jump_to_end_empty_graph(self) -> None:
        engine = PlaybackEngine(SessionGraph())
        state = engine.jump_to_end()
        assert engine.current_index == 0
        assert state.current_node is None

    def test_jump_to_start_empty_graph(self) -> None:
        engine = PlaybackEngine(SessionGraph())
        state = engine.jump_to_start()
        assert engine.current_index == 0
        assert state.current_node is None


# ---------------------------------------------------------------------------
# jump_to_timestamp
# ---------------------------------------------------------------------------


class TestJumpToTimestamp:
    def test_exact_timestamp(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        state = engine.jump_to_timestamp(102.0)
        assert state.current_node is not None
        assert state.current_node.kind == NodeKind.TOOL_CALL

    def test_closest_timestamp(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        # 101.3 is closest to 101.0 (LLM_CALL)
        state = engine.jump_to_timestamp(101.3)
        assert state.current_node is not None
        assert state.current_node.kind == NodeKind.LLM_CALL

    def test_timestamp_before_first(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        state = engine.jump_to_timestamp(0.0)
        assert state.current_node is not None
        assert state.current_node.kind == NodeKind.MESSAGE

    def test_timestamp_after_last(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        state = engine.jump_to_timestamp(9999.0)
        assert state.current_node is not None
        assert state.current_node.kind == NodeKind.ERROR

    def test_timestamp_empty_graph(self) -> None:
        engine = PlaybackEngine(SessionGraph())
        state = engine.jump_to_timestamp(100.0)
        assert state.current_node is None


# ---------------------------------------------------------------------------
# set_filter by agent_id
# ---------------------------------------------------------------------------


class TestFilterByAgent:
    def _multi_agent_graph(self) -> SessionGraph:
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE, agent_id="a1", content="a1-msg", timestamp=1.0)
        graph.add_node(NodeKind.TOOL_CALL, agent_id="a2", tool_name="bash", timestamp=2.0)
        graph.add_node(NodeKind.LLM_CALL, agent_id="a1", model="claude", timestamp=3.0)
        graph.add_node(NodeKind.MESSAGE, agent_id="a2", content="a2-msg", timestamp=4.0)
        graph.add_node(NodeKind.ERROR, agent_id="a1", content="oops", timestamp=5.0)
        return graph

    def test_filter_by_agent(self) -> None:
        engine = PlaybackEngine(self._multi_agent_graph())
        engine.set_filter(agent_id="a1")
        assert engine.total_frames == 3
        assert engine.current_node is not None
        assert engine.current_node.agent_id == "a1"

    def test_filter_by_other_agent(self) -> None:
        engine = PlaybackEngine(self._multi_agent_graph())
        engine.set_filter(agent_id="a2")
        assert engine.total_frames == 2
        assert engine.current_node is not None
        assert engine.current_node.agent_id == "a2"

    def test_filter_nonexistent_agent(self) -> None:
        engine = PlaybackEngine(self._multi_agent_graph())
        engine.set_filter(agent_id="nonexistent")
        assert engine.total_frames == 0
        assert engine.current_node is None

    def test_filter_resets_index_to_bounds(self) -> None:
        engine = PlaybackEngine(self._multi_agent_graph())
        engine.jump_to(4)  # index 4 (last frame)
        engine.set_filter(agent_id="a2")  # only 2 frames
        assert engine.current_index <= 1  # clamped to max valid index

    def test_clear_agent_filter(self) -> None:
        engine = PlaybackEngine(self._multi_agent_graph())
        engine.set_filter(agent_id="a1")
        assert engine.total_frames == 3
        engine.set_filter(agent_id=None)
        assert engine.total_frames == 5


# ---------------------------------------------------------------------------
# set_filter by NodeKind
# ---------------------------------------------------------------------------


class TestFilterByKind:
    def test_filter_single_kind(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        engine.set_filter(kind=NodeKind.MESSAGE)
        assert engine.total_frames == 1
        assert engine.current_node is not None
        assert engine.current_node.kind == NodeKind.MESSAGE

    def test_filter_list_of_kinds(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        engine.set_filter(kind=[NodeKind.MESSAGE, NodeKind.ERROR])
        assert engine.total_frames == 2

    def test_filter_kind_no_matches(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        engine.set_filter(kind=NodeKind.CHECKPOINT)
        assert engine.total_frames == 0
        assert engine.current_node is None

    def test_filter_set_of_kinds(self) -> None:
        """_filtered_timeline checks isinstance(kind_filter, (list, set))."""
        engine = PlaybackEngine(_simple_graph())
        engine.set_filter(kind=[NodeKind.LLM_CALL, NodeKind.TOOL_CALL])
        assert engine.total_frames == 2

    def test_clear_kind_filter(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        engine.set_filter(kind=NodeKind.MESSAGE)
        assert engine.total_frames == 1
        engine.set_filter(kind=None)
        assert engine.total_frames == 5


# ---------------------------------------------------------------------------
# Combined filters
# ---------------------------------------------------------------------------


class TestCombinedFilters:
    def test_agent_and_kind_filter(self) -> None:
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE, agent_id="a1", content="msg", timestamp=1.0)
        graph.add_node(NodeKind.LLM_CALL, agent_id="a1", model="claude", timestamp=2.0)
        graph.add_node(NodeKind.MESSAGE, agent_id="a2", content="other", timestamp=3.0)
        graph.add_node(NodeKind.TOOL_CALL, agent_id="a1", tool_name="bash", timestamp=4.0)

        engine = PlaybackEngine(graph)
        engine.set_filter(agent_id="a1", kind=NodeKind.MESSAGE)
        assert engine.total_frames == 1
        assert engine.current_node is not None
        assert engine.current_node.content == "msg"

    def test_set_filter_updates_existing(self) -> None:
        """Calling set_filter again should replace the previous filter."""
        engine = PlaybackEngine(_simple_graph())
        engine.set_filter(kind=NodeKind.MESSAGE)
        assert engine.total_frames == 1
        engine.set_filter(kind=NodeKind.LLM_CALL)
        assert engine.total_frames == 1
        assert engine.current_node is not None
        assert engine.current_node.kind == NodeKind.LLM_CALL


# ---------------------------------------------------------------------------
# clear_filters
# ---------------------------------------------------------------------------


class TestClearFilters:
    def test_clear_all_filters(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        engine.set_filter(agent_id="main", kind=NodeKind.MESSAGE)
        engine.clear_filters()
        assert engine.total_frames == 5

    def test_clear_resets_index_within_bounds(self) -> None:
        graph = SessionGraph()
        for i in range(3):
            graph.add_node(NodeKind.MESSAGE, content=f"msg{i}", timestamp=float(i))

        engine = PlaybackEngine(graph)
        engine.jump_to(2)
        # Filter to 1 item, index clamped
        engine.set_filter(kind=NodeKind.LLM_CALL)  # 0 items
        engine.clear_filters()
        # After clearing, index should still be valid
        assert 0 <= engine.current_index < engine.total_frames

    def test_clear_on_empty_graph(self) -> None:
        engine = PlaybackEngine(SessionGraph())
        engine.clear_filters()
        assert engine.total_frames == 0


# ---------------------------------------------------------------------------
# get_state: cumulative stats
# ---------------------------------------------------------------------------


class TestGetState:
    def test_state_at_start(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        state = engine.get_state()

        assert state.frame_index == 0
        assert state.total_frames == 5
        assert state.current_node is not None
        assert state.current_node.kind == NodeKind.MESSAGE
        assert state.agent_id == "main"
        assert state.iteration == 1
        # At frame 0 (MESSAGE), cumulative stats should show 1 message
        assert state.messages == 1
        assert state.total_tokens == 0
        assert state.total_cost == 0.0
        assert state.tool_calls == 0
        assert state.errors == 0

    def test_state_cumulates_through_llm_call(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        engine.step_forward()  # Now at LLM_CALL (index 1)
        state = engine.get_state()

        assert state.frame_index == 1
        assert state.total_tokens == 700  # 500 + 200
        assert state.total_cost == 0.01
        assert state.messages == 1  # MESSAGE from frame 0

    def test_state_cumulates_tool_calls(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        engine.jump_to(2)  # TOOL_CALL
        state = engine.get_state()

        assert state.tool_calls == 1
        assert state.messages == 1
        assert state.total_tokens == 700

    def test_state_cumulates_file_visits(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        engine.jump_to(3)  # FILE_VISIT
        state = engine.get_state()

        assert "src/main.py" in state.files_visited
        assert len(state.files_visited) == 1

    def test_state_cumulates_errors(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        engine.jump_to_end()  # ERROR at index 4
        state = engine.get_state()

        assert state.errors == 1
        assert state.messages == 1
        assert state.total_tokens == 700
        assert state.tool_calls == 1

    def test_state_elapsed_seconds(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        engine.jump_to_end()
        state = engine.get_state()

        # First node at 100.0, last at 104.0
        assert state.elapsed_seconds == pytest.approx(4.0)

    def test_state_elapsed_at_start(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        state = engine.get_state()
        assert state.elapsed_seconds == pytest.approx(0.0)

    def test_state_empty_graph(self) -> None:
        engine = PlaybackEngine(SessionGraph())
        state = engine.get_state()

        assert state.frame_index == 0
        assert state.total_frames == 0
        assert state.current_node is None
        assert state.elapsed_seconds == 0.0
        assert state.agent_id == "main"
        assert state.iteration == 0

    def test_state_with_filter(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        engine.set_filter(kind=NodeKind.MESSAGE)
        state = engine.get_state()

        assert state.total_frames == 1
        assert state.messages == 1
        assert state.total_tokens == 0

    def test_state_multiple_llm_calls(self) -> None:
        graph = _build_graph([
            (NodeKind.LLM_CALL, {"model": "a", "input_tokens": 100, "output_tokens": 50, "cost": 0.005, "timestamp": 1.0}),
            (NodeKind.LLM_CALL, {"model": "b", "input_tokens": 200, "output_tokens": 100, "cost": 0.01, "timestamp": 2.0}),
            (NodeKind.LLM_CALL, {"model": "c", "input_tokens": 300, "output_tokens": 150, "cost": 0.02, "timestamp": 3.0}),
        ])
        engine = PlaybackEngine(graph)
        engine.jump_to_end()
        state = engine.get_state()

        assert state.total_tokens == (100 + 50) + (200 + 100) + (300 + 150)
        assert state.total_cost == pytest.approx(0.035)

    def test_state_file_visit_without_path_not_tracked(self) -> None:
        """FILE_VISIT nodes with empty file_path should not be added to files_visited."""
        graph = _build_graph([
            (NodeKind.FILE_VISIT, {"file_path": "", "timestamp": 1.0}),
            (NodeKind.FILE_VISIT, {"file_path": "real.py", "timestamp": 2.0}),
        ])
        engine = PlaybackEngine(graph)
        engine.jump_to_end()
        state = engine.get_state()
        assert state.files_visited == {"real.py"}

    def test_state_files_visited_deduplication(self) -> None:
        graph = _build_graph([
            (NodeKind.FILE_VISIT, {"file_path": "a.py", "timestamp": 1.0}),
            (NodeKind.FILE_VISIT, {"file_path": "a.py", "timestamp": 2.0}),
            (NodeKind.FILE_VISIT, {"file_path": "b.py", "timestamp": 3.0}),
        ])
        engine = PlaybackEngine(graph)
        engine.jump_to_end()
        state = engine.get_state()
        assert state.files_visited == {"a.py", "b.py"}


# ---------------------------------------------------------------------------
# get_summary
# ---------------------------------------------------------------------------


class TestGetSummary:
    def test_summary_basic(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        summary = engine.get_summary()

        assert summary["total_frames"] == 5
        assert summary["duration"] == pytest.approx(4.0)
        assert summary["start_time"] == pytest.approx(100.0)
        assert summary["end_time"] == pytest.approx(104.0)
        assert "main" in summary["agent_ids"]

    def test_summary_kind_counts(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        summary = engine.get_summary()

        counts = summary["kind_counts"]
        assert counts["message"] == 1
        assert counts["llm_call"] == 1
        assert counts["tool_call"] == 1
        assert counts["file_visit"] == 1
        assert counts["error"] == 1

    def test_summary_multiple_agents(self) -> None:
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE, agent_id="a1", timestamp=1.0)
        graph.add_node(NodeKind.MESSAGE, agent_id="a2", timestamp=2.0)
        graph.add_node(NodeKind.MESSAGE, agent_id="a3", timestamp=3.0)

        engine = PlaybackEngine(graph)
        summary = engine.get_summary()
        assert sorted(summary["agent_ids"]) == ["a1", "a2", "a3"]

    def test_summary_empty_graph(self) -> None:
        engine = PlaybackEngine(SessionGraph())
        summary = engine.get_summary()
        assert summary["total_frames"] == 0
        assert summary["duration"] == 0.0
        # No start_time or end_time keys for empty graph
        assert "start_time" not in summary

    def test_summary_with_filter(self) -> None:
        engine = PlaybackEngine(_simple_graph())
        engine.set_filter(kind=NodeKind.MESSAGE)
        summary = engine.get_summary()
        assert summary["total_frames"] == 1
        assert summary["duration"] == pytest.approx(0.0)  # single node duration

    def test_summary_single_node(self) -> None:
        graph = _build_graph([
            (NodeKind.MESSAGE, {"content": "only one", "timestamp": 50.0}),
        ])
        engine = PlaybackEngine(graph)
        summary = engine.get_summary()
        assert summary["total_frames"] == 1
        assert summary["duration"] == pytest.approx(0.0)
        assert summary["start_time"] == pytest.approx(50.0)
        assert summary["end_time"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Edge case: single node
# ---------------------------------------------------------------------------


class TestSingleNode:
    def test_single_node_navigation(self) -> None:
        graph = _build_graph([
            (NodeKind.MESSAGE, {"content": "alone", "timestamp": 1.0}),
        ])
        engine = PlaybackEngine(graph)

        assert engine.total_frames == 1
        assert engine.current_index == 0
        assert engine.current_node is not None
        assert engine.current_node.content == "alone"

        # step_forward should not advance
        engine.step_forward()
        assert engine.current_index == 0

        # step_backward should not go negative
        engine.step_backward()
        assert engine.current_index == 0

        # jump_to_end == jump_to_start for single node
        engine.jump_to_end()
        assert engine.current_index == 0
        engine.jump_to_start()
        assert engine.current_index == 0

    def test_single_node_state(self) -> None:
        graph = _build_graph([
            (NodeKind.LLM_CALL, {"model": "gpt", "input_tokens": 100, "output_tokens": 50, "cost": 0.005, "timestamp": 1.0}),
        ])
        engine = PlaybackEngine(graph)
        state = engine.get_state()

        assert state.total_frames == 1
        assert state.total_tokens == 150
        assert state.total_cost == pytest.approx(0.005)
        assert state.elapsed_seconds == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# PlaybackState dataclass
# ---------------------------------------------------------------------------


class TestPlaybackState:
    def test_default_fields(self) -> None:
        state = PlaybackState(
            frame_index=0,
            total_frames=1,
            current_node=None,
            elapsed_seconds=0.0,
            agent_id="main",
            iteration=0,
        )
        assert state.total_tokens == 0
        assert state.total_cost == 0.0
        assert state.tool_calls == 0
        assert state.messages == 0
        assert state.errors == 0
        assert state.files_visited == set()

    def test_files_visited_default_not_shared(self) -> None:
        """Ensure default_factory creates independent sets."""
        s1 = PlaybackState(
            frame_index=0, total_frames=0, current_node=None,
            elapsed_seconds=0.0, agent_id="main", iteration=0,
        )
        s2 = PlaybackState(
            frame_index=0, total_frames=0, current_node=None,
            elapsed_seconds=0.0, agent_id="main", iteration=0,
        )
        s1.files_visited.add("a.py")
        assert "a.py" not in s2.files_visited


# ---------------------------------------------------------------------------
# Navigation after filter changes
# ---------------------------------------------------------------------------


class TestNavigationWithFilters:
    def test_step_forward_with_filter(self) -> None:
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE, content="msg1", timestamp=1.0)
        graph.add_node(NodeKind.TOOL_CALL, tool_name="bash", timestamp=2.0)
        graph.add_node(NodeKind.MESSAGE, content="msg2", timestamp=3.0)
        graph.add_node(NodeKind.TOOL_CALL, tool_name="read", timestamp=4.0)

        engine = PlaybackEngine(graph)
        engine.set_filter(kind=NodeKind.MESSAGE)

        assert engine.total_frames == 2
        assert engine.current_node is not None
        assert engine.current_node.content == "msg1"

        engine.step_forward()
        assert engine.current_node is not None
        assert engine.current_node.content == "msg2"

    def test_jump_to_end_with_filter(self) -> None:
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE, content="msg", timestamp=1.0)
        graph.add_node(NodeKind.LLM_CALL, model="a", timestamp=2.0)
        graph.add_node(NodeKind.LLM_CALL, model="b", timestamp=3.0)
        graph.add_node(NodeKind.MESSAGE, content="end", timestamp=4.0)

        engine = PlaybackEngine(graph)
        engine.set_filter(kind=NodeKind.LLM_CALL)
        engine.jump_to_end()

        assert engine.current_node is not None
        assert engine.current_node.model == "b"

    def test_index_clamped_when_filter_reduces_frames(self) -> None:
        graph = SessionGraph()
        for i in range(10):
            graph.add_node(NodeKind.MESSAGE, content=f"m{i}", timestamp=float(i))

        engine = PlaybackEngine(graph)
        engine.jump_to(8)  # index 8
        # Now filter to a kind with 0 matches
        engine.set_filter(kind=NodeKind.ERROR)
        assert engine.current_index == 0
        assert engine.total_frames == 0

    def test_filter_change_preserves_clamped_position(self) -> None:
        graph = SessionGraph()
        graph.add_node(NodeKind.MESSAGE, content="a", timestamp=1.0)
        graph.add_node(NodeKind.LLM_CALL, model="x", timestamp=2.0)

        engine = PlaybackEngine(graph)
        engine.jump_to(1)  # at LLM_CALL
        engine.set_filter(kind=NodeKind.MESSAGE)  # only 1 frame, index clamped to 0
        assert engine.current_index == 0
        assert engine.current_node is not None
        assert engine.current_node.kind == NodeKind.MESSAGE
