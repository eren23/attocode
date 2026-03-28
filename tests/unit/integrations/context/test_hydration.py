"""Tests for hydration state and tier classification."""
from __future__ import annotations

import pytest

from attocode.integrations.context.hydration import (
    TIER_HUGE,
    TIER_LARGE,
    TIER_MEDIUM,
    TIER_SMALL,
    HydrationState,
    classify_tier,
    skeleton_budget,
)


class TestClassifyTier:
    def test_small_repo(self):
        assert classify_tier(500) == TIER_SMALL

    def test_small_boundary(self):
        assert classify_tier(999) == TIER_SMALL

    def test_medium_boundary(self):
        assert classify_tier(1000) == TIER_MEDIUM

    def test_medium_repo(self):
        assert classify_tier(3000) == TIER_MEDIUM

    def test_large_boundary(self):
        assert classify_tier(5000) == TIER_LARGE

    def test_large_repo(self):
        assert classify_tier(12000) == TIER_LARGE

    def test_huge_boundary(self):
        assert classify_tier(20000) == TIER_HUGE

    def test_huge_repo(self):
        assert classify_tier(50000) == TIER_HUGE

    def test_zero_files(self):
        assert classify_tier(0) == TIER_SMALL


class TestSkeletonBudget:
    def test_small_returns_all(self):
        assert skeleton_budget(TIER_SMALL, 500) == 500

    def test_medium_capped(self):
        assert skeleton_budget(TIER_MEDIUM, 3000) == 500

    def test_large_capped(self):
        assert skeleton_budget(TIER_LARGE, 10000) == 300

    def test_huge_capped(self):
        assert skeleton_budget(TIER_HUGE, 50000) == 200


class TestHydrationState:
    def test_initial_state(self):
        state = HydrationState(tier=TIER_MEDIUM, total_files=2000)
        assert state.phase == "skeleton"
        assert state.parsed_files == 0
        assert state.parse_coverage == 0.0

    def test_coverage_calculation(self):
        state = HydrationState(tier=TIER_MEDIUM, total_files=1000, parsed_files=500)
        assert state.parse_coverage == 0.5

    def test_coverage_zero_total(self):
        state = HydrationState(tier=TIER_SMALL, total_files=0)
        assert state.parse_coverage == 1.0
