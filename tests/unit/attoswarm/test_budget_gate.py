"""Tests for BudgetGate."""

from __future__ import annotations

from attoswarm.coordinator.aot_graph import AoTGraph, AoTNode
from attoswarm.coordinator.budget import BudgetCounter
from attoswarm.coordinator.budget_gate import BudgetGate


class TestBudgetGate:
    def test_allows_when_within_budget(self) -> None:
        budget = BudgetCounter(max_tokens=1000, max_cost_usd=10.0)
        gate = BudgetGate(budget)
        decision = gate.can_dispatch("t1", estimated_cost=1.0)
        assert decision.allowed
        assert decision.reason == "within budget"

    def test_blocks_when_exceeded(self) -> None:
        budget = BudgetCounter(max_tokens=1000, max_cost_usd=10.0)
        budget.used_cost_usd = 10.0
        gate = BudgetGate(budget)
        decision = gate.can_dispatch("t1")
        assert not decision.allowed

    def test_blocks_at_shutdown_threshold(self) -> None:
        budget = BudgetCounter(max_tokens=1000, max_cost_usd=10.0)
        budget.used_cost_usd = 9.6  # 96%
        gate = BudgetGate(budget, shutdown_threshold=0.95)
        decision = gate.can_dispatch("t1")
        assert not decision.allowed
        assert "shutdown threshold" in decision.reason

    def test_blocks_estimated_cost_exceeds_remaining(self) -> None:
        budget = BudgetCounter(max_tokens=1000, max_cost_usd=10.0)
        budget.used_cost_usd = 9.0
        gate = BudgetGate(budget)
        decision = gate.can_dispatch("t1", estimated_cost=2.0)
        assert not decision.allowed

    def test_no_budget_limit(self) -> None:
        budget = BudgetCounter(max_tokens=1000, max_cost_usd=0.0)
        gate = BudgetGate(budget)
        decision = gate.can_dispatch("t1")
        assert decision.allowed

    def test_prioritize_critical_path(self) -> None:
        budget = BudgetCounter(max_tokens=1000, max_cost_usd=10.0)
        budget.used_cost_usd = 8.5  # 85% — tight budget

        graph = AoTGraph()
        graph.add_task(AoTNode(task_id="t1"))
        graph.add_task(AoTNode(task_id="t2", depends_on=["t1"]))
        graph.add_task(AoTNode(task_id="t3"))
        graph.compute_levels()

        gate = BudgetGate(budget, aot_graph=graph)
        result = gate.prioritize_remaining(["t3", "t1"])
        # t1 is on critical path, should be first
        assert result[0] == "t1"

    def test_no_reorder_when_budget_ok(self) -> None:
        budget = BudgetCounter(max_tokens=1000, max_cost_usd=10.0)
        budget.used_cost_usd = 2.0  # 20% — fine
        gate = BudgetGate(budget)
        result = gate.prioritize_remaining(["t3", "t1", "t2"])
        assert result == ["t3", "t1", "t2"]
