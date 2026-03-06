"""Tests for SubagentSpawner — budget allocation, timeout, closure parsing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from attocode.core.subagent_spawner import (
    ClosureReport,
    SpawnResult,
    SubagentBudget,
    SubagentSpawner,
    get_subagent_budget,
    parse_closure_report,
)
from attocode.types.budget import BudgetEnforcementMode, ExecutionBudget


# ---------------------------------------------------------------------------
# SubagentBudget
# ---------------------------------------------------------------------------
class TestSubagentBudget:
    def test_defaults(self) -> None:
        b = SubagentBudget(
            max_tokens=100_000,
            max_iterations=30,
            max_duration_seconds=300.0,
        )
        assert b.enforcement_mode == BudgetEnforcementMode.STRICT

    def test_to_execution_budget(self) -> None:
        b = SubagentBudget(
            max_tokens=100_000,
            max_iterations=25,
            max_duration_seconds=120.0,
        )
        eb = b.to_execution_budget()
        assert eb.max_tokens == 100_000
        assert eb.soft_token_limit == 80_000  # 80%
        assert eb.max_iterations == 25
        assert eb.max_duration_seconds == 120.0

    def test_to_execution_budget_rounding(self) -> None:
        b = SubagentBudget(max_tokens=99_999, max_iterations=10, max_duration_seconds=60.0)
        eb = b.to_execution_budget()
        assert eb.soft_token_limit == int(99_999 * 0.8)


# ---------------------------------------------------------------------------
# get_subagent_budget
# ---------------------------------------------------------------------------
class TestGetSubagentBudget:
    def test_fraction_of_remaining(self) -> None:
        parent = ExecutionBudget(max_tokens=1_000_000)
        result = get_subagent_budget(parent, parent_tokens_used=200_000, fraction=0.15)
        expected = int(800_000 * 0.15)
        assert result.max_tokens == expected

    def test_min_tokens_floor(self) -> None:
        parent = ExecutionBudget(max_tokens=100_000)
        result = get_subagent_budget(
            parent, parent_tokens_used=99_000, fraction=0.15, min_tokens=50_000
        )
        assert result.max_tokens == 50_000

    def test_max_tokens_ceiling(self) -> None:
        parent = ExecutionBudget(max_tokens=10_000_000)
        result = get_subagent_budget(
            parent, parent_tokens_used=0, fraction=0.5, max_tokens=200_000
        )
        assert result.max_tokens == 200_000

    def test_zero_remaining(self) -> None:
        parent = ExecutionBudget(max_tokens=100_000)
        result = get_subagent_budget(parent, parent_tokens_used=100_000, min_tokens=5_000)
        assert result.max_tokens == 5_000

    def test_over_budget_remaining_negative(self) -> None:
        parent = ExecutionBudget(max_tokens=100_000)
        result = get_subagent_budget(parent, parent_tokens_used=200_000, min_tokens=10_000)
        assert result.max_tokens == 10_000

    def test_custom_max_iterations(self) -> None:
        parent = ExecutionBudget(max_tokens=500_000)
        result = get_subagent_budget(parent, 0, max_iterations=50)
        assert result.max_iterations == 50

    def test_custom_max_duration(self) -> None:
        parent = ExecutionBudget(max_tokens=500_000)
        result = get_subagent_budget(parent, 0, max_duration_seconds=120.0)
        assert result.max_duration_seconds == 120.0


# ---------------------------------------------------------------------------
# parse_closure_report
# ---------------------------------------------------------------------------
class TestParseClosureReport:
    def test_empty_text(self) -> None:
        report = parse_closure_report("")
        assert report.summary == ""
        assert report.files_modified == []

    def test_full_report(self) -> None:
        text = """\
## Summary
Implemented feature X with tests.

## Files Modified
- src/foo.py
- src/bar.py

## Files Created
- src/new.py

## Key Decisions
- Used async pattern

## Remaining Work
- Add docs

## Errors
- Lint warning ignored

