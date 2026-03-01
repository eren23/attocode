"""Tests for AutoCheckpointManager: intervals, milestones, eviction, clear."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from attocode.integrations.quality.auto_checkpoint import (
    AutoCheckpointManager,
    CheckpointConfig,
)


class TestCheckAndSave:
    """check_and_save creates checkpoints based on elapsed time."""

    def test_first_call_after_interval_creates_checkpoint(self) -> None:
        cfg = CheckpointConfig(interval_seconds=0.0)  # always expired
        mgr = AutoCheckpointManager(config=cfg)
        cp = mgr.check_and_save(iteration=1, description="step 1")
        assert cp is not None
        assert cp.iteration == 1
        assert "step 1" in cp.description

    def test_within_interval_skips(self) -> None:
        cfg = CheckpointConfig(interval_seconds=9999)
        mgr = AutoCheckpointManager(config=cfg)
        cp = mgr.check_and_save(iteration=1)
        assert cp is None

    def test_auto_description_when_empty(self) -> None:
        cfg = CheckpointConfig(interval_seconds=0.0)
        mgr = AutoCheckpointManager(config=cfg)
        cp = mgr.check_and_save(iteration=5)
        assert cp is not None
        assert "iteration 5" in cp.description

    def test_saver_callback_invoked(self) -> None:
        saver = MagicMock(return_value="custom-id-42")
        cfg = CheckpointConfig(interval_seconds=0.0)
        mgr = AutoCheckpointManager(config=cfg, saver=saver)
        cp = mgr.check_and_save(iteration=3, description="test")
        saver.assert_called_once_with(3, "test")
        assert cp is not None
        assert cp.id == "custom-id-42"

    def test_saver_returning_none_generates_id(self) -> None:
        saver = MagicMock(return_value=None)
        cfg = CheckpointConfig(interval_seconds=0.0)
        mgr = AutoCheckpointManager(config=cfg, saver=saver)
        cp = mgr.check_and_save(iteration=1, description="x")
        assert cp is not None
        assert cp.id.startswith("cp-")

    def test_saver_exception_returns_none(self) -> None:
        def bad_saver(iteration: int, desc: str) -> str:
            raise RuntimeError("disk full")

        cfg = CheckpointConfig(interval_seconds=0.0)
        mgr = AutoCheckpointManager(config=cfg, saver=bad_saver)
        cp = mgr.check_and_save(iteration=1, description="x")
        assert cp is None

    def test_checkpoint_stored_in_list(self) -> None:
        cfg = CheckpointConfig(interval_seconds=0.0)
        mgr = AutoCheckpointManager(config=cfg)
        mgr.check_and_save(iteration=1)
        mgr.check_and_save(iteration=2)
        assert mgr.checkpoint_count == 2
        assert len(mgr.checkpoints) == 2

    def test_last_checkpoint_property(self) -> None:
        cfg = CheckpointConfig(interval_seconds=0.0)
        mgr = AutoCheckpointManager(config=cfg)
        assert mgr.last_checkpoint is None
        mgr.check_and_save(iteration=1, description="first")
        mgr.check_and_save(iteration=2, description="second")
        assert mgr.last_checkpoint is not None
        assert "second" in mgr.last_checkpoint.description


class TestForceCheckpoint:
    """force=True bypasses the interval check."""

    def test_force_within_interval(self) -> None:
        cfg = CheckpointConfig(interval_seconds=9999)
        mgr = AutoCheckpointManager(config=cfg)
        cp = mgr.check_and_save(iteration=1, force=True)
        assert cp is not None
        assert cp.iteration == 1

    def test_force_creates_checkpoint_immediately(self) -> None:
        cfg = CheckpointConfig(interval_seconds=9999)
        mgr = AutoCheckpointManager(config=cfg)
        # First force
        cp1 = mgr.check_and_save(iteration=1, force=True)
        # Second force right after
        cp2 = mgr.check_and_save(iteration=2, force=True)
        assert cp1 is not None
        assert cp2 is not None
        assert mgr.checkpoint_count == 2


class TestOnMilestone:
    """on_milestone triggers checkpoint if enabled."""

    def test_milestone_creates_checkpoint(self) -> None:
        cfg = CheckpointConfig(on_milestone=True)
        mgr = AutoCheckpointManager(config=cfg)
        cp = mgr.on_milestone(iteration=5, description="Task complete")
        assert cp is not None
        assert "Milestone" in cp.description
        assert "Task complete" in cp.description

    def test_milestone_disabled(self) -> None:
        cfg = CheckpointConfig(on_milestone=False)
        mgr = AutoCheckpointManager(config=cfg)
        cp = mgr.on_milestone(iteration=5, description="Task complete")
        assert cp is None


class TestOnToolBatchComplete:
    """on_tool_batch_complete triggers for large batches."""

    def test_tool_batch_large_creates_checkpoint(self) -> None:
        cfg = CheckpointConfig(on_tool_batch=True)
        mgr = AutoCheckpointManager(config=cfg)
        cp = mgr.on_tool_batch_complete(iteration=3, tool_count=5)
        assert cp is not None
        assert "5 tool calls" in cp.description

    def test_tool_batch_small_skips(self) -> None:
        """Batches with < 3 tools don't create a checkpoint."""
        cfg = CheckpointConfig(on_tool_batch=True)
        mgr = AutoCheckpointManager(config=cfg)
        cp = mgr.on_tool_batch_complete(iteration=3, tool_count=2)
        assert cp is None

    def test_tool_batch_disabled(self) -> None:
        cfg = CheckpointConfig(on_tool_batch=False)
        mgr = AutoCheckpointManager(config=cfg)
        cp = mgr.on_tool_batch_complete(iteration=3, tool_count=10)
        assert cp is None

    def test_tool_batch_exactly_three(self) -> None:
        cfg = CheckpointConfig(on_tool_batch=True)
        mgr = AutoCheckpointManager(config=cfg)
        cp = mgr.on_tool_batch_complete(iteration=1, tool_count=3)
        assert cp is not None


