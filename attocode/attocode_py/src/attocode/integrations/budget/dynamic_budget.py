"""Dynamic budget rebalancing for multi-agent workflows.

Extends SharedBudgetPool with dynamic rebalancing that prevents
starvation when spawning subagents sequentially.

Key features:
- ``set_expected_children(count)`` for upfront capacity planning
- Sequential spawn cap: never take >60% of remaining budget
- Rebalance on child completion (return unused budget to pool)
- Priority-based allocation (critical children get more)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from attocode.integrations.budget.budget_pool import (
    BudgetAllocation,
    BudgetPoolConfig,
    BudgetPoolStats,
    SharedBudgetPool,
)


# =============================================================================
# Types
# =============================================================================


class ChildPriority:
    """Priority levels for child agents."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


PRIORITY_MULTIPLIERS: dict[str, float] = {
    ChildPriority.LOW: 0.5,
    ChildPriority.NORMAL: 1.0,
    ChildPriority.HIGH: 1.5,
    ChildPriority.CRITICAL: 2.0,
}


@dataclass(slots=True)
class DynamicBudgetConfig:
    """Extended configuration for dynamic budget pools."""

    max_remaining_ratio: float = 0.6
    min_per_expected_child: int = 10_000
    auto_rebalance: bool = True


@dataclass(slots=True)
class ChildPriorityRecord:
    """Priority record for a child agent."""

    child_id: str
    priority: str = ChildPriority.NORMAL
    expected_tokens: int | None = None


@dataclass(slots=True)
class DynamicBudgetStats:
    """Enhanced stats including dynamic allocation info."""

    total_tokens: int = 0
    tokens_used: int = 0
    tokens_remaining: int = 0
    active_allocations: int = 0
    utilization: float = 0.0
    expected_children: int = 0
    spawned_count: int = 0
    completed_count: int = 0
    pending_count: int = 0
    avg_per_child: int = 0


# =============================================================================
# Dynamic Budget Pool
# =============================================================================


