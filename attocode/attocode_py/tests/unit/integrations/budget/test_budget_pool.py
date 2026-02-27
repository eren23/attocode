"""Tests for shared budget pool."""

from __future__ import annotations

import pytest

from attocode.integrations.budget.budget_pool import (
    BudgetAllocation,
    BudgetPoolConfig,
    BudgetPoolStats,
    SharedBudgetPool,
    create_budget_pool,
)


# =============================================================================
# BudgetPoolConfig
# =============================================================================


class TestBudgetPoolConfig:
    def test_basic_creation(self) -> None:
        config = BudgetPoolConfig(total_tokens=100_000, max_per_child=25_000)
        assert config.total_tokens == 100_000
        assert config.max_per_child == 25_000
        assert config.total_cost is None
        assert config.max_cost_per_child is None

    def test_creation_with_cost(self) -> None:
        config = BudgetPoolConfig(
            total_tokens=200_000,
            max_per_child=50_000,
            total_cost=1.0,
            max_cost_per_child=0.25,
        )
        assert config.total_cost == 1.0
        assert config.max_cost_per_child == 0.25


# =============================================================================
# SharedBudgetPool Creation
# =============================================================================


class TestSharedBudgetPoolCreation:
    def test_creation(self) -> None:
        config = BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        pool = SharedBudgetPool(config)
        assert pool.total_tokens == 100_000
        assert pool.tokens_used == 0

    def test_initial_remaining_equals_total(self) -> None:
        config = BudgetPoolConfig(total_tokens=150_000, max_per_child=50_000)
        pool = SharedBudgetPool(config)
        assert pool.get_remaining() == 150_000

    def test_initial_has_capacity(self) -> None:
        config = BudgetPoolConfig(total_tokens=150_000, max_per_child=50_000)
        pool = SharedBudgetPool(config)
        assert pool.has_capacity() is True

    def test_initial_stats(self) -> None:
        config = BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        pool = SharedBudgetPool(config)
        stats = pool.get_stats()
        assert stats.total_tokens == 100_000
        assert stats.tokens_used == 0
        assert stats.tokens_remaining == 100_000
        assert stats.active_allocations == 0
        assert stats.utilization == 0.0


# =============================================================================
# Reserve
# =============================================================================


class TestReserve:
    def _make_pool(
        self,
        total: int = 100_000,
        max_per_child: int = 30_000,
        total_cost: float | None = None,
        max_cost_per_child: float | None = None,
    ) -> SharedBudgetPool:
        return SharedBudgetPool(
            BudgetPoolConfig(
                total_tokens=total,
                max_per_child=max_per_child,
                total_cost=total_cost,
                max_cost_per_child=max_cost_per_child,
            )
        )

    def test_allocates_up_to_max_per_child(self) -> None:
        pool = self._make_pool(total=100_000, max_per_child=30_000)
        alloc = pool.reserve("child-1")
        assert alloc is not None
        assert alloc.id == "child-1"
        assert alloc.token_budget == 30_000
        assert alloc.tokens_used == 0

    def test_allocates_remaining_when_less_than_max(self) -> None:
        pool = self._make_pool(total=20_000, max_per_child=30_000)
        alloc = pool.reserve("child-1")
        assert alloc is not None
        # Only 20K available, so allocation is capped at remaining
        assert alloc.token_budget == 20_000

    def test_returns_none_when_no_capacity(self) -> None:
        pool = self._make_pool(total=50_000, max_per_child=50_000)
        alloc1 = pool.reserve("child-1")
        assert alloc1 is not None
        # Pool is exhausted (reserved == total)
        alloc2 = pool.reserve("child-2")
        assert alloc2 is None

    def test_multiple_children_share_pool(self) -> None:
        pool = self._make_pool(total=100_000, max_per_child=30_000)
        a1 = pool.reserve("child-1")
        a2 = pool.reserve("child-2")
        a3 = pool.reserve("child-3")
        assert a1 is not None
        assert a2 is not None
        assert a3 is not None
        # 30K * 3 = 90K reserved, 10K remaining
        assert pool.get_remaining() == 10_000

    def test_fourth_child_gets_reduced_allocation(self) -> None:
        pool = self._make_pool(total=100_000, max_per_child=30_000)
        pool.reserve("child-1")
        pool.reserve("child-2")
        pool.reserve("child-3")
        a4 = pool.reserve("child-4")
        assert a4 is not None
        # Only 10K remaining
        assert a4.token_budget == 10_000

    def test_reserve_reduces_remaining(self) -> None:
        pool = self._make_pool(total=100_000, max_per_child=40_000)
        pool.reserve("child-1")
        assert pool.get_remaining() == 60_000

    def test_reserve_with_cost_limits(self) -> None:
        pool = self._make_pool(
            total=100_000,
            max_per_child=50_000,
            total_cost=1.0,
            max_cost_per_child=0.3,
        )
        alloc = pool.reserve("child-1")
        assert alloc is not None
        assert alloc.cost_budget == 0.3

    def test_reserve_returns_none_when_cost_exhausted(self) -> None:
        pool = self._make_pool(
            total=200_000,
            max_per_child=50_000,
            total_cost=0.5,
            max_cost_per_child=0.25,
        )
        a1 = pool.reserve("child-1")
        a2 = pool.reserve("child-2")
        assert a1 is not None
        assert a2 is not None
        # Cost budget exhausted (0.25 * 2 = 0.5)
        a3 = pool.reserve("child-3")
        assert a3 is None


