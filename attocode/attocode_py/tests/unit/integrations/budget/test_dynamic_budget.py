"""Tests for dynamic budget rebalancing."""

from __future__ import annotations

import pytest

from attocode.integrations.budget.budget_pool import BudgetPoolConfig
from attocode.integrations.budget.dynamic_budget import (
    ChildPriority,
    ChildPriorityRecord,
    DynamicBudgetConfig,
    DynamicBudgetPool,
    DynamicBudgetStats,
    PRIORITY_MULTIPLIERS,
    create_dynamic_budget_pool,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_pool(
    total: int = 100_000,
    max_per_child: int = 50_000,
    max_remaining_ratio: float = 0.6,
    min_per_expected_child: int = 10_000,
) -> DynamicBudgetPool:
    """Create a DynamicBudgetPool with convenient defaults."""
    return DynamicBudgetPool(
        config=BudgetPoolConfig(
            total_tokens=total,
            max_per_child=max_per_child,
        ),
        dynamic_config=DynamicBudgetConfig(
            max_remaining_ratio=max_remaining_ratio,
            min_per_expected_child=min_per_expected_child,
        ),
    )


# =============================================================================
# DynamicBudgetPool Creation
# =============================================================================


class TestDynamicBudgetPoolCreation:
    def test_creation(self) -> None:
        pool = _make_pool()
        assert pool.total_tokens == 100_000
        assert pool.tokens_used == 0

    def test_inherits_shared_budget_pool(self) -> None:
        pool = _make_pool()
        # Should have all SharedBudgetPool methods
        assert hasattr(pool, "reserve")
        assert hasattr(pool, "record_usage")
        assert hasattr(pool, "release")
        assert hasattr(pool, "get_remaining")

    def test_default_dynamic_config(self) -> None:
        pool = DynamicBudgetPool(
            config=BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000),
        )
        # Default DynamicBudgetConfig should be used
        assert pool.get_remaining() == 100_000

    def test_initial_dynamic_stats(self) -> None:
        pool = _make_pool()
        stats = pool.get_dynamic_stats()
        assert stats.expected_children == 0
        assert stats.spawned_count == 0
        assert stats.completed_count == 0
        assert stats.pending_count == 0
        assert stats.avg_per_child == 0


# =============================================================================
# set_expected_children
# =============================================================================


class TestSetExpectedChildren:
    def test_sets_expected_count(self) -> None:
        pool = _make_pool()
        pool.set_expected_children(4)
        stats = pool.get_dynamic_stats()
        assert stats.expected_children == 4

    def test_adjusts_max_per_child(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=80_000)
        pool.set_expected_children(4)
        # After setting expected children, max_per_child should be adjusted
        # fair_share = 100K / 4 = 25K
        # ratio_cap = 100K * 0.6 = 60K
        # min(25K, 60K) = 25K
        alloc = pool.reserve("child-1")
        assert alloc is not None
        assert alloc.token_budget == 25_000

    def test_zero_expected_children_is_noop(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=50_000)
        pool.set_expected_children(0)
        # Should not crash and max_per_child should remain unchanged
        alloc = pool.reserve("child-1")
        assert alloc is not None
        assert alloc.token_budget == 50_000


# =============================================================================
# set_child_priority
# =============================================================================


class TestSetChildPriority:
    def test_sets_normal_priority(self) -> None:
        pool = _make_pool()
        pool.set_child_priority("child-1", ChildPriority.NORMAL)
        # No assertion on internal state, just verify it doesn't crash
        # and the priority is used in reserve_dynamic

    def test_sets_high_priority(self) -> None:
        pool = _make_pool()
        pool.set_child_priority("child-1", ChildPriority.HIGH, expected_tokens=30_000)

    def test_sets_critical_priority(self) -> None:
        pool = _make_pool()
        pool.set_child_priority("child-1", ChildPriority.CRITICAL)

    def test_sets_low_priority(self) -> None:
        pool = _make_pool()
        pool.set_child_priority("child-1", ChildPriority.LOW)


