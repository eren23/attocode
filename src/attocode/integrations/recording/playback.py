"""Playback engine for recorded session graphs.

Provides frame-by-frame iteration over a SessionGraph,
supporting timeline scrubbing, filtering by agent/kind,
and state snapshot generation at any point in time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from attocode.integrations.recording.graph_types import (
    GraphNode,
    NodeKind,
    SessionGraph,
)


@dataclass(slots=True)
class PlaybackState:
    """State snapshot at a given point in playback."""

    frame_index: int
    total_frames: int
    current_node: GraphNode | None
    elapsed_seconds: float
    agent_id: str
    iteration: int
    # Cumulative stats up to this point
    total_tokens: int = 0
    total_cost: float = 0.0
    tool_calls: int = 0
    messages: int = 0
    errors: int = 0
    files_visited: set[str] = field(default_factory=set)


class PlaybackEngine:
    """Step through a SessionGraph frame by frame.

    Supports:
    - Forward/backward navigation
    - Jump to specific frame or timestamp
    - Filtering by agent ID or node kind
    - Cumulative state tracking
    """

    def __init__(self, graph: SessionGraph) -> None:
        self._graph = graph
        # Build timeline: all nodes sorted by timestamp
        self._timeline: list[GraphNode] = sorted(
            graph.nodes.values(),
            key=lambda n: (n.timestamp, n.iteration),
        )
        self._index = 0
        self._filters: dict[str, Any] = {}

    @property
    def total_frames(self) -> int:
        return len(self._filtered_timeline)

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def current_node(self) -> GraphNode | None:
        timeline = self._filtered_timeline
        if 0 <= self._index < len(timeline):
            return timeline[self._index]
        return None

    @property
    def _filtered_timeline(self) -> list[GraphNode]:
        """Apply current filters to the timeline."""
        timeline = self._timeline
        agent_filter = self._filters.get("agent_id")
        kind_filter = self._filters.get("kind")

        if agent_filter:
            timeline = [n for n in timeline if n.agent_id == agent_filter]
        if kind_filter:
            if isinstance(kind_filter, (list, set)):
                timeline = [n for n in timeline if n.kind in kind_filter]
            else:
                timeline = [n for n in timeline if n.kind == kind_filter]
        return timeline

    def set_filter(self, *, agent_id: str | None = None, kind: NodeKind | list[NodeKind] | None = None) -> None:
        """Set playback filters. Pass None to clear a filter."""
        if agent_id is not None:
            self._filters["agent_id"] = agent_id
        elif "agent_id" in self._filters:
            del self._filters["agent_id"]

        if kind is not None:
            self._filters["kind"] = kind
        elif "kind" in self._filters:
            del self._filters["kind"]

        # Reset index to stay in bounds
        self._index = min(self._index, max(0, self.total_frames - 1))

    def clear_filters(self) -> None:
        """Remove all playback filters."""
        self._filters.clear()
        self._index = min(self._index, max(0, self.total_frames - 1))

    def step_forward(self) -> PlaybackState:
        """Advance one frame."""
        if self._index < self.total_frames - 1:
            self._index += 1
        return self.get_state()

    def step_backward(self) -> PlaybackState:
        """Go back one frame."""
        if self._index > 0:
            self._index -= 1
        return self.get_state()

    def jump_to(self, index: int) -> PlaybackState:
        """Jump to a specific frame index."""
        self._index = max(0, min(index, self.total_frames - 1))
        return self.get_state()

    def jump_to_start(self) -> PlaybackState:
        """Jump to the first frame."""
        self._index = 0
        return self.get_state()

    def jump_to_end(self) -> PlaybackState:
        """Jump to the last frame."""
        self._index = max(0, self.total_frames - 1)
        return self.get_state()

    def jump_to_timestamp(self, timestamp: float) -> PlaybackState:
        """Jump to the frame closest to the given timestamp."""
        timeline = self._filtered_timeline
        if not timeline:
            return self.get_state()

        best_idx = 0
        best_diff = abs(timeline[0].timestamp - timestamp)
        for i, node in enumerate(timeline):
            diff = abs(node.timestamp - timestamp)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        self._index = best_idx
        return self.get_state()

    def get_state(self) -> PlaybackState:
        """Build a cumulative state snapshot at the current frame."""
        timeline = self._filtered_timeline
        if not timeline:
            return PlaybackState(
                frame_index=0,
                total_frames=0,
                current_node=None,
                elapsed_seconds=0.0,
                agent_id="main",
                iteration=0,
            )

        current = timeline[min(self._index, len(timeline) - 1)]
        start_time = timeline[0].timestamp if timeline else 0.0

        # Compute cumulative stats up to current frame
        total_tokens = 0
        total_cost = 0.0
        tool_calls = 0
        messages = 0
        errors = 0
        files_visited: set[str] = set()

        for i in range(min(self._index + 1, len(timeline))):
            node = timeline[i]
            if node.kind == NodeKind.LLM_CALL:
                total_tokens += node.input_tokens + node.output_tokens
                total_cost += node.cost
            elif node.kind == NodeKind.TOOL_CALL:
                tool_calls += 1
            elif node.kind == NodeKind.MESSAGE:
                messages += 1
            elif node.kind == NodeKind.ERROR:
                errors += 1
            elif node.kind == NodeKind.FILE_VISIT and node.file_path:
                files_visited.add(node.file_path)

        return PlaybackState(
            frame_index=self._index,
            total_frames=self.total_frames,
            current_node=current,
            elapsed_seconds=current.timestamp - start_time,
            agent_id=current.agent_id,
            iteration=current.iteration,
            total_tokens=total_tokens,
            total_cost=total_cost,
            tool_calls=tool_calls,
            messages=messages,
            errors=errors,
            files_visited=files_visited,
        )

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the entire recording."""
        timeline = self._filtered_timeline
        if not timeline:
            return {"total_frames": 0, "duration": 0.0}

        duration = timeline[-1].timestamp - timeline[0].timestamp
        kind_counts: dict[str, int] = {}
        agent_ids: set[str] = set()

        for node in timeline:
            kind_counts[node.kind.value] = kind_counts.get(node.kind.value, 0) + 1
            agent_ids.add(node.agent_id)

        return {
            "total_frames": len(timeline),
            "duration": duration,
            "start_time": timeline[0].timestamp,
            "end_time": timeline[-1].timestamp,
            "agent_ids": sorted(agent_ids),
            "kind_counts": kind_counts,
        }