# =============================================================================
# Record Usage
# =============================================================================


class TestRecordUsage:
    def _make_pool_with_child(self) -> tuple[SharedBudgetPool, BudgetAllocation]:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        alloc = pool.reserve("child-1")
        assert alloc is not None
        return pool, alloc

    def test_records_tokens(self) -> None:
        pool, alloc = self._make_pool_with_child()
        result = pool.record_usage("child-1", tokens=10_000)
        assert result is True
        assert alloc.tokens_used == 10_000
        assert pool.tokens_used == 10_000

    def test_records_cost(self) -> None:
        pool, alloc = self._make_pool_with_child()
        pool.record_usage("child-1", tokens=5_000, cost=0.05)
        assert alloc.cost_used == 0.05

    def test_returns_false_when_over_budget(self) -> None:
        pool, _ = self._make_pool_with_child()
        result = pool.record_usage("child-1", tokens=60_000)
        assert result is False

    def test_returns_false_for_unknown_child(self) -> None:
        pool, _ = self._make_pool_with_child()
        result = pool.record_usage("unknown", tokens=1_000)
        assert result is False

    def test_cumulative_usage(self) -> None:
        pool, alloc = self._make_pool_with_child()
        pool.record_usage("child-1", tokens=10_000)
        pool.record_usage("child-1", tokens=15_000)
        assert alloc.tokens_used == 25_000
        assert pool.tokens_used == 25_000

    def test_exact_budget_returns_true(self) -> None:
        pool, _ = self._make_pool_with_child()
        result = pool.record_usage("child-1", tokens=50_000)
        assert result is True


# =============================================================================
# Release
# =============================================================================


class TestRelease:
    def test_release_frees_tokens(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        pool.reserve("child-1")
        assert pool.get_remaining() == 50_000
        pool.record_usage("child-1", tokens=10_000)
        pool.release("child-1")
        # After release, reserved tokens freed; only actual usage counts
        assert pool.get_remaining() == 90_000

    def test_release_removes_allocation(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        pool.reserve("child-1")
        pool.release("child-1")
        assert pool.get_allocation("child-1") is None

    def test_release_unknown_child_is_noop(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        # Should not raise
        pool.release("nonexistent")

    def test_release_decrements_active_allocations(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=30_000)
        )
        pool.reserve("child-1")
        pool.reserve("child-2")
        assert pool.get_stats().active_allocations == 2
        pool.release("child-1")
        assert pool.get_stats().active_allocations == 1


# =============================================================================
# Queries
# =============================================================================


class TestGetRemaining:
    def test_reflects_reservations(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=40_000)
        )
        pool.reserve("child-1")
        assert pool.get_remaining() == 60_000

    def test_reflects_usage_after_release(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=40_000)
        )
        pool.reserve("child-1")
        pool.record_usage("child-1", tokens=20_000)
        pool.release("child-1")
        # Reserved freed, but used=20K remains
        assert pool.get_remaining() == 80_000

    def test_never_negative(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=50_000, max_per_child=50_000)
        )
        pool.reserve("child-1")
        pool.record_usage("child-1", tokens=60_000)  # over budget
        # get_remaining clamps to 0
        assert pool.get_remaining() >= 0


