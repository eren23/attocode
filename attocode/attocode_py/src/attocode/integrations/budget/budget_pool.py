"""Shared budget pool for multi-agent workflows.

Enables parent-child budget sharing so subagents draw from a shared pool
that the parent allocates from its own budget, keeping total tree cost
bounded.

Model:
    Parent budget: 200K tokens
    Parent reserves: 50K (for synthesis after subagents complete)
    Subagent pool: 150K (shared among all children)

Each child can draw up to ``max_per_child`` tokens from the pool, but
the combined consumption never exceeds the pool total.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


# =============================================================================
# Types
# =============================================================================


@dataclass(slots=True)
class BudgetPoolConfig:
    """Configuration for a budget pool."""

    total_tokens: int
    max_per_child: int
    total_cost: float | None = None
    max_cost_per_child: float | None = None


@dataclass(slots=True)
class BudgetAllocation:
    """An active budget allocation for a child agent."""

    id: str
    token_budget: int
    cost_budget: float
    tokens_used: int = 0
    cost_used: float = 0.0


@dataclass(slots=True)
class BudgetPoolStats:
    """Statistics for the budget pool."""

    total_tokens: int
    tokens_used: int
    tokens_remaining: int
    active_allocations: int
    utilization: float


# =============================================================================
# Shared Budget Pool
# =============================================================================


class SharedBudgetPool:
    """Shared budget pool with pessimistic reservation accounting.

    Uses pessimistic accounting: reserved tokens count against pool
    capacity until actual usage is recorded via ``record_usage()`` and
    the allocation is released via ``release()``.

    Thread-safe via asyncio.Lock for all mutating operations.
    Synchronous methods are also provided for non-async contexts.
    """

    def __init__(self, config: BudgetPoolConfig) -> None:
        self._config = config
        self._original_max_per_child = config.max_per_child
        self._allocations: dict[str, BudgetAllocation] = {}
        self._total_tokens_used = 0
        self._total_cost_used = 0.0
        self._total_tokens_reserved = 0
        self._total_cost_reserved = 0.0
        self._lock = asyncio.Lock()

    # =========================================================================
    # Allocation
    # =========================================================================

    def reserve(self, child_id: str) -> BudgetAllocation | None:
        """Reserve a budget allocation for a child agent.

        Uses pessimistic accounting: reserved tokens count against pool
        capacity until released. Returns None if the pool is exhausted.
        """
        committed = max(self._total_tokens_used, self._total_tokens_reserved)
        remaining = self._config.total_tokens - committed
        if remaining <= 0:
            return None

        token_budget = min(self._config.max_per_child, remaining)

        committed_cost = max(self._total_cost_used, self._total_cost_reserved)
        if self._config.total_cost is not None:
            cost_remaining = self._config.total_cost - committed_cost
        else:
            cost_remaining = float("inf")

        if self._config.max_cost_per_child is not None:
            cost_budget = min(self._config.max_cost_per_child, max(0.0, cost_remaining))
        else:
            cost_budget = max(0.0, cost_remaining)

        if token_budget <= 0:
            return None
        if self._config.total_cost is not None and cost_budget <= 0:
            return None

        allocation = BudgetAllocation(
            id=child_id,
            token_budget=token_budget,
            cost_budget=cost_budget,
        )

        self._total_tokens_reserved += token_budget
        self._total_cost_reserved += cost_budget
        self._allocations[child_id] = allocation

        return allocation

    async def reserve_async(self, child_id: str) -> BudgetAllocation | None:
        """Thread-safe async version of reserve."""
        async with self._lock:
            return self.reserve(child_id)

    def record_usage(
        self, child_id: str, tokens: int, cost: float = 0.0
    ) -> bool:
        """Record token consumption for a child agent.

        Returns False if the child has exceeded its allocation.
        """
        allocation = self._allocations.get(child_id)
        if allocation is None:
            return False

        allocation.tokens_used += tokens
        allocation.cost_used += cost
        self._total_tokens_used += tokens
        self._total_cost_used += cost

        return allocation.tokens_used <= allocation.token_budget

    async def record_usage_async(
        self, child_id: str, tokens: int, cost: float = 0.0
    ) -> bool:
        """Thread-safe async version of record_usage."""
        async with self._lock:
            return self.record_usage(child_id, tokens, cost)

    def release(self, child_id: str) -> None:
        """Release an allocation, returning unused budget to the pool.

        Must be called after the child completes to adjust pessimistic
        reservations to reflect actual usage.
        """
        allocation = self._allocations.get(child_id)
        if allocation is not None:
            self._total_tokens_reserved -= allocation.token_budget
            self._total_cost_reserved -= allocation.cost_budget
            del self._allocations[child_id]

    async def release_async(self, child_id: str) -> None:
        """Thread-safe async version of release."""
        async with self._lock:
            self.release(child_id)

    # =========================================================================
    # Queries
    # =========================================================================

    def get_remaining(self) -> int:
        """Get total remaining tokens in the pool."""
        committed = max(self._total_tokens_used, self._total_tokens_reserved)
        return max(0, self._config.total_tokens - committed)

    def get_remaining_for_child(self, child_id: str) -> int:
        """Get remaining tokens for a specific child allocation."""
        allocation = self._allocations.get(child_id)
        if allocation is None:
            return 0
        return max(0, allocation.token_budget - allocation.tokens_used)

    def get_allocation(self, child_id: str) -> BudgetAllocation | None:
        """Get the current allocation for a child."""
        return self._allocations.get(child_id)

    def has_capacity(self) -> bool:
        """Check if the pool has enough budget for at least one more child."""
        committed = max(self._total_tokens_used, self._total_tokens_reserved)
        return self._config.total_tokens - committed > 10_000

    def get_stats(self) -> BudgetPoolStats:
        """Get overall pool statistics."""
        committed = max(self._total_tokens_used, self._total_tokens_reserved)
        total = self._config.total_tokens

        return BudgetPoolStats(
            total_tokens=total,
            tokens_used=self._total_tokens_used,
            tokens_remaining=max(0, total - committed),
            active_allocations=len(self._allocations),
            utilization=committed / total if total > 0 else 0.0,
        )

    # =========================================================================
    # Max-Per-Child Override
    # =========================================================================

    def set_max_per_child(self, max_per_child: int) -> None:
        """Temporarily override max_per_child for batch spawning.

        Used by parallel spawn to divide the pool equally among children.
        Must be followed by ``reset_max_per_child()`` in a finally block.
        """
        self._config.max_per_child = max_per_child

    def reset_max_per_child(self) -> None:
        """Restore max_per_child to the original value."""
        self._config.max_per_child = self._original_max_per_child

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def total_tokens(self) -> int:
        """Total pool capacity."""
        return self._config.total_tokens

    @property
    def tokens_used(self) -> int:
        """Total tokens consumed across all children."""
        return self._total_tokens_used


# =============================================================================
# Factory
# =============================================================================


def create_budget_pool(
    parent_budget_tokens: int,
    parent_reserve_ratio: float = 0.25,
    max_per_child: int = 100_000,
) -> SharedBudgetPool:
    """Create a budget pool from a parent's total budget.

    Reserves a portion for the parent's own synthesis work.

    Args:
        parent_budget_tokens: Total parent budget in tokens.
        parent_reserve_ratio: Fraction reserved for parent (default 25%).
        max_per_child: Maximum tokens any single child can consume.

    Returns:
        A SharedBudgetPool instance.
    """
    parent_reserve = int(parent_budget_tokens * parent_reserve_ratio)
    pool_tokens = parent_budget_tokens - parent_reserve

    return SharedBudgetPool(BudgetPoolConfig(
        total_tokens=pool_tokens,
        max_per_child=min(max_per_child, pool_tokens),
        total_cost=0.5,
        max_cost_per_child=0.25,
    ))