class TestChildPriorityConstants:
    def test_priority_values(self) -> None:
        assert ChildPriority.LOW == "low"
        assert ChildPriority.NORMAL == "normal"
        assert ChildPriority.HIGH == "high"
        assert ChildPriority.CRITICAL == "critical"

    def test_multipliers_cover_all_priorities(self) -> None:
        for p in [ChildPriority.LOW, ChildPriority.NORMAL, ChildPriority.HIGH, ChildPriority.CRITICAL]:
            assert p in PRIORITY_MULTIPLIERS

    def test_multiplier_ordering(self) -> None:
        assert PRIORITY_MULTIPLIERS[ChildPriority.LOW] < PRIORITY_MULTIPLIERS[ChildPriority.NORMAL]
        assert PRIORITY_MULTIPLIERS[ChildPriority.NORMAL] < PRIORITY_MULTIPLIERS[ChildPriority.HIGH]
        assert PRIORITY_MULTIPLIERS[ChildPriority.HIGH] < PRIORITY_MULTIPLIERS[ChildPriority.CRITICAL]


# =============================================================================
# reserve_dynamic
# =============================================================================


class TestReserveDynamic:
    def test_basic_allocation(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=50_000)
        alloc = pool.reserve_dynamic("child-1")
        assert alloc is not None
        assert alloc.id == "child-1"
        assert alloc.token_budget > 0

    def test_returns_none_when_exhausted(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=100_000)
        # Exhaust by reserving child-1, recording full usage, releasing,
        # then reserve again until pool is truly empty
        a1 = pool.reserve_dynamic("child-1")
        assert a1 is not None
        pool.record_usage("child-1", tokens=a1.token_budget)
        a2 = pool.reserve_dynamic("child-2")
        assert a2 is not None
        pool.record_usage("child-2", tokens=a2.token_budget)
        # Keep reserving until pool is drained
        while True:
            remaining = pool.get_remaining()
            if remaining <= 0:
                break
            child_id = f"child-drain-{remaining}"
            a = pool.reserve_dynamic(child_id)
            if a is None:
                break
            pool.record_usage(child_id, tokens=a.token_budget)
        alloc = pool.reserve_dynamic("child-final")
        assert alloc is None

    def test_respects_remaining_ratio_cap(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=100_000, max_remaining_ratio=0.6)
        alloc = pool.reserve_dynamic("child-1")
        assert alloc is not None
        # Allocation should be at most 60% of 100K = 60K
        assert alloc.token_budget <= 60_000

    def test_high_priority_gets_more(self) -> None:
        pool1 = _make_pool(total=100_000, max_per_child=100_000)
        pool1.set_expected_children(2)
        alloc_normal = pool1.reserve_dynamic("child-1", priority=ChildPriority.NORMAL)

        pool2 = _make_pool(total=100_000, max_per_child=100_000)
        pool2.set_expected_children(2)
        alloc_high = pool2.reserve_dynamic("child-1", priority=ChildPriority.HIGH)

        assert alloc_normal is not None
        assert alloc_high is not None
        # High priority should get at least as much (often more due to multiplier)
        assert alloc_high.token_budget >= alloc_normal.token_budget

    def test_critical_priority_gets_more_than_normal(self) -> None:
        pool1 = _make_pool(total=100_000, max_per_child=100_000)
        pool1.set_expected_children(3)
        alloc_normal = pool1.reserve_dynamic("child-1", priority=ChildPriority.NORMAL)

        pool2 = _make_pool(total=100_000, max_per_child=100_000)
        pool2.set_expected_children(3)
        alloc_critical = pool2.reserve_dynamic("child-1", priority=ChildPriority.CRITICAL)

        assert alloc_normal is not None
        assert alloc_critical is not None
        assert alloc_critical.token_budget >= alloc_normal.token_budget

    def test_increments_spawned_count(self) -> None:
        pool = _make_pool()
        pool.reserve_dynamic("child-1")
        pool.reserve_dynamic("child-2")
        stats = pool.get_dynamic_stats()
        assert stats.spawned_count == 2

    def test_failed_reserve_does_not_increment_spawned(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=100_000)
        # Exhaust the pool first
        while True:
            remaining = pool.get_remaining()
            if remaining <= 0:
                break
            child_id = f"child-{pool.get_dynamic_stats().spawned_count}"
            a = pool.reserve_dynamic(child_id)
            if a is None:
                break
            pool.record_usage(child_id, tokens=a.token_budget)
        spawned_before = pool.get_dynamic_stats().spawned_count
        # This should fail and not increment spawned_count
        alloc = pool.reserve_dynamic("child-final")
        assert alloc is None
        assert pool.get_dynamic_stats().spawned_count == spawned_before

    def test_reserves_for_future_children(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=100_000, min_per_expected_child=20_000)
        pool.set_expected_children(4)
        # First child should not take entire pool since 3 more are expected
        alloc = pool.reserve_dynamic("child-1")
        assert alloc is not None
        # Should leave room for at least 3 * 20K = 60K for future children
        assert alloc.token_budget <= 40_000

    def test_inline_priority_setting(self) -> None:
        pool = _make_pool()
        alloc = pool.reserve_dynamic("child-1", priority=ChildPriority.HIGH)
        assert alloc is not None

    def test_restores_max_per_child_after_reserve(self) -> None:
        """reserve_dynamic temporarily changes max_per_child; verify it resets."""
        pool = _make_pool(total=200_000, max_per_child=50_000)
        pool.reserve_dynamic("child-1")
        # After reserve_dynamic, max_per_child should be restored to original
        alloc = pool.reserve("child-2")
        assert alloc is not None
        # The regular reserve should use the original max_per_child (or remaining if less)
        remaining_before = pool.get_remaining() + alloc.token_budget
        expected = min(50_000, remaining_before)
        assert alloc.token_budget == expected


