"""Pre-dispatch budget validation gate.

Validates that the budget allows dispatching a task before it is sent
to a worker.  When budget is tight, prioritizes critical-path tasks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
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


@dataclass(slots=True)
class TaskProgressWindow:
    """Sliding window of per-turn progress metrics for a single task."""

    turn_deltas: list[int] = field(default_factory=list)
    tool_calls_per_turn: list[int] = field(default_factory=list)
    files_touched_per_turn: list[int] = field(default_factory=list)


class DiminishingReturnsTracker:
    """Detects tasks that produce decreasing value per LLM turn.

    A task is considered "diminishing" when the last N turns each produced
    fewer than ``delta_threshold`` output tokens and zero tool calls.
    This indicates the agent is stuck in a loop of producing low-value text.
    """

    def __init__(
        self,
        *,
        min_turns: int = 3,
        delta_threshold: int = 500,
        max_window: int = 20,
    ) -> None:
        self._windows: dict[str, TaskProgressWindow] = {}
        self._min_turns = min_turns
        self._delta_threshold = delta_threshold
        self._max_window = max_window

    def record_turn(
        self,
        task_id: str,
        tokens_delta: int,
        tool_calls: int,
        files_touched: int,
    ) -> None:
        """Record metrics from a single agent turn."""
        if task_id not in self._windows:
            self._windows[task_id] = TaskProgressWindow()
        window = self._windows[task_id]
        window.turn_deltas.append(tokens_delta)
        window.tool_calls_per_turn.append(tool_calls)
        window.files_touched_per_turn.append(files_touched)
        # Trim to max window size
        if len(window.turn_deltas) > self._max_window:
            window.turn_deltas = window.turn_deltas[-self._max_window :]
            window.tool_calls_per_turn = window.tool_calls_per_turn[-self._max_window :]
            window.files_touched_per_turn = window.files_touched_per_turn[-self._max_window :]

    def is_diminishing(self, task_id: str) -> bool:
        """Check if a task shows diminishing returns."""
        window = self._windows.get(task_id)
        if not window or len(window.turn_deltas) < self._min_turns:
            return False
        recent_deltas = window.turn_deltas[-self._min_turns :]
        recent_tools = window.tool_calls_per_turn[-self._min_turns :]
        return all(d < self._delta_threshold for d in recent_deltas) and all(
            t == 0 for t in recent_tools
        )

    def clear_task(self, task_id: str) -> None:
        """Remove tracking for a completed/failed task."""
        self._windows.pop(task_id, None)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for state persistence."""
        return {
            task_id: {
                "turn_deltas": w.turn_deltas,
                "tool_calls": w.tool_calls_per_turn,
                "files_touched": w.files_touched_per_turn,
            }
            for task_id, w in self._windows.items()
        }