class TestGetRemainingForChild:
    def test_returns_budget_minus_used(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=40_000)
        )
        pool.reserve("child-1")
        pool.record_usage("child-1", tokens=15_000)
        assert pool.get_remaining_for_child("child-1") == 25_000

    def test_returns_zero_for_unknown_child(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=40_000)
        )
        assert pool.get_remaining_for_child("unknown") == 0

    def test_never_negative(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=40_000)
        )
        pool.reserve("child-1")
        pool.record_usage("child-1", tokens=50_000)  # over budget
        assert pool.get_remaining_for_child("child-1") == 0


class TestHasCapacity:
    def test_true_when_above_10k(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        assert pool.has_capacity() is True

    def test_false_when_below_10k(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=50_000, max_per_child=45_000)
        )
        pool.reserve("child-1")  # 45K reserved, 5K remaining
        assert pool.has_capacity() is False

    def test_false_when_exactly_10k(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=50_000, max_per_child=40_000)
        )
        pool.reserve("child-1")  # 40K reserved, 10K remaining
        # has_capacity checks > 10_000 (not >=)
        assert pool.has_capacity() is False

    def test_true_when_just_above_10k(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=50_001, max_per_child=40_000)
        )
        pool.reserve("child-1")  # 40K reserved, 10001 remaining
        assert pool.has_capacity() is True


# =============================================================================
# Stats
# =============================================================================