## Confidence: 0.85
"""
        report = parse_closure_report(text)
        assert "Implemented feature X" in report.summary
        assert report.files_modified == ["src/foo.py", "src/bar.py"]
        assert report.files_created == ["src/new.py"]
        assert report.key_decisions == ["Used async pattern"]
        assert report.remaining_work == ["Add docs"]
        assert report.errors_encountered == ["Lint warning ignored"]
        assert report.confidence == pytest.approx(0.85)

    def test_summary_only(self) -> None:
        text = "Just a plain text response without headings."
        report = parse_closure_report(text)
        assert report.summary == text

    def test_confidence_clamped_high(self) -> None:
        report = parse_closure_report("## Confidence: 1.5")
        assert report.confidence == 1.0

    def test_confidence_clamped_low(self) -> None:
        report = parse_closure_report("## Confidence: -0.5")
        assert report.confidence == 0.0

    def test_confidence_invalid(self) -> None:
        report = parse_closure_report("## Confidence: not-a-number")
        assert report.confidence == 0.0

    def test_bullet_styles(self) -> None:
        text = """\
## Files Modified
- file1.py
* file2.py
• file3.py
"""
        report = parse_closure_report(text)
        assert len(report.files_modified) == 3

    def test_fallback_summary_first_paragraph(self) -> None:
        text = "First line\nSecond line\n\nAnother paragraph"
        report = parse_closure_report(text)
        assert "First line" in report.summary
        assert "Second line" in report.summary
        assert "Another paragraph" not in report.summary


# ---------------------------------------------------------------------------
# ClosureReport dataclass
# ---------------------------------------------------------------------------
class TestClosureReport:
    def test_defaults(self) -> None:
        r = ClosureReport()
        assert r.summary == ""
        assert r.files_modified == []
        assert r.files_created == []
        assert r.key_decisions == []
        assert r.remaining_work == []
        assert r.errors_encountered == []
        assert r.confidence == 0.0


# ---------------------------------------------------------------------------
# SpawnResult dataclass
# ---------------------------------------------------------------------------
class TestSpawnResult:
    def test_defaults(self) -> None:
        r = SpawnResult(agent_id="sub-abc", success=True)
        assert r.response == ""
        assert r.closure_report is None
        assert r.tokens_used == 0
        assert r.error is None
        assert r.timed_out is False


# ---------------------------------------------------------------------------
# SubagentSpawner
# ---------------------------------------------------------------------------
@dataclass
class _FakeRunResult:
    response: str = "Done"
    success: bool = True
    metrics: Any = None


class TestSubagentSpawner:
    def test_active_count_starts_zero(self) -> None:
        spawner = SubagentSpawner()
        assert spawner.active_count == 0

    def test_update_parent_usage(self) -> None:
        spawner = SubagentSpawner()
        spawner.update_parent_usage(50_000)
        assert spawner._parent_tokens_used == 50_000

    @pytest.mark.asyncio
    async def test_spawn_success(self) -> None:
        async def run_fn(budget: ExecutionBudget, agent_id: str) -> _FakeRunResult:
            return _FakeRunResult(response="## Summary\nAll done.")

        spawner = SubagentSpawner(
            parent_budget=ExecutionBudget(max_tokens=500_000),
            hard_timeout_seconds=10.0,
        )
        result = await spawner.spawn(run_fn, task_description="test task")
        assert result.success
        assert "sub-" in result.agent_id
        assert result.closure_report is not None
        assert "All done" in result.closure_report.summary
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_spawn_timeout(self) -> None:
        async def slow_fn(budget: ExecutionBudget, agent_id: str) -> _FakeRunResult:
            await asyncio.sleep(100)
            return _FakeRunResult()

        spawner = SubagentSpawner(
            parent_budget=ExecutionBudget(max_tokens=500_000),
            hard_timeout_seconds=0.1,
            wrapup_warning_seconds=0.05,
        )
        result = await spawner.spawn(slow_fn, timeout=0.1)
        assert not result.success
        assert result.timed_out
        assert "timed out" in (result.error or "").lower()
        assert spawner.active_count == 0

    @pytest.mark.asyncio
    async def test_spawn_exception(self) -> None:
        async def failing_fn(budget: ExecutionBudget, agent_id: str) -> _FakeRunResult:
            raise ValueError("something broke")

        spawner = SubagentSpawner(
            parent_budget=ExecutionBudget(max_tokens=500_000),
        )
        result = await spawner.spawn(failing_fn)
        assert not result.success
        assert "something broke" in (result.error or "")
        assert spawner.active_count == 0

    @pytest.mark.asyncio
    async def test_spawn_emits_events(self) -> None:
        events: list[str] = []

        def emit(event_type: Any, **kwargs: Any) -> None:
            events.append(str(event_type))

        async def run_fn(budget: ExecutionBudget, agent_id: str) -> _FakeRunResult:
            return _FakeRunResult()

        spawner = SubagentSpawner(
            parent_budget=ExecutionBudget(max_tokens=500_000),
            emit_event=emit,
        )
        await spawner.spawn(run_fn)
        assert any("spawn" in e for e in events)
        assert any("complete" in e for e in events)

    @pytest.mark.asyncio
    async def test_spawn_emits_timeout_event(self) -> None:
        events: list[str] = []

        def emit(event_type: Any, **kwargs: Any) -> None:
            events.append(str(event_type))

        async def slow_fn(budget: ExecutionBudget, agent_id: str) -> _FakeRunResult:
            await asyncio.sleep(100)
            return _FakeRunResult()

        spawner = SubagentSpawner(
            parent_budget=ExecutionBudget(max_tokens=500_000),
            emit_event=emit,
            hard_timeout_seconds=0.1,
        )
        await spawner.spawn(slow_fn, timeout=0.1)
        assert any("hard_kill" in e for e in events)

    @pytest.mark.asyncio
    async def test_spawn_emits_error_event(self) -> None:
        events: list[str] = []

        def emit(event_type: Any, **kwargs: Any) -> None:
            events.append(str(event_type))

        async def fail_fn(budget: ExecutionBudget, agent_id: str) -> _FakeRunResult:
            raise RuntimeError("boom")

        spawner = SubagentSpawner(
            parent_budget=ExecutionBudget(max_tokens=500_000),
            emit_event=emit,
        )
        await spawner.spawn(fail_fn)
        assert any("error" in e for e in events)

    @pytest.mark.asyncio
    async def test_cancel_all(self) -> None:
        started = asyncio.Event()

        async def long_fn(budget: ExecutionBudget, agent_id: str) -> _FakeRunResult:
            started.set()
            await asyncio.sleep(100)
            return _FakeRunResult()

        spawner = SubagentSpawner(
            parent_budget=ExecutionBudget(max_tokens=500_000),
            hard_timeout_seconds=10.0,
        )

        # Start in background
        task = asyncio.create_task(spawner.spawn(long_fn))
        await started.wait()
        assert spawner.active_count == 1

        await spawner.cancel_all()
        assert spawner.active_count == 0

        # CancelledError is BaseException, propagates out of spawn()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_budget_fraction_respected(self) -> None:
        budget_received: list[ExecutionBudget] = []

        async def capture_fn(budget: ExecutionBudget, agent_id: str) -> _FakeRunResult:
            budget_received.append(budget)
            return _FakeRunResult()

        spawner = SubagentSpawner(
            parent_budget=ExecutionBudget(max_tokens=1_000_000),
            parent_tokens_used=200_000,
        )
        await spawner.spawn(capture_fn, budget_fraction=0.25)

        assert len(budget_received) == 1
        # 25% of 800k remaining = 200k
        assert budget_received[0].max_tokens == 200_000

    @pytest.mark.asyncio
    async def test_agent_id_format(self) -> None:
        agent_ids: list[str] = []

        async def run_fn(budget: ExecutionBudget, agent_id: str) -> _FakeRunResult:
            agent_ids.append(agent_id)
            return _FakeRunResult()

        spawner = SubagentSpawner(
            parent_budget=ExecutionBudget(max_tokens=500_000),
        )
        result = await spawner.spawn(run_fn)
        assert result.agent_id.startswith("sub-")
        assert len(result.agent_id) == 12  # "sub-" + 8 hex chars
        assert agent_ids[0] == result.agent_id

    @pytest.mark.asyncio
    async def test_metrics_extraction(self) -> None:
        @dataclass
        class FakeMetrics:
            total_tokens: int = 42_000

        async def run_fn(budget: ExecutionBudget, agent_id: str) -> _FakeRunResult:
            return _FakeRunResult(metrics=FakeMetrics())

        spawner = SubagentSpawner(
            parent_budget=ExecutionBudget(max_tokens=500_000),
        )
        result = await spawner.spawn(run_fn)
        assert result.tokens_used == 42_000
