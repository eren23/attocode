"""Budget and economics types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class BudgetEnforcementMode(StrEnum):
    """How strictly the budget is enforced."""

    STRICT = "strict"
    SOFT = "soft"
    ADVISORY = "advisory"


class BudgetStatus(StrEnum):
    """Current budget status."""

    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    EXHAUSTED = "exhausted"


@dataclass
class ExecutionBudget:
    """Budget constraints for an agent run."""

    max_tokens: int = 1_000_000
    soft_token_limit: int | None = None
    max_cost: float | None = None
    max_duration_seconds: float | None = None
    max_iterations: int | None = None
    enforcement_mode: BudgetEnforcementMode = BudgetEnforcementMode.STRICT

    @property
    def soft_ratio(self) -> float | None:
        if self.soft_token_limit is not None and self.max_tokens > 0:
            return self.soft_token_limit / self.max_tokens
        return None


@dataclass
class BudgetCheckResult:
    """Result of a budget check."""

    status: BudgetStatus
    token_usage: float = 0.0
    cost_usage: float = 0.0
    duration_usage: float = 0.0
    iteration_usage: float = 0.0
    should_stop: bool = False
    message: str | None = None

    @property
    def is_ok(self) -> bool:
        return self.status == BudgetStatus.OK

    @property
    def max_usage(self) -> float:
        return max(self.token_usage, self.cost_usage, self.duration_usage, self.iteration_usage)


# Preset budgets
QUICK_BUDGET = ExecutionBudget(
    max_tokens=200_000,
    soft_token_limit=160_000,
    max_iterations=20,
)

STANDARD_BUDGET = ExecutionBudget(
    max_tokens=1_000_000,
    soft_token_limit=800_000,
    max_iterations=100,
)

DEEP_BUDGET = ExecutionBudget(
    max_tokens=5_000_000,
    soft_token_limit=4_000_000,
    max_iterations=500,
)

SUBAGENT_BUDGET = ExecutionBudget(
    max_tokens=100_000,
    soft_token_limit=80_000,
    max_iterations=30,
    enforcement_mode=BudgetEnforcementMode.STRICT,
)
