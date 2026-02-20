"""Tests for execution economics manager."""

from __future__ import annotations

import time

import pytest

from attocode.integrations.budget.economics import (
    BudgetCheck,
    ExecutionEconomicsManager,
    UsageSnapshot,
)
from attocode.types.budget import BudgetEnforcementMode, BudgetStatus, ExecutionBudget


class TestExecutionEconomicsBasic:
    def test_initial_state(self) -> None:
        em = ExecutionEconomicsManager()
        assert em.total_tokens == 0
        assert em.estimated_cost == 0.0
        assert em.llm_calls == 0
        assert em.usage_fraction == 0.0

    def test_record_llm_usage(self) -> None:
        em = ExecutionEconomicsManager()
        em.record_llm_usage(100, 50, cost=0.001)
        assert em.total_tokens == 150
        assert em.llm_calls == 1
        assert em.estimated_cost == pytest.approx(0.001)

    def test_cumulative_usage(self) -> None:
        em = ExecutionEconomicsManager()
        em.record_llm_usage(100, 50)
        em.record_llm_usage(200, 100)
        assert em.total_tokens == 450
        assert em.llm_calls == 2

    def test_record_tool_call(self) -> None:
        em = ExecutionEconomicsManager()
        loop_det, nudge = em.record_tool_call("read_file", {"path": "a.py"}, iteration=1)
        assert not loop_det.is_loop
        assert nudge is None

    def test_usage_fraction(self) -> None:
        em = ExecutionEconomicsManager(budget=ExecutionBudget(max_tokens=1000))
        em.record_llm_usage(300, 200)
        assert em.usage_fraction == pytest.approx(0.5)


class TestBudgetChecks:
    def test_ok_budget(self) -> None:
        em = ExecutionEconomicsManager(budget=ExecutionBudget(max_tokens=10000))
        em.record_llm_usage(100, 50)
        check = em.check_budget()
        assert check.can_continue
        assert check.status == BudgetStatus.OK

    def test_warning_budget(self) -> None:
        em = ExecutionEconomicsManager(budget=ExecutionBudget(max_tokens=1000))
        em.record_llm_usage(400, 450)  # 850/1000 = 85% > soft_ratio
        check = em.check_budget()
        assert check.can_continue
        assert check.status == BudgetStatus.WARNING
        assert check.injected_prompt != ""

    def test_exhausted_budget(self) -> None:
        em = ExecutionEconomicsManager(budget=ExecutionBudget(max_tokens=1000))
        em.record_llm_usage(500, 600)  # 1100/1000 > 100%
        check = em.check_budget()
        assert not check.can_continue
        assert check.status == BudgetStatus.EXHAUSTED
        assert check.budget_type == "tokens"

    def test_iteration_limit(self) -> None:
        em = ExecutionEconomicsManager(budget=ExecutionBudget(max_iterations=5))
        for _ in range(5):
            em.record_llm_usage(10, 5)
        check = em.check_budget()
        assert not check.can_continue
        assert check.budget_type == "iterations"

    def test_no_limit(self) -> None:
        em = ExecutionEconomicsManager(budget=ExecutionBudget(max_tokens=0, max_iterations=0))
        em.record_llm_usage(999999, 999999)
        check = em.check_budget()
        assert check.can_continue

    def test_force_text_only_near_limit(self) -> None:
        em = ExecutionEconomicsManager(
            budget=ExecutionBudget(max_tokens=1000),
            enforcement_mode=BudgetEnforcementMode.STRICT,
        )
        em.record_llm_usage(475, 480)  # 955/1000 = 95.5%
        check = em.check_budget()
        assert check.force_text_only


class TestBaseline:
    def test_set_baseline(self) -> None:
        em = ExecutionEconomicsManager()
        em.record_llm_usage(100, 50)
        em.set_baseline()
        assert em.incremental_tokens == 0

    def test_incremental_after_baseline(self) -> None:
        em = ExecutionEconomicsManager()
        em.record_llm_usage(100, 50)
        em.set_baseline()
        em.record_llm_usage(200, 100)
        assert em.incremental_tokens == 300

    def test_update_baseline(self) -> None:
        em = ExecutionEconomicsManager()
        em.record_llm_usage(1000, 500)
        em.set_baseline()
        em.record_llm_usage(200, 100)
        em.update_baseline(500)  # After compaction
        assert em.incremental_tokens == em.total_tokens - 500

    def test_no_baseline_returns_total(self) -> None:
        em = ExecutionEconomicsManager()
        em.record_llm_usage(100, 50)
        assert em.incremental_tokens == 150


class TestDurationTracking:
    def test_elapsed_seconds(self) -> None:
        em = ExecutionEconomicsManager()
        time.sleep(0.05)
        assert em.elapsed_seconds >= 0.04

    def test_pause_resume(self) -> None:
        em = ExecutionEconomicsManager()
        em.pause_duration()
        time.sleep(0.05)
        em.resume_duration()
        # Paused time should be excluded
        assert em.elapsed_seconds < 0.05


class TestSnapshot:
    def test_get_snapshot(self) -> None:
        em = ExecutionEconomicsManager()
        em.record_llm_usage(100, 50, cost=0.001)
        snap = em.get_snapshot()
        assert snap.total_tokens == 150
        assert snap.estimated_cost == pytest.approx(0.001)
        assert snap.timestamp > 0


class TestReset:
    def test_reset(self) -> None:
        em = ExecutionEconomicsManager()
        em.record_llm_usage(100, 50)
        em.record_tool_call("read_file", {})
        em.set_baseline()
        em.reset()
        assert em.total_tokens == 0
        assert em.llm_calls == 0
        assert em.loop_detector.total_calls == 0
