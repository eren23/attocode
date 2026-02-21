"""Swarm budget management.

Splits budget between orchestrator and workers, tracks per-worker
spending, and provides global budget oversight for the swarm.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from attocode.types.budget import ExecutionBudget


@dataclass(slots=True)
class SwarmBudgetConfig:
    """Swarm budget configuration."""

    total_max_tokens: int = 5_000_000
    orchestrator_fraction: float = 0.2  # 20% for orchestrator
    worker_fraction: float = 0.8       # 80% for workers
    per_worker_max_tokens: int = 300_000
    reserve_fraction: float = 0.05     # 5% reserve for recovery


@dataclass(slots=True)
class WorkerSpending:
    """Spending record for a single worker."""

    worker_id: str
    tokens_used: int = 0
    cost_used: float = 0.0
    tasks_completed: int = 0
    started_at: float = 0.0


@dataclass(slots=True)
class SwarmBudgetStatus:
    """Current swarm budget status."""

    total_tokens_used: int = 0
    total_tokens_remaining: int = 0
    orchestrator_tokens_used: int = 0
    worker_tokens_used: int = 0
    reserve_tokens: int = 0
    worker_count: int = 0
    can_spawn_worker: bool = True
    usage_fraction: float = 0.0


class SwarmBudget:
    """Manages budget allocation between orchestrator and workers.

    Provides:
    - Split budget between orchestrator and worker pool
    - Per-worker budget tracking and enforcement
    - Reserve budget for recovery operations
    - Global budget status for decision making
    """

    def __init__(self, config: SwarmBudgetConfig | None = None) -> None:
        self._config = config or SwarmBudgetConfig()
        self._orchestrator_tokens = 0
        self._workers: dict[str, WorkerSpending] = {}
        self._reserve_used = 0

        # Calculate allocations
        self._orchestrator_budget = int(
            self._config.total_max_tokens * self._config.orchestrator_fraction
        )
        self._worker_pool_budget = int(
            self._config.total_max_tokens * self._config.worker_fraction
        )
        self._reserve_budget = int(
            self._config.total_max_tokens * self._config.reserve_fraction
        )

    def get_worker_budget(self, worker_id: str) -> ExecutionBudget:
        """Get budget allocation for a worker."""
        remaining = self._worker_pool_budget - self._total_worker_tokens()
        worker_max = min(self._config.per_worker_max_tokens, remaining)

        return ExecutionBudget(
            max_tokens=max(0, worker_max),
            soft_token_limit=int(worker_max * 0.8) if worker_max > 0 else 0,
            max_iterations=50,
        )

    def get_orchestrator_budget(self) -> ExecutionBudget:
        """Get budget allocation for the orchestrator."""
        remaining = self._orchestrator_budget - self._orchestrator_tokens
        return ExecutionBudget(
            max_tokens=max(0, remaining),
            soft_token_limit=int(remaining * 0.8) if remaining > 0 else 0,
            max_iterations=200,
        )

    def record_orchestrator_usage(self, tokens: int) -> None:
        """Record token usage by the orchestrator."""
        self._orchestrator_tokens += tokens

    def record_worker_usage(
        self,
        worker_id: str,
        tokens: int,
        cost: float = 0.0,
    ) -> None:
        """Record token usage by a worker."""
        if worker_id not in self._workers:
            self._workers[worker_id] = WorkerSpending(
                worker_id=worker_id,
                started_at=time.monotonic(),
            )
        self._workers[worker_id].tokens_used += tokens
        self._workers[worker_id].cost_used += cost

    def record_worker_completion(self, worker_id: str) -> None:
        """Record a worker completing a task."""
        if worker_id in self._workers:
            self._workers[worker_id].tasks_completed += 1

    def use_reserve(self, tokens: int) -> bool:
        """Use reserve budget for recovery. Returns True if available."""
        if self._reserve_used + tokens > self._reserve_budget:
            return False
        self._reserve_used += tokens
        return True

    def can_spawn_worker(self) -> bool:
        """Check if budget allows spawning another worker."""
        remaining = self._worker_pool_budget - self._total_worker_tokens()
        return remaining >= self._config.per_worker_max_tokens * 0.2  # At least 20% of a worker budget

    def get_status(self) -> SwarmBudgetStatus:
        """Get current swarm budget status."""
        total_used = self._orchestrator_tokens + self._total_worker_tokens() + self._reserve_used
        total_remaining = max(0, self._config.total_max_tokens - total_used)

        return SwarmBudgetStatus(
            total_tokens_used=total_used,
            total_tokens_remaining=total_remaining,
            orchestrator_tokens_used=self._orchestrator_tokens,
            worker_tokens_used=self._total_worker_tokens(),
            reserve_tokens=self._reserve_budget - self._reserve_used,
            worker_count=len(self._workers),
            can_spawn_worker=self.can_spawn_worker(),
            usage_fraction=total_used / self._config.total_max_tokens if self._config.total_max_tokens > 0 else 0.0,
        )

    def get_worker_stats(self) -> list[WorkerSpending]:
        """Get spending stats for all workers."""
        return list(self._workers.values())

    def _total_worker_tokens(self) -> int:
        return sum(w.tokens_used for w in self._workers.values())

    def to_json(self) -> dict[str, Any]:
        """Serialize for checkpointing."""
        return {
            "orchestrator_tokens": self._orchestrator_tokens,
            "reserve_used": self._reserve_used,
            "workers": {
                w_id: {
                    "tokens_used": w.tokens_used,
                    "cost_used": w.cost_used,
                    "tasks_completed": w.tasks_completed,
                }
                for w_id, w in self._workers.items()
            },
        }

    def restore_from(self, data: dict[str, Any]) -> None:
        """Restore from checkpoint data."""
        self._orchestrator_tokens = data.get("orchestrator_tokens", 0)
        self._reserve_used = data.get("reserve_used", 0)
        for w_id, w_data in data.get("workers", {}).items():
            self._workers[w_id] = WorkerSpending(
                worker_id=w_id,
                tokens_used=w_data.get("tokens_used", 0),
                cost_used=w_data.get("cost_used", 0.0),
                tasks_completed=w_data.get("tasks_completed", 0),
            )
