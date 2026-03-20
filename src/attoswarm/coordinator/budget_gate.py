"""Pre-dispatch budget validation gate.

Validates that the budget allows dispatching a task before it is sent
to a worker.  When budget is tight, prioritizes critical-path tasks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attoswarm.coordinator.aot_graph import AoTGraph
    from attoswarm.coordinator.budget import BudgetCounter, BudgetProjector

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BudgetDecision:
    """Result of a budget gate check."""

    allowed: bool
    reason: str
    remaining_budget: float = 0.0
    estimated_cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "remaining_budget": round(self.remaining_budget, 4),
            "estimated_cost": round(self.estimated_cost, 4),
        }


class BudgetGate:
    """Pre-dispatch budget validator.

    Usage::

        gate = BudgetGate(budget, projector, aot_graph)
        decision = gate.can_dispatch("task-1", estimated_cost=0.5)
        if not decision.allowed:
            skip(task)
        prioritized = gate.prioritize_remaining(ready_tasks)
    """

    def __init__(
        self,
        budget: BudgetCounter,
        projector: BudgetProjector | None = None,
        aot_graph: AoTGraph | None = None,
        shutdown_threshold: float = 0.95,
    ) -> None:
        self._budget = budget
        self._projector = projector
        self._aot_graph = aot_graph
        self._shutdown_threshold = shutdown_threshold

    def can_dispatch(
        self,
        task_id: str,
        estimated_cost: float = 0.0,
    ) -> BudgetDecision:
        """Check whether the budget allows dispatching a task.

        Args:
            task_id: Task identifier (for logging).
            estimated_cost: Estimated cost from EWMA.  If 0, uses remaining
                budget heuristic.

        Returns:
            BudgetDecision with allowed/reason.
        """
        max_cost = self._budget.max_cost_usd
        if max_cost <= 0:
            return BudgetDecision(allowed=True, reason="no budget limit")

        used = self._budget.used_cost_usd
        remaining = max(max_cost - used, 0.0)
        usage_fraction = used / max_cost

        # Hard limit: already exceeded
        if self._budget.hard_exceeded():
            return BudgetDecision(
                allowed=False,
                reason="budget hard limit exceeded",
                remaining_budget=remaining,
                estimated_cost=estimated_cost,
            )

        # Shutdown threshold: stop dispatch entirely
        if usage_fraction >= self._shutdown_threshold:
            return BudgetDecision(
                allowed=False,
                reason=f"budget at {usage_fraction:.0%} (>= {self._shutdown_threshold:.0%} shutdown threshold)",
                remaining_budget=remaining,
                estimated_cost=estimated_cost,
            )

        # If we have an estimate, check if it fits
        if estimated_cost > 0 and estimated_cost > remaining:
            return BudgetDecision(
                allowed=False,
                reason=f"estimated cost ${estimated_cost:.3f} exceeds remaining ${remaining:.3f}",
                remaining_budget=remaining,
                estimated_cost=estimated_cost,
            )

        return BudgetDecision(
            allowed=True,
            reason="within budget",
            remaining_budget=remaining,
            estimated_cost=estimated_cost,
        )

    def estimated_task_cost(self) -> float:
        """Return the EWMA estimated cost per task, or 0 if unknown."""
        if self._projector and hasattr(self._projector, "_ewma") and self._projector._ewma is not None:
            return self._projector._ewma
        return 0.0

    def prioritize_remaining(self, ready_task_ids: list[str]) -> list[str]:
        """When budget is tight, prioritize critical-path tasks.

        Returns the task IDs in priority order (most important first).
        Non-critical-path tasks are appended after critical-path ones.
        """
        if not self._aot_graph or not ready_task_ids:
            return list(ready_task_ids)

        max_cost = self._budget.max_cost_usd
        if max_cost <= 0:
            return list(ready_task_ids)

        usage_fraction = self._budget.used_cost_usd / max_cost
        if usage_fraction < 0.80:
            # Budget is fine — no reordering needed
            return list(ready_task_ids)

        # Get critical path and prioritize tasks on it
        critical_path = set(self._aot_graph.get_critical_path())
        on_cp = [tid for tid in ready_task_ids if tid in critical_path]
        off_cp = [tid for tid in ready_task_ids if tid not in critical_path]

        return on_cp + off_cp
