"""Tests for DiminishingReturnsTracker and TaskProgressWindow."""

from __future__ import annotations

from attoswarm.coordinator.budget_gate import DiminishingReturnsTracker


def test_not_diminishing_too_few_turns() -> None:
    """Fewer than min_turns recorded returns False."""
    tracker = DiminishingReturnsTracker(min_turns=3, delta_threshold=500)

    # Record only 2 turns (below the min_turns=3 threshold)
    tracker.record_turn("task-1", tokens_delta=100, tool_calls=0, files_touched=0)
    tracker.record_turn("task-1", tokens_delta=100, tool_calls=0, files_touched=0)

    assert tracker.is_diminishing("task-1") is False

    # Also test a task that was never recorded
    assert tracker.is_diminishing("nonexistent") is False


def test_diminishing_on_stagnant_turns() -> None:
    """3 turns with <500 tokens and 0 tool calls triggers diminishing."""
    tracker = DiminishingReturnsTracker(min_turns=3, delta_threshold=500)

    for _ in range(3):
        tracker.record_turn("task-1", tokens_delta=100, tool_calls=0, files_touched=0)

    assert tracker.is_diminishing("task-1") is True


def test_not_diminishing_with_tool_calls() -> None:
    """Tool activity in any of the recent turns prevents diminishing detection."""
    tracker = DiminishingReturnsTracker(min_turns=3, delta_threshold=500)

    tracker.record_turn("task-1", tokens_delta=100, tool_calls=0, files_touched=0)
    tracker.record_turn("task-1", tokens_delta=100, tool_calls=1, files_touched=0)
    tracker.record_turn("task-1", tokens_delta=100, tool_calls=0, files_touched=0)

    assert tracker.is_diminishing("task-1") is False


def test_not_diminishing_with_high_tokens() -> None:
    """High token output in any recent turn prevents diminishing detection."""
    tracker = DiminishingReturnsTracker(min_turns=3, delta_threshold=500)

    tracker.record_turn("task-1", tokens_delta=100, tool_calls=0, files_touched=0)
    tracker.record_turn("task-1", tokens_delta=100, tool_calls=0, files_touched=0)
    tracker.record_turn("task-1", tokens_delta=800, tool_calls=0, files_touched=0)

    assert tracker.is_diminishing("task-1") is False


def test_clear_task_removes_window() -> None:
    """clear_task removes all tracking for that task."""
    tracker = DiminishingReturnsTracker(min_turns=3, delta_threshold=500)

    for _ in range(5):
        tracker.record_turn("task-1", tokens_delta=50, tool_calls=0, files_touched=0)

    assert tracker.is_diminishing("task-1") is True

    tracker.clear_task("task-1")
    assert tracker.is_diminishing("task-1") is False

    # Clearing a nonexistent task is a no-op
    tracker.clear_task("nonexistent")


def test_max_window_trim() -> None:
    """Recording more than max_window turns trims the window to max_window."""
    tracker = DiminishingReturnsTracker(min_turns=3, delta_threshold=500, max_window=20)

    # Record 25 turns
    for i in range(25):
        tracker.record_turn("task-1", tokens_delta=i * 10, tool_calls=0, files_touched=0)

    # Internal window should have exactly 20 entries
    window = tracker._windows["task-1"]
    assert len(window.turn_deltas) == 20
    assert len(window.tool_calls_per_turn) == 20
    assert len(window.files_touched_per_turn) == 20

    # The oldest 5 entries (i=0..4) should have been trimmed.
    # The window should start from i=5, so first delta = 50.
    assert window.turn_deltas[0] == 50


def test_to_dict() -> None:
    """to_dict serialization includes all tracked tasks."""
    tracker = DiminishingReturnsTracker()

    tracker.record_turn("task-a", tokens_delta=100, tool_calls=1, files_touched=2)
    tracker.record_turn("task-b", tokens_delta=200, tool_calls=0, files_touched=0)

    d = tracker.to_dict()

    assert "task-a" in d
    assert "task-b" in d

    assert d["task-a"]["turn_deltas"] == [100]
    assert d["task-a"]["tool_calls"] == [1]
    assert d["task-a"]["files_touched"] == [2]

    assert d["task-b"]["turn_deltas"] == [200]
    assert d["task-b"]["tool_calls"] == [0]
    assert d["task-b"]["files_touched"] == [0]
