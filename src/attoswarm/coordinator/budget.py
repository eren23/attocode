"""Budget accounting with native + fallback token estimation and projection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BudgetCounter:
    max_tokens: int
    max_cost_usd: float
    chars_per_token: float = 4.0
    used_tokens: int = 0
    used_cost_usd: float = 0.0

    def add_usage(self, token_usage: dict[str, int] | None, cost_usd: float | None, text: str = "") -> None:
        if token_usage and "total" in token_usage:
            self.used_tokens += max(int(token_usage["total"]), 0)
        elif text:
            self.used_tokens += max(int(len(text) / max(self.chars_per_token, 1.0)), 1)
        if cost_usd is not None:
            self.used_cost_usd += max(cost_usd, 0.0)

    def hard_exceeded(self) -> bool:
        return self.used_tokens >= self.max_tokens or self.used_cost_usd >= self.max_cost_usd

    def as_dict(self) -> dict[str, float | int]:
        return {
            "tokens_used": self.used_tokens,
            "tokens_max": self.max_tokens,
            "cost_used_usd": round(self.used_cost_usd, 6),
            "cost_max_usd": self.max_cost_usd,
        }


@dataclass(slots=True)
class BudgetProjection:
    """Projected budget usage based on EWMA of per-task costs."""

    usage_fraction: float
    avg_cost_per_task: float
    projected_total_cost: float
    will_exceed: bool
    estimated_completable: int
    warning_level: str  # ok|caution|warning|critical|shutdown
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "usage_fraction": round(self.usage_fraction, 4),
            "avg_cost_per_task": round(self.avg_cost_per_task, 6),
            "projected_total_cost": round(self.projected_total_cost, 4),
            "will_exceed": self.will_exceed,
            "estimated_completable": self.estimated_completable,
            "warning_level": self.warning_level,
            "message": self.message,
        }


class BudgetProjector:
    """Projects budget usage using EWMA of per-task costs.

    Warning levels:
    - ok:       <60% used
    - caution:  60-80%
    - warning:  80-90%
    - critical: 90-95%
    - shutdown: >95%
    """

    def __init__(self, ewma_alpha: float = 0.3) -> None:
        self._alpha = ewma_alpha
        self._ewma: float | None = None

    def project(
        self,
        used_cost: float,
        max_cost: float,
        completed_tasks: int,
        total_tasks: int,
        per_task_costs: list[float],
    ) -> BudgetProjection:
        """Project budget usage based on completed task costs.

        Args:
            used_cost: Total cost used so far.
            max_cost: Maximum budget.
            completed_tasks: Number of completed tasks.
            total_tasks: Total number of tasks.
            per_task_costs: List of individual task costs.

        Returns:
            BudgetProjection with warning level and message.
        """
        if max_cost <= 0:
            max_cost = 1.0  # avoid division by zero

        usage_fraction = used_cost / max_cost

        # Compute EWMA of per-task costs
        avg_cost = 0.0
        if per_task_costs:
            # Update EWMA
            for cost in per_task_costs:
                if self._ewma is None:
                    self._ewma = cost
                else:
                    self._ewma = self._alpha * cost + (1.0 - self._alpha) * self._ewma
            avg_cost = self._ewma or 0.0
        elif completed_tasks > 0:
            avg_cost = used_cost / completed_tasks

        # Project total cost
        remaining_tasks = max(total_tasks - completed_tasks, 0)
        projected_total = used_cost + avg_cost * remaining_tasks
        will_exceed = projected_total > max_cost

        # Estimate how many more tasks we can complete
        remaining_budget = max(max_cost - used_cost, 0.0)
        estimated_completable = int(remaining_budget / avg_cost) if avg_cost > 0 else remaining_tasks

        # Determine warning level
        if usage_fraction >= 0.95:
            level = "shutdown"
        elif usage_fraction >= 0.90:
            level = "critical"
        elif usage_fraction >= 0.80:
            level = "warning"
        elif usage_fraction >= 0.60:
            level = "caution"
        else:
            level = "ok"

        # Build message
        pct = int(usage_fraction * 100)
        msg_parts = [f"Budget {pct}% used (${used_cost:.2f}/${max_cost:.2f})"]
        if avg_cost > 0:
            msg_parts.append(f"avg ${avg_cost:.3f}/task")
        if will_exceed:
            msg_parts.append(f"PROJECTED OVERSHOOT: ${projected_total:.2f}")
        if estimated_completable < remaining_tasks:
            msg_parts.append(f"can complete ~{estimated_completable}/{remaining_tasks} remaining")
        message = " | ".join(msg_parts)

        return BudgetProjection(
            usage_fraction=usage_fraction,
            avg_cost_per_task=avg_cost,
            projected_total_cost=projected_total,
            will_exceed=will_exceed,
            estimated_completable=estimated_completable,
            warning_level=level,
            message=message,
        )