class TestMaxCheckpointsEviction:
    """max_checkpoints enforces eviction of oldest checkpoints."""

    def test_evicts_oldest(self) -> None:
        cfg = CheckpointConfig(interval_seconds=0.0, max_checkpoints=3)
        mgr = AutoCheckpointManager(config=cfg)
        for i in range(5):
            mgr.check_and_save(iteration=i, description=f"cp-{i}")
        assert mgr.checkpoint_count == 3
        # The oldest two should have been evicted
        descriptions = [cp.description for cp in mgr.checkpoints]
        assert "cp-0" not in " ".join(descriptions)
        assert "cp-1" not in " ".join(descriptions)
        assert any("cp-4" in d for d in descriptions)

    def test_max_one_checkpoint(self) -> None:
        cfg = CheckpointConfig(interval_seconds=0.0, max_checkpoints=1)
        mgr = AutoCheckpointManager(config=cfg)
        mgr.check_and_save(iteration=1, description="first")
        mgr.check_and_save(iteration=2, description="second")
        assert mgr.checkpoint_count == 1
        assert "second" in mgr.last_checkpoint.description  # type: ignore[union-attr]


class TestClear:
    """clear() empties checkpoint history."""

    def test_clear_removes_all(self) -> None:
        cfg = CheckpointConfig(interval_seconds=0.0)
        mgr = AutoCheckpointManager(config=cfg)
        mgr.check_and_save(iteration=1)
        mgr.check_and_save(iteration=2)
        mgr.clear()
        assert mgr.checkpoint_count == 0
        assert mgr.checkpoints == []
        assert mgr.last_checkpoint is None


class TestSetSaver:
    """set_saver allows changing the saver callback after construction."""

    def test_set_saver_used_on_next_save(self) -> None:
        cfg = CheckpointConfig(interval_seconds=0.0)
        mgr = AutoCheckpointManager(config=cfg)
        new_saver = MagicMock(return_value="new-id")
        mgr.set_saver(new_saver)
        cp = mgr.check_and_save(iteration=1, description="x")
        new_saver.assert_called_once()
        assert cp is not None
        assert cp.id == "new-id"