# =============================================================================
# release_dynamic
# =============================================================================


class TestReleaseDynamic:
    def test_increments_completed_count(self) -> None:
        pool = _make_pool()
        pool.reserve_dynamic("child-1")
        pool.release_dynamic("child-1")
        stats = pool.get_dynamic_stats()
        assert stats.completed_count == 1

    def test_removes_priority_record(self) -> None:
        pool = _make_pool()
        pool.set_child_priority("child-1", ChildPriority.HIGH)
        pool.reserve_dynamic("child-1")
        pool.release_dynamic("child-1")
        # Priority record should be cleaned up (internal check)
        assert "child-1" not in pool._child_priorities

    def test_frees_allocation(self) -> None:
        pool = _make_pool(total=100_000)
        pool.reserve_dynamic("child-1")
        remaining_before = pool.get_remaining()
        pool.release_dynamic("child-1")
        remaining_after = pool.get_remaining()
        assert remaining_after > remaining_before

    def test_pending_count_tracks_active(self) -> None:
        pool = _make_pool()
        pool.reserve_dynamic("child-1")
        pool.reserve_dynamic("child-2")
        assert pool.get_dynamic_stats().pending_count == 2
        pool.release_dynamic("child-1")
        assert pool.get_dynamic_stats().pending_count == 1
        pool.release_dynamic("child-2")
        assert pool.get_dynamic_stats().pending_count == 0


# =============================================================================
# extend
# =============================================================================


class TestExtend:
    def test_gives_more_tokens(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=30_000)
        pool.reserve("child-1")
        remaining_for_child = pool.get_remaining_for_child("child-1")
        assert remaining_for_child == 30_000

        result = pool.extend("child-1", extra_tokens=10_000)
        assert result is True
        assert pool.get_remaining_for_child("child-1") == 40_000

    def test_fails_when_pool_insufficient(self) -> None:
        pool = _make_pool(total=50_000, max_per_child=50_000)
        pool.reserve("child-1")
        # Pool is exhausted, cannot extend
        result = pool.extend("child-1", extra_tokens=10_000)
        assert result is False

    def test_fails_for_unknown_child(self) -> None:
        pool = _make_pool()
        result = pool.extend("nonexistent", extra_tokens=5_000)
        assert result is False

    def test_adjusts_reserved_totals(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=30_000)
        pool.reserve("child-1")
        # 30K reserved, 70K remaining
        assert pool.get_remaining() == 70_000
        pool.extend("child-1", extra_tokens=20_000)
        # 50K reserved now, 50K remaining
        assert pool.get_remaining() == 50_000

    def test_extend_exact_remaining(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=60_000)
        pool.reserve("child-1")
        # 60K reserved, 40K remaining
        result = pool.extend("child-1", extra_tokens=40_000)
        assert result is True
        assert pool.get_remaining() == 0


# =============================================================================
# compress
# =============================================================================


