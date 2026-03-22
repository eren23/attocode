"""Tests for the swarm event bridge — new handlers, state tracking, performance."""

from __future__ import annotations

import json
import os
import time
from io import StringIO
from typing import Any
from unittest.mock import patch

import pytest

from attocode.integrations.swarm.event_bridge import SwarmEventBridge
from attocode.integrations.swarm.types import (
    SwarmEvent,
    SwarmPhase,
    SwarmStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(event_type: str, **data: Any) -> SwarmEvent:
    return SwarmEvent(type=event_type, data=data)


def _make_bridge(tmp_path) -> SwarmEventBridge:
    bridge = SwarmEventBridge(output_dir=str(tmp_path))
    bridge._ensure_output_dir()
    events_path = os.path.join(str(tmp_path), "events.jsonl")
    bridge._events_file = open(events_path, "a", encoding="utf-8")  # noqa: SIM115
    bridge._last_status = SwarmStatus(phase=SwarmPhase.EXECUTING)
    return bridge


# =============================================================================
# Circuit Breaker
# =============================================================================


class TestCircuitBreaker:
    def test_open_sets_state(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.circuit.open", pause_ms=5000, rate_limit_count=3))
        assert bridge._circuit_breaker_open is True
        assert bridge._circuit_breaker_pause_until is not None
        assert bridge._rate_limit_count == 3

    def test_closed_clears_state(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.circuit.open", pause_ms=5000))
        bridge._handle_event(_event("swarm.circuit.closed"))
        assert bridge._circuit_breaker_open is False
        assert bridge._circuit_breaker_pause_until is None

    def test_appears_in_state_dict(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.circuit.open", pause_ms=10000, rate_limit_count=2))
        state = bridge._build_state_dict()
        cb = state["circuit_breaker"]
        assert cb["open"] is True
        assert cb["rate_limit_count"] == 2
        assert cb["pause_until"] is not None

    def test_circuit_in_timeline(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.circuit.open", pause_ms=3000))
        assert any(e["type"] == "swarm.circuit.open" for e in bridge._timeline)


# =============================================================================
# Pause / Resume
# =============================================================================


class TestPauseResume:
    def test_pause_sets_state(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.paused", reason="user_requested"))
        assert bridge._paused is True
        assert bridge._pause_reason == "user_requested"

    def test_resume_clears_state(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.paused", reason="rate_limit"))
        bridge._handle_event(_event("swarm.resumed"))
        assert bridge._paused is False
        assert bridge._pause_reason is None

    def test_pause_in_state_dict(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.paused", reason="test"))
        state = bridge._build_state_dict()
        assert state["paused"] is True
        assert state["pause_reason"] == "test"
        assert state["status"]["paused"] is True

    def test_resume_in_state_dict(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.paused", reason="x"))
        bridge._handle_event(_event("swarm.resumed"))
        state = bridge._build_state_dict()
        assert state["paused"] is False


# =============================================================================
# Wave Tracking
# =============================================================================


class TestWaveTracking:
    def test_wave_start_appends(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.wave.start", wave=0, task_count=5))
        assert len(bridge._waves) == 1
        assert bridge._waves[0]["wave"] == 0
        assert bridge._waves[0]["task_count"] == 5
        assert bridge._waves[0]["completed_at"] is None

    def test_wave_complete_updates(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.wave.start", wave=0, task_count=3))
        bridge._handle_event(_event("swarm.wave.complete", wave=0, passed=2, failed=1))
        assert bridge._waves[0]["completed_at"] is not None
        assert bridge._waves[0]["passed"] == 2
        assert bridge._waves[0]["failed"] == 1

    def test_multiple_waves(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.wave.start", wave=0, task_count=3))
        bridge._handle_event(_event("swarm.wave.complete", wave=0, passed=3))
        bridge._handle_event(_event("swarm.wave.start", wave=1, task_count=2))
        assert len(bridge._waves) == 2

    def test_waves_in_state_dict(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.wave.start", wave=0, task_count=4))
        state = bridge._build_state_dict()
        assert len(state["waves"]) == 1

    def test_wave_all_failed(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.wave.start", wave=0, task_count=3))
        bridge._handle_event(_event("swarm.wave.allFailed", wave=0, failed=3))
        assert bridge._waves[0]["failed"] == 3


# =============================================================================
# Verification Tracking
# =============================================================================


class TestVerificationTracking:
    def test_verification_failed_appends(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        checks = [{"name": "tests", "passed": False, "message": "2 failed"}]
        bridge._handle_event(_event("swarm.verification.failed", task_id="t1", checks=checks))
        assert len(bridge._verification_results) == 1
        assert bridge._verification_results[0]["task_id"] == "t1"
        assert bridge._verification_results[0]["passed"] is False

    def test_verification_capped_at_100(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        for i in range(110):
            bridge._handle_event(_event("swarm.verification.failed", task_id=f"t{i}", checks=[]))
        assert len(bridge._verification_results) == 100

    def test_verification_in_state_dict(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.verification.failed", task_id="t1", checks=[]))
        state = bridge._build_state_dict()
        assert len(state["verification_results"]) == 1


# =============================================================================
# File Conflicts
# =============================================================================


class TestFileConflicts:
    def test_file_conflict_appends(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.file_conflict", task_id="t1", conflicting_files=["a.py"]))
        assert len(bridge._file_conflicts) == 1
        assert bridge._file_conflicts[0]["files"] == ["a.py"]

    def test_file_conflicts_capped_at_50(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        for i in range(60):
            bridge._handle_event(_event("swarm.file_conflict", task_id=f"t{i}", conflicting_files=[]))
        assert len(bridge._file_conflicts) == 50

    def test_file_conflicts_in_state_dict(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event("swarm.file_conflict", task_id="t1", conflicting_files=["b.py"]))
        state = bridge._build_state_dict()
        assert len(state["file_conflicts"]) == 1


# =============================================================================
# Batched Event File Flushes
# =============================================================================


class TestBatchedFlush:
    def test_no_flush_under_threshold(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._last_flush = time.monotonic()  # reset
        for i in range(5):
            bridge._append_event_to_file(SwarmEvent(type="test", data={"i": i}))
        assert bridge._events_unflushed == 5  # not flushed yet

    def test_flush_at_threshold(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._last_flush = time.monotonic()
        for i in range(20):
            bridge._append_event_to_file(SwarmEvent(type="test", data={"i": i}))
        assert bridge._events_unflushed == 0  # flushed at 20

    def test_flush_after_time_gap(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._last_flush = time.monotonic() - 1.0  # 1s ago
        bridge._append_event_to_file(SwarmEvent(type="test", data={}))
        assert bridge._events_unflushed == 0  # flushed due to time


# =============================================================================
# Batched Task Detail Writes
# =============================================================================


class TestBatchedTaskWrites:
    def test_mark_dirty_writes_immediately_without_event_loop(self, tmp_path) -> None:
        """Without a running event loop, _mark_task_dirty flushes synchronously."""
        bridge = _make_bridge(tmp_path)
        from attocode.integrations.swarm.types import SwarmTask
        bridge._tasks["t1"] = SwarmTask(id="t1", description="test task")
        bridge._mark_task_dirty("t1", {"status": "completed"})
        # Without event loop, flush happens immediately
        assert len(bridge._dirty_tasks) == 0
        task_file = os.path.join(str(tmp_path), "tasks", "t1.json")
        assert os.path.isfile(task_file)

    @pytest.mark.asyncio
    async def test_mark_dirty_defers_with_event_loop(self, tmp_path) -> None:
        """With a running event loop, _mark_task_dirty defers the write."""
        bridge = _make_bridge(tmp_path)
        from attocode.integrations.swarm.types import SwarmTask
        bridge._tasks["t1"] = SwarmTask(id="t1", description="test task")
        bridge._mark_task_dirty("t1", {"status": "completed"})
        # With event loop, dirty tasks are deferred
        assert "t1" in bridge._dirty_tasks
        # Manually flush
        bridge._flush_dirty_tasks()
        assert len(bridge._dirty_tasks) == 0
        task_file = os.path.join(str(tmp_path), "tasks", "t1.json")
        assert os.path.isfile(task_file)

    def test_flush_writes_and_clears(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        from attocode.integrations.swarm.types import SwarmTask
        bridge._tasks["t1"] = SwarmTask(id="t1", description="test task")
        # Directly populate dirty_tasks (bypassing _mark_task_dirty)
        bridge._dirty_tasks["t1"] = {"status": "completed"}
        bridge._flush_dirty_tasks()
        assert len(bridge._dirty_tasks) == 0
        task_file = os.path.join(str(tmp_path), "tasks", "t1.json")
        assert os.path.isfile(task_file)

    def test_close_flushes_pending(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        from attocode.integrations.swarm.types import SwarmTask
        bridge._tasks["t1"] = SwarmTask(id="t1", description="test")
        # Directly populate dirty_tasks
        bridge._dirty_tasks["t1"] = {"status": "done"}
        assert len(bridge._dirty_tasks) == 1
        bridge.close()
        assert len(bridge._dirty_tasks) == 0


# =============================================================================
# Quality Results Eviction
# =============================================================================


class TestQualityResultsEviction:
    def test_evicts_when_over_100(self, tmp_path) -> None:
        bridge = _make_bridge(tmp_path)
        for i in range(110):
            bridge._handle_event(_event("swarm.quality.result", task_id=f"t{i}", score=3, passed=True))
        assert len(bridge._quality_results) <= 100


# =============================================================================
# Event Routing (new types don't fall to catch-all)
# =============================================================================


class TestEventRouting:
    @pytest.mark.parametrize("event_type", [
        "swarm.circuit.open",
        "swarm.circuit.closed",
        "swarm.paused",
        "swarm.resumed",
        "swarm.wave.start",
        "swarm.wave.complete",
        "swarm.wave.allFailed",
        "swarm.verification.failed",
        "swarm.verification.skipped",
        "swarm.file_conflict",
        "swarm.task.decomposed",
        "swarm.replan",
        "swarm.rescue.final",
        "swarm.task.stale_recovered",
    ])
    def test_known_event_reaches_timeline(self, tmp_path, event_type: str) -> None:
        bridge = _make_bridge(tmp_path)
        bridge._handle_event(_event(event_type))
        assert any(e["type"] == event_type for e in bridge._timeline)