class TestGetStats:
    def test_returns_correct_type(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        stats = pool.get_stats()
        assert isinstance(stats, BudgetPoolStats)

    def test_utilization_after_reservation(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        pool.reserve("child-1")
        stats = pool.get_stats()
        assert stats.utilization == pytest.approx(0.5)

    def test_utilization_after_usage_and_release(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        pool.reserve("child-1")
        pool.record_usage("child-1", tokens=30_000)
        pool.release("child-1")
        stats = pool.get_stats()
        # No reservations, 30K used
        assert stats.tokens_used == 30_000
        assert stats.utilization == pytest.approx(0.3)

    def test_zero_total_tokens_no_division_error(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=0, max_per_child=0)
        )
        stats = pool.get_stats()
        assert stats.utilization == 0.0


# =============================================================================
# Max-Per-Child Override
# =============================================================================


class TestMaxPerChildOverride:
    def test_set_max_per_child(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        pool.set_max_per_child(20_000)
        alloc = pool.reserve("child-1")
        assert alloc is not None
        assert alloc.token_budget == 20_000

    def test_reset_max_per_child(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        pool.set_max_per_child(20_000)
        pool.reset_max_per_child()
        alloc = pool.reserve("child-1")
        assert alloc is not None
        assert alloc.token_budget == 50_000

    def test_set_and_reset_pattern(self) -> None:
        """Simulate the batch spawning pattern."""
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        pool.set_max_per_child(25_000)
        try:
            a1 = pool.reserve("child-1")
            a2 = pool.reserve("child-2")
            assert a1 is not None
            assert a1.token_budget == 25_000
            assert a2 is not None
            assert a2.token_budget == 25_000
        finally:
            pool.reset_max_per_child()

        # After reset, new reserves use original max
        a3 = pool.reserve("child-3")
        assert a3 is not None
        assert a3.token_budget == 50_000


# =============================================================================
# Factory
# =============================================================================


class TestCreateBudgetPool:
    def test_default_reserve_ratio(self) -> None:
        pool = create_budget_pool(200_000)
        # 25% reserved for parent -> pool = 150K
        assert pool.total_tokens == 150_000

    def test_custom_reserve_ratio(self) -> None:
        pool = create_budget_pool(200_000, parent_reserve_ratio=0.5)
        assert pool.total_tokens == 100_000

    def test_max_per_child_capped_to_pool_total(self) -> None:
        pool = create_budget_pool(40_000, max_per_child=100_000)
        # Pool = 30K (75% of 40K), max_per_child capped to 30K
        alloc = pool.reserve("child-1")
        assert alloc is not None
        assert alloc.token_budget == 30_000

    def test_returns_shared_budget_pool(self) -> None:
        pool = create_budget_pool(100_000)
        assert isinstance(pool, SharedBudgetPool)

    def test_has_cost_defaults(self) -> None:
        pool = create_budget_pool(100_000)
        # Factory sets total_cost=0.5, max_cost_per_child=0.25
        alloc = pool.reserve("child-1")
        assert alloc is not None
        assert alloc.cost_budget == 0.25


# =============================================================================
# Properties
# =============================================================================


class TestProperties:
    def test_total_tokens(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=123_456, max_per_child=50_000)
        )
        assert pool.total_tokens == 123_456

    def test_tokens_used_tracks_usage(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        pool.reserve("child-1")
        pool.record_usage("child-1", tokens=7_777)
        assert pool.tokens_used == 7_777


# =============================================================================
# Async Variants
# =============================================================================


class TestAsyncMethods:
    @pytest.mark.asyncio
    async def test_reserve_async(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        alloc = await pool.reserve_async("child-1")
        assert alloc is not None
        assert alloc.id == "child-1"
        assert alloc.token_budget == 50_000

    @pytest.mark.asyncio
    async def test_reserve_async_returns_none_when_exhausted(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=50_000, max_per_child=50_000)
        )
        await pool.reserve_async("child-1")
        alloc = await pool.reserve_async("child-2")
        assert alloc is None

    @pytest.mark.asyncio
    async def test_record_usage_async(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        await pool.reserve_async("child-1")
        result = await pool.record_usage_async("child-1", tokens=10_000)
        assert result is True
        assert pool.tokens_used == 10_000

    @pytest.mark.asyncio
    async def test_record_usage_async_over_budget(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        await pool.reserve_async("child-1")
        result = await pool.record_usage_async("child-1", tokens=60_000)
        assert result is False

    @pytest.mark.asyncio
    async def test_release_async(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        await pool.reserve_async("child-1")
        assert pool.get_remaining() == 50_000
        await pool.release_async("child-1")
        assert pool.get_remaining() == 100_000

    @pytest.mark.asyncio
    async def test_full_async_lifecycle(self) -> None:
        """Simulate a full async child lifecycle."""
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=40_000)
        )
        alloc = await pool.reserve_async("worker-1")
        assert alloc is not None

        ok = await pool.record_usage_async("worker-1", tokens=5_000, cost=0.01)
        assert ok is True
        ok = await pool.record_usage_async("worker-1", tokens=10_000, cost=0.02)
        assert ok is True

        assert pool.get_remaining_for_child("worker-1") == 25_000

        await pool.release_async("worker-1")
        assert pool.get_allocation("worker-1") is None
        assert pool.get_remaining() == 85_000


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    def test_get_allocation_for_existing_child(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        pool.reserve("child-1")
        alloc = pool.get_allocation("child-1")
        assert alloc is not None
        assert alloc.id == "child-1"

    def test_get_allocation_for_unknown_child(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        assert pool.get_allocation("unknown") is None

    def test_pessimistic_accounting_prefers_reserved_over_used(self) -> None:
        """Committed = max(used, reserved). If reserved > used, remaining is
        based on reserved, not used."""
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=60_000)
        )
        pool.reserve("child-1")  # 60K reserved
        pool.record_usage("child-1", tokens=10_000)  # 10K used
        # committed = max(10K, 60K) = 60K
        assert pool.get_remaining() == 40_000

    def test_pessimistic_accounting_prefers_used_when_higher(self) -> None:
        """If used > reserved (e.g., after release), remaining is based on used."""
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=50_000)
        )
        pool.reserve("child-1")
        pool.record_usage("child-1", tokens=40_000)
        pool.release("child-1")
        # reserved back to 0, used = 40K
        # committed = max(40K, 0) = 40K
        assert pool.get_remaining() == 60_000

    def test_reserve_same_child_id_overwrites(self) -> None:
        pool = SharedBudgetPool(
            BudgetPoolConfig(total_tokens=100_000, max_per_child=30_000)
        )
        a1 = pool.reserve("child-1")
        assert a1 is not None
        # Reserve again with the same id (overwrites the dict entry)
        a2 = pool.reserve("child-1")
        assert a2 is not None
        # Both reservations counted towards reserved total
        assert pool.get_stats().active_allocations == 1
