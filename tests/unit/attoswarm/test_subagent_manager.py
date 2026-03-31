"""Tests for attoswarm.coordinator.subagent_manager timeout tracking fields.

Covers:
- TaskResult dataclass defaults and construction with timeout fields
- _execute_one() behavior on TimeoutError, near-timeout, and zero-token warnings
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import patch

import pytest

from attoswarm.coordinator.subagent_manager import SubagentManager, TaskResult

# ── TaskResult dataclass ──────────────────────────────────────────────


class TestTaskResultDefaults:
    def test_timed_out_defaults_false(self) -> None:
        r = TaskResult(task_id="t1", success=True)
        assert r.timed_out is False

    def test_near_timeout_defaults_false(self) -> None:
        r = TaskResult(task_id="t1", success=True)
        assert r.near_timeout is False

    def test_construct_with_timed_out_true(self) -> None:
        r = TaskResult(task_id="t1", success=False, timed_out=True)
        assert r.timed_out is True

    def test_construct_with_near_timeout_true(self) -> None:
        r = TaskResult(task_id="t1", success=True, near_timeout=True)
        assert r.near_timeout is True


# ── Helpers ───────────────────────────────────────────────────────────


def _make_task(task_id: str = "t1", **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "task_id": task_id,
        "description": f"do {task_id}",
        "target_files": [],
    }
    base.update(overrides)
    return base


def _make_manager(spawn_fn: Any) -> SubagentManager:
    return SubagentManager(max_concurrency=2, spawn_fn=spawn_fn)


# ── _execute_one() ────────────────────────────────────────────────────


class TestExecuteOneTimeout:
    @pytest.mark.asyncio
    async def test_timeout_error_sets_timed_out(self) -> None:
        """When spawn_fn raises TimeoutError, result.timed_out should be True."""

        async def slow_spawn(task: dict[str, Any]) -> TaskResult:
            raise TimeoutError("boom")

        mgr = _make_manager(spawn_fn=slow_spawn)
        result = await mgr._execute_one(_make_task(), timeout=10.0)

        assert result.success is False
        assert result.timed_out is True
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_near_timeout_when_duration_exceeds_90_percent(self) -> None:
        """When the task completes but takes >90% of the timeout, near_timeout is set."""

        async def normal_spawn(task: dict[str, Any]) -> TaskResult:
            return TaskResult(
                task_id=task["task_id"],
                success=True,
                result_summary="ok",
                tokens_used=100,
            )

        mgr = _make_manager(spawn_fn=normal_spawn)

        # Patch time.time so that (end - start) = 9.5s with a 10s timeout (95%)
        call_count = 0
        base_time = 1000.0

        def fake_time() -> float:
            nonlocal call_count
            call_count += 1
            # First call: start timestamp
            # Subsequent calls: simulate 9.5s elapsed
            if call_count <= 1:
                return base_time
            return base_time + 9.5

        with patch("attoswarm.coordinator.subagent_manager.time") as mock_time:
            mock_time.time = fake_time
            result = await mgr._execute_one(_make_task(), timeout=10.0)

        assert result.success is True
        assert result.near_timeout is True
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_no_near_timeout_when_well_within_limit(self) -> None:
        """When the task finishes quickly, near_timeout stays False."""

        async def fast_spawn(task: dict[str, Any]) -> TaskResult:
            return TaskResult(
                task_id=task["task_id"],
                success=True,
                result_summary="ok",
                tokens_used=100,
            )

        mgr = _make_manager(spawn_fn=fast_spawn)

        call_count = 0
        base_time = 1000.0

        def fake_time() -> float:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return base_time
            return base_time + 1.0  # 1s of 10s = 10%

        with patch("attoswarm.coordinator.subagent_manager.time") as mock_time:
            mock_time.time = fake_time
            result = await mgr._execute_one(_make_task(), timeout=10.0)

        assert result.success is True
        assert result.near_timeout is False
        assert result.timed_out is False


class TestExecuteOneZeroTokenWarning:
    @pytest.mark.asyncio
    async def test_zero_tokens_success_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """When spawn_fn returns success=True but tokens_used=0, a warning is logged."""

        async def spawn_no_tokens(task: dict[str, Any]) -> TaskResult:
            return TaskResult(
                task_id=task["task_id"],
                success=True,
                result_summary="done",
                tokens_used=0,
            )

        mgr = _make_manager(spawn_fn=spawn_no_tokens)

        with caplog.at_level(logging.WARNING, logger="attoswarm.coordinator.subagent_manager"):
            result = await mgr._execute_one(_make_task(), timeout=10.0)

        assert result.success is True
        assert result.tokens_used == 0

        # Check that the instrumentation gap warning was logged
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("tokens_used=0" in msg for msg in warning_msgs), (
            f"Expected a warning about tokens_used=0, got: {warning_msgs}"
        )

    @pytest.mark.asyncio
    async def test_nonzero_tokens_success_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """When spawn_fn returns success=True with tokens_used > 0, no zero-token warning."""

        async def spawn_with_tokens(task: dict[str, Any]) -> TaskResult:
            return TaskResult(
                task_id=task["task_id"],
                success=True,
                result_summary="done",
                tokens_used=500,
            )

        mgr = _make_manager(spawn_fn=spawn_with_tokens)

        with caplog.at_level(logging.WARNING, logger="attoswarm.coordinator.subagent_manager"):
            result = await mgr._execute_one(_make_task(), timeout=10.0)

        assert result.success is True
        assert result.tokens_used == 500

        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert not any("tokens_used=0" in msg for msg in warning_msgs), (
            f"Did not expect a tokens_used=0 warning, got: {warning_msgs}"
        )


class TestAgentStatusMetadata:
    @pytest.mark.asyncio
    async def test_backend_is_preserved_across_status_transitions(self) -> None:
        async def spawn_ok(task: dict[str, Any]) -> TaskResult:
            return TaskResult(task_id=task["task_id"], success=True, result_summary="ok")

        mgr = _make_manager(spawn_fn=spawn_ok)
        await mgr._execute_one(
            _make_task(task_id="t-backend", backend="codex", model="gpt-5.3-codex"),
            timeout=10.0,
        )

        status = mgr.get_all_agents()[0]
        assert status.backend == "codex"
        assert status.model == "gpt-5.3-codex"