class DynamicBudgetPool(SharedBudgetPool):
    """Budget pool with dynamic rebalancing and priority allocation.

    Extends SharedBudgetPool with capacity planning based on expected
    child count and priority-based allocation. Prevents starvation
    by capping each allocation at a fraction of remaining budget.

    Example::

        pool = create_dynamic_budget_pool(200_000)
        pool.set_expected_children(4)

        alloc = pool.reserve_dynamic("child-1", priority="high")
        # ... child runs ...
        pool.record_usage("child-1", tokens=15_000)
        pool.release_dynamic("child-1")
    """

    def __init__(
        self,
        config: BudgetPoolConfig,
        dynamic_config: DynamicBudgetConfig | None = None,
    ) -> None:
        super().__init__(config)
        self._dynamic_config = dynamic_config or DynamicBudgetConfig()
        self._expected_children = 0
        self._spawned_count = 0
        self._completed_count = 0
        self._child_priorities: dict[str, ChildPriorityRecord] = {}

    # =========================================================================
    # Capacity Planning
    # =========================================================================

    def set_expected_children(self, count: int) -> None:
        """Set the expected number of children for capacity planning.

        Adjusts max_per_child to ensure fair distribution.
        """
        self._expected_children = count
        self._update_max_per_child()

    def set_child_priority(
        self, child_id: str, priority: str = ChildPriority.NORMAL, expected_tokens: int | None = None
    ) -> None:
        """Set priority for a child agent."""
        self._child_priorities[child_id] = ChildPriorityRecord(
            child_id=child_id,
            priority=priority,
            expected_tokens=expected_tokens,
        )

    # =========================================================================
    # Dynamic Reservation
    # =========================================================================

    def reserve_dynamic(
        self, child_id: str, priority: str | None = None
    ) -> BudgetAllocation | None:
        """Reserve with dynamic capacity planning.

        Respects expected children and remaining ratio cap.

        Args:
            child_id: Unique ID for the child agent.
            priority: Priority level (low/normal/high/critical).

        Returns:
            BudgetAllocation if successful, None if pool exhausted.
        """
        if priority is not None:
            self.set_child_priority(child_id, priority)

        stats = self.get_stats()
        remaining = stats.tokens_remaining

        if remaining <= 0:
            return None

        # Cap at max_remaining_ratio of remaining budget
        ratio_cap = int(remaining * self._dynamic_config.max_remaining_ratio)

        # Reserve for expected future children
        unreserved_children = max(
            0, self._expected_children - self._spawned_count - 1
        )
        reserve_for_future = (
            unreserved_children * self._dynamic_config.min_per_expected_child
        )
        after_reserve = max(0, remaining - reserve_for_future)

        # Apply priority multiplier
        priority_record = self._child_priorities.get(child_id)
        priority_level = (
            priority_record.priority
            if priority_record
            else ChildPriority.NORMAL
        )
        multiplier = PRIORITY_MULTIPLIERS.get(priority_level, 1.0)
        divisor = max(1, unreserved_children + 1)
        priority_adjusted = int((after_reserve * multiplier) / divisor)

        # Final allocation: min of all caps
        dynamic_max = min(
            ratio_cap,
            after_reserve,
            max(
                priority_adjusted,
                self._dynamic_config.min_per_expected_child,
            ),
        )

        # Temporarily set max per child for this reservation
        self.set_max_per_child(dynamic_max)
        allocation = self.reserve(child_id)
        self.reset_max_per_child()

        if allocation is not None:
            self._spawned_count += 1

        return allocation

    def release_dynamic(self, child_id: str) -> None:
        """Release with tracking of completed count."""
        self.release(child_id)
        self._completed_count += 1
        self._child_priorities.pop(child_id, None)

    # =========================================================================
    # Extension
    # =========================================================================

    def extend(self, child_id: str, extra_tokens: int) -> bool:
        """Grant extra tokens to a child from the remaining pool.

        Args:
            child_id: The child to extend.
            extra_tokens: Additional tokens to grant.

        Returns:
            True if extension was successful.
        """
        allocation = self.get_allocation(child_id)
        if allocation is None:
            return False

        remaining = self.get_remaining()
        if extra_tokens > remaining:
            return False

        allocation.token_budget += extra_tokens
        # Adjust reserved totals
        self._total_tokens_reserved += extra_tokens
        return True

    def compress(self) -> int:
        """Reclaim unused allocations from completed/idle children.

        Returns the number of tokens freed.
        """
        freed = 0
        to_release: list[str] = []

        for child_id, allocation in self._allocations.items():
            unused = allocation.token_budget - allocation.tokens_used
            if unused > 0 and allocation.tokens_used == 0:
                # Child hasn't started, reclaim entirely
                to_release.append(child_id)
                freed += allocation.token_budget

        for child_id in to_release:
            self.release(child_id)

        return freed

    def rebalance(self) -> int:
        """Redistribute unused budget among active agents.

        Shrinks over-allocated children that haven't used their full
        budget and makes the freed tokens available for future allocations.

        Returns:
            Number of tokens freed by rebalancing.
        """
        freed = 0

        for allocation in self._allocations.values():
            if allocation.tokens_used > 0:
                # Shrink to 120% of actual usage
                new_budget = int(allocation.tokens_used * 1.2)
                if new_budget < allocation.token_budget:
                    diff = allocation.token_budget - new_budget
                    allocation.token_budget = new_budget
                    self._total_tokens_reserved -= diff
                    freed += diff

        return freed

    # =========================================================================
    # Enhanced Stats
    # =========================================================================

    def get_dynamic_stats(self) -> DynamicBudgetStats:
        """Get enhanced stats including dynamic info."""
        base = self.get_stats()
        pending = self._spawned_count - self._completed_count

        return DynamicBudgetStats(
            total_tokens=base.total_tokens,
            tokens_used=base.tokens_used,
            tokens_remaining=base.tokens_remaining,
            active_allocations=base.active_allocations,
            utilization=base.utilization,
            expected_children=self._expected_children,
            spawned_count=self._spawned_count,
            completed_count=self._completed_count,
            pending_count=pending,
            avg_per_child=(
                base.tokens_used // self._spawned_count
                if self._spawned_count > 0
                else 0
            ),
        )

    # =========================================================================
    # Internal
    # =========================================================================

    def _update_max_per_child(self) -> None:
        """Recalculate max_per_child based on expected children."""
        if self._expected_children <= 0:
            return

        stats = self.get_stats()
        remaining = stats.tokens_remaining
        unreserved = max(1, self._expected_children - self._spawned_count)

        fair_share = remaining // unreserved
        ratio_cap = int(
            remaining * self._dynamic_config.max_remaining_ratio
        )

        self.set_max_per_child(min(fair_share, ratio_cap))


# =============================================================================
# Factory
# =============================================================================


def create_dynamic_budget_pool(
    parent_budget_tokens: int,
    parent_reserve_ratio: float = 0.25,
    max_per_child: int = 100_000,
    dynamic_config: DynamicBudgetConfig | None = None,
) -> DynamicBudgetPool:
    """Create a dynamic budget pool from a parent's budget.

    Args:
        parent_budget_tokens: Total parent budget in tokens.
        parent_reserve_ratio: Fraction reserved for parent (default 25%).
        max_per_child: Maximum tokens any single child can consume.
        dynamic_config: Optional dynamic rebalancing configuration.

    Returns:
        A DynamicBudgetPool instance.
    """
    parent_reserve = int(parent_budget_tokens * parent_reserve_ratio)
    pool_tokens = parent_budget_tokens - parent_reserve

    return DynamicBudgetPool(
        config=BudgetPoolConfig(
            total_tokens=pool_tokens,
            max_per_child=min(max_per_child, pool_tokens),
            total_cost=0.5,
            max_cost_per_child=0.25,
        ),
        dynamic_config=dynamic_config or DynamicBudgetConfig(),
    )