class TestCompress:
    def test_reclaims_unused_allocations(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=30_000)
        pool.reserve("child-1")  # 30K, no usage
        pool.reserve("child-2")  # 30K, no usage

        freed = pool.compress()
        assert freed == 60_000
        # Allocations should be removed
        assert pool.get_allocation("child-1") is None
        assert pool.get_allocation("child-2") is None

    def test_does_not_reclaim_active_allocations(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=30_000)
        pool.reserve("child-1")
        pool.record_usage("child-1", tokens=5_000)  # actively used

        freed = pool.compress()
        assert freed == 0
        # Allocation should still exist
        assert pool.get_allocation("child-1") is not None

    def test_mixed_active_and_idle(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=30_000)
        pool.reserve("child-1")
        pool.record_usage("child-1", tokens=5_000)  # active
        pool.reserve("child-2")  # idle

        freed = pool.compress()
        assert freed == 30_000
        assert pool.get_allocation("child-1") is not None
        assert pool.get_allocation("child-2") is None

    def test_compress_no_allocations(self) -> None:
        pool = _make_pool()
        freed = pool.compress()
        assert freed == 0


# =============================================================================
# rebalance
# =============================================================================


class TestRebalance:
    def test_shrinks_over_allocated(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=50_000)
        pool.reserve("child-1")
        pool.record_usage("child-1", tokens=10_000)
        # Budget = 50K, used = 10K, 120% of used = 12K
        # Shrink from 50K to 12K, freeing 38K

        freed = pool.rebalance()
        assert freed == 38_000
        alloc = pool.get_allocation("child-1")
        assert alloc is not None
        assert alloc.token_budget == 12_000

    def test_does_not_shrink_below_120_percent(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=50_000)
        pool.reserve("child-1")
        pool.record_usage("child-1", tokens=45_000)
        # 120% of 45K = 54K > 50K budget, so no shrink

        freed = pool.rebalance()
        assert freed == 0

    def test_skips_idle_children(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=30_000)
        pool.reserve("child-1")  # idle (tokens_used == 0)

        freed = pool.rebalance()
        assert freed == 0

    def test_rebalances_multiple_children(self) -> None:
        pool = _make_pool(total=200_000, max_per_child=50_000)
        pool.reserve("child-1")
        pool.reserve("child-2")
        pool.record_usage("child-1", tokens=10_000)
        pool.record_usage("child-2", tokens=20_000)
        # child-1: 50K -> 12K (freed 38K)
        # child-2: 50K -> 24K (freed 26K)

        freed = pool.rebalance()
        assert freed == 64_000

    def test_frees_tokens_to_pool(self) -> None:
        pool = _make_pool(total=100_000, max_per_child=50_000)
        pool.reserve("child-1")
        pool.record_usage("child-1", tokens=10_000)
        remaining_before = pool.get_remaining()

        freed = pool.rebalance()
        remaining_after = pool.get_remaining()
        assert remaining_after == remaining_before + freed

    def test_rebalance_no_allocations(self) -> None:
        pool = _make_pool()
        freed = pool.rebalance()
        assert freed == 0


# =============================================================================
# get_dynamic_stats
# =============================================================================


class TestGetDynamicStats:
    def test_returns_correct_type(self) -> None:
        pool = _make_pool()
        stats = pool.get_dynamic_stats()
        assert isinstance(stats, DynamicBudgetStats)

    def test_tracks_expected_children(self) -> None:
        pool = _make_pool()
        pool.set_expected_children(5)
        stats = pool.get_dynamic_stats()
        assert stats.expected_children == 5

    def test_tracks_spawned_and_completed(self) -> None:
        pool = _make_pool()
        pool.reserve_dynamic("child-1")
        pool.reserve_dynamic("child-2")
        pool.record_usage("child-1", tokens=5_000)
        pool.release_dynamic("child-1")

        stats = pool.get_dynamic_stats()
        assert stats.spawned_count == 2
        assert stats.completed_count == 1
        assert stats.pending_count == 1

    def test_avg_per_child(self) -> None:
        pool = _make_pool()
        pool.reserve_dynamic("child-1")
        pool.reserve_dynamic("child-2")
        pool.record_usage("child-1", tokens=10_000)
        pool.record_usage("child-2", tokens=20_000)

        stats = pool.get_dynamic_stats()
        assert stats.avg_per_child == 15_000  # 30K / 2

    def test_avg_per_child_zero_when_no_spawns(self) -> None:
        pool = _make_pool()
        stats = pool.get_dynamic_stats()
        assert stats.avg_per_child == 0

    def test_includes_base_stats(self) -> None:
        pool = _make_pool(total=100_000)
        pool.reserve_dynamic("child-1")
        pool.record_usage("child-1", tokens=10_000)

        stats = pool.get_dynamic_stats()
        assert stats.total_tokens == 100_000
        assert stats.tokens_used == 10_000
        assert stats.utilization > 0.0


