"""Tests for trajectory analysis."""

from __future__ import annotations

import pytest

from attocode.integrations.quality.trajectory import (
    PatternDetection,
    TrajectoryPattern,
    TrajectoryTracker,
    TrajectoryTriple,
)


class TestTrajectoryTracker:
    """Tests for TrajectoryTracker."""

    def test_record_triple(self) -> None:
        tracker = TrajectoryTracker()
        triple = tracker.record(
            iteration=1,
            reasoning="Need to read the file",
            tool_name="read_file",
            tool_args={"path": "/foo.py"},
            result_summary="File contents returned",
            success=True,
            tokens_used=100,
        )
        assert triple.iteration == 1
        assert triple.tool_name == "read_file"
        assert triple.success is True
        assert len(tracker.triples) == 1

    def test_max_history_eviction(self) -> None:
        tracker = TrajectoryTracker(max_history=5)
        for i in range(10):
            tracker.record(iteration=i, reasoning=f"step {i}")
        assert len(tracker.triples) == 5
        assert tracker.triples[0].iteration == 5

    def test_detect_repetitive_loop(self) -> None:
        tracker = TrajectoryTracker()
        # Create a repeating pattern: read, edit, read, edit
        for i in range(8):
            tool = "read_file" if i % 2 == 0 else "edit_file"
            tracker.record(iteration=i, reasoning="step", tool_name=tool)

        patterns = tracker.analyze()
        loop_patterns = [p for p in patterns if p.pattern == TrajectoryPattern.REPETITIVE_LOOP]
        assert len(loop_patterns) >= 1
        assert loop_patterns[0].confidence >= 0.7

    def test_detect_spinning(self) -> None:
        tracker = TrajectoryTracker()
        # Same tool with same args, all failing
        for i in range(6):
            tracker.record(
                iteration=i,
                reasoning="trying again",
                tool_name="bash",
                tool_args={"cmd": "make build"},
                success=False,
            )
        assert tracker.detect_spinning() is True

    def test_no_spinning_with_diverse_tools(self) -> None:
        tracker = TrajectoryTracker()
        tools = ["read_file", "edit_file", "bash", "search", "write_file", "grep"]
        for i, tool in enumerate(tools):
            tracker.record(iteration=i, reasoning="step", tool_name=tool, success=True)
        assert tracker.detect_spinning() is False

    def test_detect_regression(self) -> None:
        tracker = TrajectoryTracker()
        # First half: mostly success
        for i in range(4):
            tracker.record(iteration=i, reasoning="step", tool_name="read", success=True)
        # Second half: mostly failure
        for i in range(4, 8):
            tracker.record(iteration=i, reasoning="step", tool_name="edit", success=False)

        patterns = tracker.analyze(window=8)
        regression = [p for p in patterns if p.pattern == TrajectoryPattern.REGRESSION]
        assert len(regression) >= 1

    def test_detect_productive(self) -> None:
        tracker = TrajectoryTracker()
        tools = ["read_file", "edit_file", "bash", "search", "write_file"]
        for i, tool in enumerate(tools):
            tracker.record(iteration=i, reasoning="step", tool_name=tool, success=True)

        patterns = tracker.analyze(window=5)
        productive = [p for p in patterns if p.pattern == TrajectoryPattern.PRODUCTIVE]
        assert len(productive) >= 1
        assert productive[0].confidence >= 0.7

    def test_get_summary(self) -> None:
        tracker = TrajectoryTracker()
        tracker.record(iteration=0, reasoning="r", tool_name="read", success=True, tokens_used=50)
        tracker.record(iteration=1, reasoning="r", tool_name="edit", success=True, tokens_used=100)
        tracker.record(iteration=2, reasoning="r", tool_name="bash", success=False, tokens_used=75)

        summary = tracker.get_summary()
        assert summary["total_triples"] == 3
        assert summary["total_tokens"] == 225
        assert summary["success_rate"] == pytest.approx(2 / 3)
        assert "read" in summary["tool_distribution"]
        assert isinstance(summary["is_spinning"], bool)

    def test_clear(self) -> None:
        tracker = TrajectoryTracker()
        tracker.record(iteration=0, reasoning="r", tool_name="read")
        tracker.clear()
        assert len(tracker.triples) == 0
        assert len(tracker.patterns) == 0

    def test_analyze_too_few_triples(self) -> None:
        tracker = TrajectoryTracker()
        tracker.record(iteration=0, reasoning="r")
        patterns = tracker.analyze()
        assert patterns == []

    def test_spinning_same_signatures(self) -> None:
        tracker = TrajectoryTracker()
        for i in range(6):
            tracker.record(
                iteration=i,
                reasoning="same thing",
                tool_name="bash",
                tool_args={"cmd": "npm test"},
                success=True,
            )
        assert tracker.detect_spinning() is True

    def test_no_spinning_with_few_triples(self) -> None:
        tracker = TrajectoryTracker()
        tracker.record(iteration=0, reasoning="r", tool_name="bash")
        assert tracker.detect_spinning() is False