# =============================================================================
# Factory
# =============================================================================


class TestCreateDynamicBudgetPool:
    def test_default_reserve_ratio(self) -> None:
        pool = create_dynamic_budget_pool(200_000)
        # 25% reserved -> 150K pool
        assert pool.total_tokens == 150_000

    def test_custom_reserve_ratio(self) -> None:
        pool = create_dynamic_budget_pool(200_000, parent_reserve_ratio=0.5)
        assert pool.total_tokens == 100_000

    def test_max_per_child_capped(self) -> None:
        pool = create_dynamic_budget_pool(40_000, max_per_child=100_000)
        # Pool = 30K, max_per_child capped to 30K
        alloc = pool.reserve("child-1")
        assert alloc is not None
        assert alloc.token_budget == 30_000

    def test_returns_dynamic_budget_pool(self) -> None:
        pool = create_dynamic_budget_pool(100_000)
        assert isinstance(pool, DynamicBudgetPool)

    def test_custom_dynamic_config(self) -> None:
        dyn_config = DynamicBudgetConfig(
            max_remaining_ratio=0.8,
            min_per_expected_child=5_000,
            auto_rebalance=False,
        )
        pool = create_dynamic_budget_pool(100_000, dynamic_config=dyn_config)
        # Should use the custom config -- verify via behavior
        assert pool.total_tokens == 75_000

    def test_has_cost_defaults(self) -> None:
        pool = create_dynamic_budget_pool(100_000)
        # Factory sets total_cost=0.5, max_cost_per_child=0.25
        alloc = pool.reserve("child-1")
        assert alloc is not None
        assert alloc.cost_budget == 0.25


# =============================================================================
# Integration: Full Lifecycle
# =============================================================================


class TestFullLifecycle:
    def test_sequential_spawn_with_rebalance(self) -> None:
        """Simulate sequential child spawning with rebalancing."""
        pool = _make_pool(total=100_000, max_per_child=60_000)
        pool.set_expected_children(3)

        # Spawn child-1
        a1 = pool.reserve_dynamic("child-1")
        assert a1 is not None

        # Child-1 works and uses some tokens
        pool.record_usage("child-1", tokens=10_000)

        # Rebalance before spawning next child
        freed = pool.rebalance()
        assert freed > 0

        # Spawn child-2
        a2 = pool.reserve_dynamic("child-2")
        assert a2 is not None

        # Child-1 completes
        pool.release_dynamic("child-1")

        # Spawn child-3
        a3 = pool.reserve_dynamic("child-3")
        assert a3 is not None

        stats = pool.get_dynamic_stats()
        assert stats.spawned_count == 3
        assert stats.completed_count == 1
        assert stats.pending_count == 2

    def test_extend_then_rebalance(self) -> None:
        """Extend a child, then rebalance to reclaim unused."""
        pool = _make_pool(total=100_000, max_per_child=30_000)
        pool.reserve("child-1")
        pool.record_usage("child-1", tokens=25_000)

        # Extend child-1 because it needs more
        pool.extend("child-1", extra_tokens=10_000)
        assert pool.get_remaining_for_child("child-1") == 15_000

        # Record a bit more usage
        pool.record_usage("child-1", tokens=5_000)

        # Rebalance: budget=40K, used=30K, 120% of 30K = 36K < 40K, so shrink
        freed = pool.rebalance()
        assert freed == 4_000
        alloc = pool.get_allocation("child-1")
        assert alloc is not None
        assert alloc.token_budget == 36_000

    def test_compress_then_spawn(self) -> None:
        """Compress idle allocations, then spawn new children."""
        pool = _make_pool(total=100_000, max_per_child=40_000)
        pool.reserve("idle-1")  # idle
        pool.reserve("idle-2")  # idle

        # Pool is nearly exhausted (80K reserved)
        assert pool.get_remaining() == 20_000

        freed = pool.compress()
        assert freed == 80_000
        assert pool.get_remaining() == 100_000

        # Now we can spawn more
        alloc = pool.reserve_dynamic("child-1")
        assert alloc is not None
